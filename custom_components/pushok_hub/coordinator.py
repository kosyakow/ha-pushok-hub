"""Data coordinator for Pushok Hub integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import PushokHubClient, PushokAuth
from .api.models import (
    AdapterParam,
    DeviceAdapter,
    DeviceAttributes,
    DeviceDescription,
    DeviceFormat,
    DeviceState,
)
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_USE_SSL,
    CONF_REMOTE_MODE,
    CONF_HUB_ID,
    AUTOMATION_ENABLED_FIELD,
    CONF_IMPORT_AUTOMATIONS,
    DEFAULT_IMPORT_AUTOMATIONS,
    DEFAULT_PORT,
    DEFAULT_USE_SSL,
    DEVICE_LIST_POLL_INTERVAL,
    ENTITY_TYPE_AUTOMATION,
    ENTITY_TYPE_ZIGBEE,
    EVT_OBJECT_ADD,
    EVT_OBJECT_REMOVE,
    EVT_OBJECT_UPDATE,
    RECONNECT_INTERVAL,
    STORAGE_KEY_PRIVATE_KEY,
    STORAGE_KEY_USER_ID,
)

# Maps an automation state's datatype string to (param_type, min, max).
# Mirrors DATATYPE_INFO from iot-gate/tg-miniapp/src/components/DeviceCard.jsx.
_AUTOMATION_DATATYPES: dict[str, tuple[str, int | None, int | None]] = {
    "BOOL":   ("bool",  0, 1),
    "INT8":   ("int",  -128, 127),
    "INT16":  ("int",  -32768, 32767),
    "INT32":  ("int",  -2147483648, 2147483647),
    "INT64":  ("int",  None, None),
    "UINT8":  ("int",  0, 255),
    "UINT16": ("int",  0, 65535),
    "UINT32": ("int",  0, 4294967295),
    "UINT64": ("int",  0, None),
    "FLOAT":  ("float", None, None),
}


def _build_automation_pseudo_adapter(
    automation_id: str, attrs: DeviceAttributes
) -> DeviceAdapter:
    """Build a synthetic DeviceAdapter from an automation's local States.

    Automations don't ship an adapter through getAdapter the way zigbee devices
    do — the State descriptors live in their attributes. We mirror what the TG
    mini-app does (DeviceCard.jsx:42-69) so every platform can keep using the
    existing AdapterParam-driven entity builders.
    """
    params: list[AdapterParam] = []
    for st in attrs.states:
        if not isinstance(st, dict) or st.get("type") != "local":
            continue
        local_id = st.get("localId")
        if local_id is None:
            continue
        datatype = (st.get("datatype") or "").upper()
        param_type, min_v, max_v = _AUTOMATION_DATATYPES.get(
            datatype, ("int", None, None)
        )
        writable = bool(st.get("write"))
        name = st.get("name") or f"state_{local_id}"
        params.append(
            AdapterParam(
                address=int(local_id),
                access="rw" if writable else "r",
                param_type=param_type,
                name=name,
                description=st.get("description"),
                min_value=min_v,
                max_value=max_v,
                view_params={"type": "switch" if param_type == "bool" else "value"},
            )
        )
    return DeviceAdapter(
        driver=f"_automation_{automation_id}",
        crc=0,
        description="Pushok automation",
        device_type="automation",
        params=params,
    )

PlatformBuilder = Callable[["PushokHubCoordinator", DeviceDescription], list]


def _is_gateway_id(device_id: str | None) -> bool:
    """The hub exposes itself either as id "0" (broadcasts) or "0000…000"
    (get_devices, the all-zero zigbee IEEE). Both mean "this is the gateway,
    not a real device" and must be filtered out everywhere."""
    return bool(device_id) and set(device_id) == {"0"}


def _is_real_device(device: DeviceDescription) -> bool:
    return not _is_gateway_id(device.id)

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
        # No update_interval: state updates come from broadcast (object_update),
        # and device-list reconciliation runs on its own long-period background task.
        super().__init__(hass, _LOGGER, name=DOMAIN)

        self.config_entry = entry
        self._client: PushokHubClient | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._device_poll_task: asyncio.Task | None = None
        self._devices: dict[str, DeviceDescription] = {}
        self._formats: dict[str, DeviceFormat] = {}
        self._attributes: dict[str, DeviceAttributes] = {}
        self._adapters: dict[str, DeviceAdapter] = {}  # Cached by driver name

        # Registered platform builders for dynamic device add/remove
        self._platform_builders: list[tuple[PlatformBuilder, AddEntitiesCallback]] = []
        # Serialize add/remove against concurrent broadcasts and the periodic poller
        self._devices_lock = asyncio.Lock()

        # Whether to fetch automations alongside zigbee devices. Pulled from
        # config entry options at setup time; default on for new installs.
        self._import_automations: bool = entry.options.get(
            CONF_IMPORT_AUTOMATIONS,
            entry.data.get(CONF_IMPORT_AUTOMATIONS, DEFAULT_IMPORT_AUTOMATIONS),
        )

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

        For zigbee devices the adapter is keyed by driver name and shared
        across devices with the same driver. For automations we synthesize
        a per-automation pseudo-adapter (see _build_automation_pseudo_adapter)
        and key it by f"_automation_{id}".
        """
        device = self._devices.get(device_id)
        if not device:
            return None
        if device.is_automation:
            return self._adapters.get(f"_automation_{device_id}")
        if device.driver:
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
        remote_mode = self.config_entry.data.get(CONF_REMOTE_MODE, False)
        hub_id = self.config_entry.data.get(CONF_HUB_ID, "")

        # Build path for remote connection
        path = f"/{hub_id}/client" if remote_mode and hub_id else ""

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
            path=path,
            auth=auth,
        )
        self._client.set_broadcast_callback(self._handle_broadcast)
        self._client.set_connection_lost_callback(self._handle_connection_lost)

        try:
            await self._client.connect()
            await self._load_devices()
            self._cleanup_orphan_devices()
            self._start_device_list_poller()
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

        if self._device_poll_task:
            self._device_poll_task.cancel()
            try:
                await self._device_poll_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.disconnect()

    def register_platform_builder(
        self,
        builder: PlatformBuilder,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Register a platform's entity builder for dynamic device addition.

        Each platform calls this from its async_setup_entry. When a new device
        appears (broadcast object_add or periodic re-poll diff), the coordinator
        calls every registered builder for the new device and passes the produced
        entities to the platform's async_add_entities callback.
        """
        self._platform_builders.append((builder, async_add_entities))

    async def _load_devices(self) -> None:
        """Load all zigbee devices and (enabled) automations from the hub."""
        if not self._client:
            return

        devices = await self._fetch_all_objects()
        self._devices = {d.id: d for d in devices}

        states: dict[str, DeviceState] = {}
        for device in self._devices.values():
            state = await self._load_single_device(device)
            if state is not None:
                states[device.id] = state

        self.async_set_updated_data(states)

    async def _load_single_device(self, device: DeviceDescription) -> DeviceState | None:
        """Load state/format/attributes/adapter for a single device or automation.

        Returns the device's state (or None if it couldn't be loaded). Updates
        self._formats, self._attributes, self._adapters as side effects.
        """
        if not self._client:
            return None

        _LOGGER.debug(
            "Processing %s %s: model=%s, driver=%s",
            device.entity_type, device.id, device.model, device.driver,
        )

        state: DeviceState | None = None
        try:
            state = await self._client.get_state(device.id, entity_type=device.entity_type)
        except Exception as e:
            _LOGGER.warning("Failed to load state for %s: %s", device.id, e)

        # Format only exists for zigbee devices.
        if not device.is_automation:
            try:
                self._formats[device.id] = await self._client.get_format(device.id)
            except Exception as e:
                _LOGGER.warning("Failed to load format for %s: %s", device.id, e)

        try:
            self._attributes[device.id] = await self._client.get_attributes(
                device.id, entity_type=device.entity_type
            )
        except Exception as e:
            _LOGGER.debug("No attributes for %s: %s", device.id, e)

        if device.is_automation:
            # Automations don't expose an adapter through getAdapter — synthesize
            # one from the State descriptors in their attributes.
            attrs = self._attributes.get(device.id)
            if attrs is not None:
                self._adapters[f"_automation_{device.id}"] = (
                    _build_automation_pseudo_adapter(device.id, attrs)
                )
        elif device.driver and device.driver not in self._adapters:
            try:
                self._adapters[device.driver] = await self._client.get_adapter(device.driver)
            except Exception as e:
                _LOGGER.warning(
                    "Failed to load adapter for driver %s: %s", device.driver, e
                )

        return state

    async def async_add_device(self, device: DeviceDescription) -> None:
        """Register a new device with the coordinator and create its HA entities.

        Idempotent: if the device is already known, this is a no-op.
        """
        async with self._devices_lock:
            if device.id in self._devices:
                return

            _LOGGER.info(
                "Adding new device %s (model=%s, driver=%s)",
                device.id,
                device.model,
                device.driver,
            )

            state = await self._load_single_device(device)
            self._devices[device.id] = device

            # Merge state into coordinator data
            if state is not None:
                current_data = dict(self.data) if self.data else {}
                current_data[device.id] = state
                self.async_set_updated_data(current_data)

            # Create entities on every registered platform
            for builder, add_entities in self._platform_builders:
                try:
                    entities = builder(self, device)
                except Exception as e:
                    _LOGGER.exception("Platform builder failed for %s: %s", device.id, e)
                    continue
                if entities:
                    add_entities(entities)

    async def async_remove_device(self, device_id: str) -> None:
        """Remove a device from the coordinator and from Home Assistant.

        Removing the device from the device_registry cascades to all entities
        that belonged to it (entity_registry removes them automatically).
        """
        async with self._devices_lock:
            if device_id not in self._devices:
                return

            _LOGGER.info("Removing device %s", device_id)

            self._devices.pop(device_id, None)
            self._formats.pop(device_id, None)
            self._attributes.pop(device_id, None)
            # Adapters are shared across devices and stay cached.

            if self.data and device_id in self.data:
                new_data = dict(self.data)
                del new_data[device_id]
                self.async_set_updated_data(new_data)

            dev_reg = dr.async_get(self.hass)
            device_entry = dev_reg.async_get_device(identifiers={(DOMAIN, device_id)})
            if device_entry:
                dev_reg.async_remove_device(device_entry.id)

    async def _is_automation_enabled(self, automation_id: str) -> bool:
        """Check the automation's "enabled" bit (virtual field 255).

        Mirrors the TG mini-app convention (DeviceCard.jsx:45-50): field 255 of
        an automation's state is a bool rw flag for whether the automation is
        currently running. Disabled automations are excluded from HA — there's
        nothing to control while the automation isn't active.
        """
        if not self._client:
            return False
        try:
            state = await self._client.get_state(
                automation_id,
                entity_type=ENTITY_TYPE_AUTOMATION,
                fields=[AUTOMATION_ENABLED_FIELD],
            )
        except Exception as e:
            _LOGGER.debug("Enabled-check failed for automation %s: %s", automation_id, e)
            return False
        prop = state.properties.get(AUTOMATION_ENABLED_FIELD)
        return prop is not None and bool(prop.value)

    async def _fetch_all_objects(self) -> list[DeviceDescription]:
        """Fetch zigbee devices and (if enabled) automations from the hub.

        Disabled automations are filtered out — only those with their field-255
        enable bit set true are returned.
        """
        if not self._client:
            return []
        items = [d for d in await self._client.get_devices(ENTITY_TYPE_ZIGBEE) if _is_real_device(d)]
        if self._import_automations:
            try:
                automations = await self._client.get_devices(ENTITY_TYPE_AUTOMATION)
            except Exception as e:
                _LOGGER.debug("Failed to list automations: %s", e)
                automations = []
            kept = 0
            for auto in automations:
                if await self._is_automation_enabled(auto.id):
                    items.append(auto)
                    kept += 1
                else:
                    _LOGGER.debug("Skipping disabled automation %s", auto.id)
            _LOGGER.info(
                "Loaded %d automation(s) from hub (%d total, %d disabled)",
                kept, len(automations), len(automations) - kept,
            )
        return items

    async def _reload_after_reconnect(self) -> None:
        """Reload devices after a reconnect, applying any add/remove diff.

        Refreshes state of devices that still exist, creates HA entities for
        devices that appeared during the disconnect, and removes entities of
        devices that disappeared.
        """
        if not self._client:
            return

        old_ids = set(self._devices.keys())

        try:
            devices = await self._fetch_all_objects()
        except Exception as e:
            _LOGGER.warning("Failed to fetch device list on reconnect: %s", e)
            return

        remote_ids = {d.id for d in devices}
        added_devices = [d for d in devices if d.id not in old_ids]
        removed_ids = old_ids - remote_ids
        kept_devices = [d for d in devices if d.id in old_ids]

        # Refresh state of devices that survived (description may have updated metadata)
        new_data = dict(self.data) if self.data else {}
        for device in kept_devices:
            self._devices[device.id] = device
            try:
                state = await self._client.get_state(device.id, entity_type=device.entity_type)
                new_data[device.id] = state
            except Exception as e:
                _LOGGER.debug("State refresh failed for %s: %s", device.id, e)
        self.async_set_updated_data(new_data)

        for device in added_devices:
            await self.async_add_device(device)

        for device_id in removed_ids:
            await self.async_remove_device(device_id)

        self._cleanup_orphan_devices()

    async def _refresh_device_list(self) -> None:
        """Re-fetch the device list from the hub and apply add/remove diff.

        Safety net for missed broadcasts. Runs on a long interval; the primary
        source of truth for add/remove is the broadcast handler.
        """
        if not self._client or not self._client.connected:
            return

        try:
            devices = await self._fetch_all_objects()
        except Exception as e:
            _LOGGER.debug("Periodic device list refresh failed: %s", e)
            return

        remote_ids = {d.id for d in devices}
        known_ids = set(self._devices.keys())

        added = remote_ids - known_ids
        removed = known_ids - remote_ids

        if added or removed:
            _LOGGER.info(
                "Device list drift detected: +%d -%d", len(added), len(removed)
            )

        for device in devices:
            if device.id in added:
                await self.async_add_device(device)

        for device_id in removed:
            await self.async_remove_device(device_id)

    def _cleanup_orphan_devices(self) -> None:
        """Remove device_registry entries for devices the hub no longer has.

        Covers two cases:
        - The hub used to expose itself as device id "0" and earlier integration
          versions registered it; we no longer want it.
        - A device was unpaired in the Pushok app while HA was down; we missed
          the object_remove broadcast.

        Scoped to *this* config entry only — with multiple hubs each coordinator
        must not touch the other hub's devices.
        """
        dev_reg = dr.async_get(self.hass)
        known_ids = set(self._devices.keys())
        entries = dr.async_entries_for_config_entry(
            dev_reg, self.config_entry.entry_id
        )
        for entry in entries:
            our_ids = {ident[1] for ident in entry.identifiers if ident[0] == DOMAIN}
            if not our_ids:
                continue
            if not our_ids & known_ids:
                _LOGGER.info(
                    "Removing orphan device entry %s (ids=%s)", entry.id, our_ids
                )
                dev_reg.async_remove_device(entry.id)

    def _start_device_list_poller(self) -> None:
        """Start (or restart) the periodic device-list refresh task."""
        if self._device_poll_task and not self._device_poll_task.done():
            return
        self._device_poll_task = self.hass.async_create_background_task(
            self._device_list_poll_loop(),
            name=f"{DOMAIN}_device_list_poll",
        )

    async def _device_list_poll_loop(self) -> None:
        """Periodically refresh the device list as a safety net."""
        while True:
            try:
                await asyncio.sleep(DEVICE_LIST_POLL_INTERVAL)
                await self._refresh_device_list()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _LOGGER.exception("Device list poll loop error: %s", e)

    @callback
    def _handle_broadcast(self, data: dict[str, Any]) -> None:
        """Handle broadcast message from hub.

        Args:
            data: Broadcast message data
        """
        evt = data.get("evt")

        if evt == EVT_OBJECT_UPDATE:
            self._handle_object_update(data)
        elif evt == EVT_OBJECT_ADD:
            self._handle_object_add(data)
        elif evt == EVT_OBJECT_REMOVE:
            self._handle_object_remove(data)

    @callback
    def _handle_object_add(self, data: dict[str, Any]) -> None:
        """Handle object_add broadcast: a new device or automation appeared."""
        device_id = data.get("id")
        if not device_id or _is_gateway_id(device_id):
            return
        entity_type = data.get("type")
        if entity_type not in (ENTITY_TYPE_ZIGBEE, ENTITY_TYPE_AUTOMATION):
            return
        if entity_type == ENTITY_TYPE_AUTOMATION and not self._import_automations:
            return
        if device_id in self._devices:
            return

        # Need the full device description; re-fetch the matching list.
        self.hass.async_create_task(self._fetch_and_add_device(device_id, entity_type))

    async def _fetch_and_add_device(self, device_id: str, entity_type: str) -> None:
        """Look up a newly-added device on the hub and register it locally."""
        if not self._client:
            return
        try:
            devices = await self._client.get_devices(entity_type)
        except Exception as e:
            _LOGGER.warning("Failed to fetch devices after object_add: %s", e)
            return

        for device in devices:
            if device.id == device_id and _is_real_device(device):
                await self.async_add_device(device)
                return

        _LOGGER.debug("object_add for %s but %s not in list yet", device_id, entity_type)

    @callback
    def _handle_object_remove(self, data: dict[str, Any]) -> None:
        """Handle object_remove broadcast: a device was unpaired on the hub."""
        device_id = data.get("id")
        if not device_id:
            return
        if device_id not in self._devices:
            return
        self.hass.async_create_task(self.async_remove_device(device_id))

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

        # An automation's enable bit (field 255) toggled — add or remove its
        # HA entities accordingly. We may receive this broadcast for an
        # automation we don't yet track (just got enabled), so this branch
        # must run BEFORE the "unknown device" early-return below.
        if (
            data.get("type") == ENTITY_TYPE_AUTOMATION
            and self._import_automations
            and str(AUTOMATION_ENABLED_FIELD) in props
        ):
            enable_prop = props[str(AUTOMATION_ENABLED_FIELD)]
            if isinstance(enable_prop, dict):
                wants_enabled = bool(enable_prop.get("value"))
                currently_known = device_id in self._devices
                if wants_enabled and not currently_known:
                    _LOGGER.info("Automation %s enabled — adding entities", device_id)
                    self.hass.async_create_task(
                        self._fetch_and_add_device(device_id, ENTITY_TYPE_AUTOMATION)
                    )
                    return
                if not wants_enabled and currently_known:
                    _LOGGER.info("Automation %s disabled — removing entities", device_id)
                    self.hass.async_create_task(self.async_remove_device(device_id))
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

    def _handle_connection_lost(self) -> None:
        """Handle connection lost event from client."""
        _LOGGER.warning("Connection to hub lost, scheduling reconnect...")

        # Schedule reconnect in the event loop
        self.hass.loop.call_soon_threadsafe(self._schedule_reconnect)

        # Notify listeners that connection is lost (entities will mark as unavailable)
        self.hass.loop.call_soon_threadsafe(
            lambda: self.async_set_updated_data(self.data)
        )

    @property
    def available(self) -> bool:
        """Return True if hub is connected."""
        return self._client is not None and self._client.connected

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
                    await self._reload_after_reconnect()
                    self._start_device_list_poller()
                    _LOGGER.info("Reconnected to hub")
                    # Notify listeners that connection is restored
                    self.async_set_updated_data(self.data)
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

        Routes the request with the correct entity_type so set_state goes to
        the right object (zigbee or automation).
        """
        if not self._client:
            return False

        device = self._devices.get(device_id)
        entity_type = device.entity_type if device else ENTITY_TYPE_ZIGBEE
        return await self._client.set_state(device_id, field, value, entity_type=entity_type)
