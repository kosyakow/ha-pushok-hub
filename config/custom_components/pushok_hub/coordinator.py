"""Data coordinator for Pushok Hub integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import PushokHubClient, PushokAuth
from .api.models import DeviceAdapter, DeviceAttributes, DeviceDescription, DeviceFormat, DeviceState
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_USE_SSL,
    DEFAULT_PORT,
    DEFAULT_USE_SSL,
    ENTITY_TYPE_ZIGBEE,
    EVT_OBJECT_UPDATE,
    RECONNECT_INTERVAL,
    STORAGE_KEY_PRIVATE_KEY,
    STORAGE_KEY_USER_ID,
)

_LOGGER = logging.getLogger(__name__)


class PushokHubCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """Coordinator for Pushok Hub data.

    This coordinator maintains a WebSocket connection to the hub
    and receives push updates for device state changes.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            entry: Config entry for this hub
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No update_interval - we use push updates
            update_interval=None,
        )

        self.config_entry = entry
        self._client: PushokHubClient | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._devices: dict[str, DeviceDescription] = {}
        self._formats: dict[str, DeviceFormat] = {}
        self._attributes: dict[str, DeviceAttributes] = {}
        self._adapters: dict[str, DeviceAdapter] = {}  # Cached by driver name

    @property
    def client(self) -> PushokHubClient | None:
        """Get the API client."""
        return self._client

    @property
    def devices(self) -> dict[str, DeviceDescription]:
        """Get all devices."""
        return self._devices

    @property
    def formats(self) -> dict[str, DeviceFormat]:
        """Get device formats."""
        return self._formats

    @property
    def attributes(self) -> dict[str, DeviceAttributes]:
        """Get device attributes."""
        return self._attributes

    @property
    def adapters(self) -> dict[str, DeviceAdapter]:
        """Get device adapters (cached by driver name)."""
        return self._adapters

    def get_adapter_for_device(self, device_id: str) -> DeviceAdapter | None:
        """Get adapter for a specific device by its ID.

        Args:
            device_id: Device ID (IEEE address)

        Returns:
            DeviceAdapter if found, None otherwise
        """
        device = self._devices.get(device_id)
        if device and device.driver:
            return self._adapters.get(device.driver)
        return None

    async def async_setup(self) -> bool:
        """Set up the coordinator and connect to the hub.

        Returns:
            True if setup was successful
        """
        host = self.config_entry.data[CONF_HOST]
        port = self.config_entry.data.get(CONF_PORT, DEFAULT_PORT)
        use_ssl = self.config_entry.data.get(CONF_USE_SSL, DEFAULT_USE_SSL)

        # Load or create authentication keys
        private_key = self.config_entry.data.get(STORAGE_KEY_PRIVATE_KEY)
        user_id = self.config_entry.data.get(STORAGE_KEY_USER_ID)

        auth = PushokAuth(private_key_hex=private_key, user_id=user_id)

        # Save generated keys if new
        if not private_key or not user_id:
            new_data = {
                **self.config_entry.data,
                STORAGE_KEY_PRIVATE_KEY: auth.private_key_hex,
                STORAGE_KEY_USER_ID: auth.user_id_b64,
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

        self._client = PushokHubClient(
            host=host,
            port=port,
            use_ssl=use_ssl,
            auth=auth,
        )
        self._client.set_broadcast_callback(self._handle_broadcast)

        try:
            await self._client.connect()
            await self._load_devices()
            return True
        except Exception as e:
            _LOGGER.error("Failed to connect to hub: %s", e)
            self._schedule_reconnect()
            return False

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.disconnect()

    async def _load_devices(self) -> None:
        """Load all devices from the hub."""
        if not self._client:
            return

        # Get device list
        devices = await self._client.get_devices(ENTITY_TYPE_ZIGBEE)
        self._devices = {d.id: d for d in devices}

        # Load state, format, and attributes for each device
        states: dict[str, DeviceState] = {}

        for device_id, device in self._devices.items():
            try:
                state = await self._client.get_state(device_id)
                states[device_id] = state

                fmt = await self._client.get_format(device_id)
                self._formats[device_id] = fmt

                attrs = await self._client.get_attributes(device_id)
                self._attributes[device_id] = attrs

                # Load adapter if device has a driver and not already cached
                if device.driver and device.driver not in self._adapters:
                    try:
                        adapter = await self._client.get_adapter(device.driver)
                        self._adapters[device.driver] = adapter
                        _LOGGER.debug(
                            "Loaded adapter for driver %s: %s",
                            device.driver,
                            adapter.description,
                        )
                    except Exception as e:
                        _LOGGER.warning(
                            "Failed to load adapter for driver %s: %s",
                            device.driver,
                            e,
                        )

            except Exception as e:
                _LOGGER.warning("Failed to load device %s: %s", device_id, e)

        self.async_set_updated_data(states)

    @callback
    def _handle_broadcast(self, data: dict[str, Any]) -> None:
        """Handle broadcast message from hub.

        Args:
            data: Broadcast message data
        """
        evt = data.get("evt")

        if evt == EVT_OBJECT_UPDATE:
            self._handle_object_update(data)

    @callback
    def _handle_object_update(self, data: dict[str, Any]) -> None:
        """Handle object update broadcast.

        Args:
            data: Object update data with format:
            {"id": "device_ieee", "type": "zigbee", "evt": "object_update", "props": {...}}
        """
        device_id = data.get("id")  # Device IEEE address
        props = data.get("props", {})

        if not device_id:
            _LOGGER.debug("Broadcast without device id")
            return

        if device_id not in self._devices:
            _LOGGER.debug("Update for unknown device: %s", device_id)
            return

        _LOGGER.debug("Processing update for device %s: %s", device_id, props)

        # Update the device description if metadata changed
        if "lqi" in props:
            self._devices[device_id].lqi = props["lqi"]
        if "lse" in props:
            self._devices[device_id].last_seen = props["lse"]
        if "warn" in props:
            self._devices[device_id].warning = props["warn"]

        # Update state
        from .api.models import DeviceState, PropertyValue

        current_data = dict(self.data) if self.data else {}
        current_state = current_data.get(device_id)

        # Create state if it doesn't exist
        if not current_state:
            current_state = DeviceState(device_id=device_id, properties={})
            current_data[device_id] = current_state

        # Update properties
        for key, value in props.items():
            if key.isdigit() and isinstance(value, dict):
                field_id = int(key)
                current_state.properties[field_id] = PropertyValue.from_dict(value)
                _LOGGER.debug("Updated field %d = %s", field_id, value.get("value"))

        if "adptr-crc" in props:
            current_state.adapter_crc = props["adptr-crc"]

        # Notify listeners
        self.async_set_updated_data(current_data)

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        if self._reconnect_task and not self._reconnect_task.done():
            return

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect to the hub."""
        while True:
            await asyncio.sleep(RECONNECT_INTERVAL)

            if self._client and self._client.connected:
                break

            _LOGGER.info("Attempting to reconnect to hub...")

            try:
                if self._client:
                    await self._client.disconnect()
                    await self._client.connect()
                    await self._load_devices()
                    _LOGGER.info("Reconnected to hub")
                    break
            except Exception as e:
                _LOGGER.warning("Reconnection failed: %s", e)

    async def async_set_device_state(
        self,
        device_id: str,
        field: int,
        value: Any,
    ) -> bool:
        """Set device state.

        Args:
            device_id: Device ID
            field: Field ID
            value: Value to set

        Returns:
            True if successful
        """
        if not self._client:
            return False

        return await self._client.set_state(device_id, field, value)
