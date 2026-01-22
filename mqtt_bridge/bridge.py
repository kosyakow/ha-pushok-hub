"""Main bridge class for Pushok Hub MQTT Bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for importing api module as package
_root_path = Path(__file__).parent.parent
sys.path.insert(0, str(_root_path))

from custom_components.pushok_hub.api.client import PushokHubClient
from custom_components.pushok_hub.api.auth import PushokAuth
from custom_components.pushok_hub.api.models import (
    DeviceAdapter,
    DeviceAttributes,
    DeviceDescription,
    DeviceState,
    PropertyValue,
)

import aiomqtt

from .config import BridgeConfig

_LOGGER = logging.getLogger(__name__)


class PushokMqttBridge:
    """MQTT Bridge for Pushok Hub in Zigbee2MQTT format."""

    def __init__(self, config: BridgeConfig) -> None:
        """Initialize the bridge."""
        self._config = config
        self._hub_client: PushokHubClient | None = None
        self._mqtt_client: aiomqtt.Client | None = None

        self._devices: dict[str, DeviceDescription] = {}
        self._attributes: dict[str, DeviceAttributes] = {}
        self._adapters: dict[str, DeviceAdapter] = {}
        self._states: dict[str, DeviceState] = {}

        self._running = False
        self._reconnect_task: asyncio.Task | None = None

    @property
    def base_topic(self) -> str:
        """Get base MQTT topic."""
        return self._config.mqtt.base_topic

    async def start(self) -> None:
        """Start the bridge."""
        _LOGGER.info("Starting Pushok Hub MQTT Bridge")
        self._running = True

        # Connect to hub
        await self._connect_hub()

        # Connect to MQTT and run main loop
        await self._run_mqtt()

    async def stop(self) -> None:
        """Stop the bridge."""
        _LOGGER.info("Stopping Pushok Hub MQTT Bridge")
        self._running = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._hub_client:
            await self._hub_client.disconnect()

    async def _connect_hub(self) -> None:
        """Connect to Pushok Hub."""
        auth = PushokAuth(
            private_key_hex=self._config.hub.private_key,
            user_id=self._config.hub.user_id,
        )

        # Save generated keys for next run
        if not self._config.hub.private_key:
            _LOGGER.info("Generated new keys:")
            _LOGGER.info("  private_key: %s", auth.private_key_hex)
            _LOGGER.info("  user_id: %s", auth.user_id_b64)

        self._hub_client = PushokHubClient(
            host=self._config.hub.host,
            port=self._config.hub.port,
            use_ssl=self._config.hub.use_ssl,
            auth=auth,
        )
        self._hub_client.set_broadcast_callback(self._handle_hub_broadcast)

        await self._hub_client.connect()
        _LOGGER.info("Connected to Pushok Hub at %s:%d", self._config.hub.host, self._config.hub.port)

        # Load devices
        await self._load_devices()

    async def _load_devices(self) -> None:
        """Load all devices from hub."""
        if not self._hub_client:
            return

        devices = await self._hub_client.get_devices("zigbee")
        self._devices = {d.id: d for d in devices}
        _LOGGER.info("Loaded %d devices", len(self._devices))

        for device_id, device in self._devices.items():
            _LOGGER.debug("Processing device %s: %s", device_id, device.model)

            # Load state
            try:
                state = await self._hub_client.get_state(device_id)
                self._states[device_id] = state
            except Exception as e:
                _LOGGER.warning("Failed to load state for %s: %s", device_id, e)

            # Load attributes
            try:
                attrs = await self._hub_client.get_attributes(device_id)
                self._attributes[device_id] = attrs
            except Exception as e:
                _LOGGER.debug("No attributes for %s: %s", device_id, e)

            # Load adapter
            if device.driver and device.driver not in self._adapters:
                try:
                    adapter = await self._hub_client.get_adapter(device.driver)
                    self._adapters[device.driver] = adapter
                    _LOGGER.debug("Loaded adapter %s", device.driver)
                except Exception as e:
                    _LOGGER.warning("Failed to load adapter %s: %s", device.driver, e)

    async def _run_mqtt(self) -> None:
        """Run MQTT client loop."""
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self._config.mqtt.host,
                    port=self._config.mqtt.port,
                    username=self._config.mqtt.username,
                    password=self._config.mqtt.password,
                    identifier=self._config.mqtt.client_id,
                ) as client:
                    self._mqtt_client = client
                    _LOGGER.info("Connected to MQTT broker at %s:%d", self._config.mqtt.host, self._config.mqtt.port)

                    # Publish bridge state
                    await self._publish_bridge_state("online")

                    # Publish device list
                    await self._publish_bridge_devices()

                    # Publish initial states
                    await self._publish_all_states()

                    # Publish HA discovery
                    if self._config.mqtt.discovery_enabled:
                        await self._publish_discovery()

                    # Subscribe to command topics
                    await client.subscribe(f"{self.base_topic}/+/set")
                    await client.subscribe(f"{self.base_topic}/bridge/request/#")

                    # Process messages
                    async for message in client.messages:
                        await self._handle_mqtt_message(message)

            except aiomqtt.MqttError as e:
                _LOGGER.error("MQTT error: %s, reconnecting in 5s", e)
                self._mqtt_client = None
                await asyncio.sleep(5)

    def _handle_hub_broadcast(self, data: dict[str, Any]) -> None:
        """Handle broadcast message from hub."""
        evt = data.get("evt")
        if evt == "object_update":
            asyncio.create_task(self._handle_object_update(data))

    async def _handle_object_update(self, data: dict[str, Any]) -> None:
        """Handle object update from hub."""
        device_id = data.get("id")
        props = data.get("props", {})

        if not device_id or device_id not in self._devices:
            return

        device = self._devices[device_id]
        _LOGGER.debug("Update for %s: %s", self._get_friendly_name(device), props)

        # Update state
        state = self._states.get(device_id)
        if state:
            for key, value in props.items():
                if key.isdigit() and isinstance(value, dict):
                    state.properties[int(key)] = PropertyValue.from_dict(value)

        # Publish to MQTT
        await self._publish_device_state(device)

    async def _handle_mqtt_message(self, message: aiomqtt.Message) -> None:
        """Handle incoming MQTT message."""
        topic = str(message.topic)
        payload = message.payload.decode() if message.payload else ""

        _LOGGER.debug("MQTT message: %s = %s", topic, payload)

        # Handle set commands
        if topic.endswith("/set"):
            friendly_name = topic.split("/")[-2]
            await self._handle_set_command(friendly_name, payload)

    async def _handle_set_command(self, friendly_name: str, payload: str) -> None:
        """Handle set command for device."""
        device = self._find_device_by_name(friendly_name)
        if not device:
            _LOGGER.warning("Device not found: %s", friendly_name)
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            _LOGGER.warning("Invalid JSON payload: %s", payload)
            return

        adapter = self._adapters.get(device.driver) if device.driver else None

        for key, value in data.items():
            field_id = self._get_field_id_by_name(adapter, key)
            if field_id is not None:
                _LOGGER.info("Setting %s.%s (%d) = %s", friendly_name, key, field_id, value)
                if self._hub_client:
                    await self._hub_client.set_state(device.id, field_id, value)

    def _get_field_id_by_name(self, adapter: DeviceAdapter | None, name: str) -> int | None:
        """Get field ID by parameter name."""
        if not adapter:
            return None

        param = adapter.get_param_by_name(name)
        if param:
            return param.address

        # Try lowercase
        name_lower = name.lower()
        for param in adapter.params:
            if param.name and param.name.lower() == name_lower:
                return param.address

        return None

    def _find_device_by_name(self, friendly_name: str) -> DeviceDescription | None:
        """Find device by friendly name or IEEE address."""
        for device_id, device in self._devices.items():
            if self._get_friendly_name(device) == friendly_name:
                return device
            if device_id == friendly_name:
                return device
        return None

    def _get_friendly_name(self, device: DeviceDescription) -> str:
        """Get friendly name for device."""
        attrs = self._attributes.get(device.id)
        if attrs and attrs.name:
            return attrs.name
        return device.id

    async def _publish_bridge_state(self, state: str) -> None:
        """Publish bridge state."""
        if self._mqtt_client:
            await self._mqtt_client.publish(
                f"{self.base_topic}/bridge/state",
                payload=json.dumps({"state": state}),
                retain=True,
            )

    async def _publish_bridge_devices(self) -> None:
        """Publish device list."""
        if not self._mqtt_client:
            return

        devices_list = []
        for device_id, device in self._devices.items():
            adapter = self._adapters.get(device.driver) if device.driver else None
            devices_list.append({
                "ieee_address": device_id,
                "friendly_name": self._get_friendly_name(device),
                "model": device.model,
                "manufacturer": device.manufacturer,
                "definition": {
                    "description": adapter.description if adapter else device.model,
                    "model": device.model,
                    "vendor": device.manufacturer,
                } if adapter else None,
            })

        await self._mqtt_client.publish(
            f"{self.base_topic}/bridge/devices",
            payload=json.dumps(devices_list),
            retain=True,
        )

    async def _publish_all_states(self) -> None:
        """Publish all device states."""
        for device_id, device in self._devices.items():
            await self._publish_device_state(device)

    async def _publish_device_state(self, device: DeviceDescription) -> None:
        """Publish device state to MQTT."""
        if not self._mqtt_client:
            return

        state = self._states.get(device.id)
        if not state:
            return

        adapter = self._adapters.get(device.driver) if device.driver else None
        friendly_name = self._get_friendly_name(device)

        # Build state payload
        payload = {}
        for field_id, prop in state.properties.items():
            name = self._get_param_name(adapter, field_id)
            value = prop.value

            # Apply conversion if available
            if adapter:
                param = adapter.get_param_by_address(field_id)
                if param and param.labels:
                    # Convert numeric to label
                    for label, label_value in param.labels.items():
                        if label_value == value:
                            value = label
                            break

            payload[name] = value

        # Add device metadata
        payload["linkquality"] = device.lqi

        await self._mqtt_client.publish(
            f"{self.base_topic}/{friendly_name}",
            payload=json.dumps(payload),
            retain=True,
        )

        # Publish availability
        await self._mqtt_client.publish(
            f"{self.base_topic}/{friendly_name}/availability",
            payload="online" if not device.warning else "offline",
            retain=True,
        )

    def _get_param_name(self, adapter: DeviceAdapter | None, field_id: int) -> str:
        """Get parameter name by field ID."""
        if adapter:
            param = adapter.get_param_by_address(field_id)
            if param and param.name:
                return param.name
        return f"field_{field_id}"

    async def _publish_discovery(self) -> None:
        """Publish Home Assistant MQTT discovery messages."""
        if not self._mqtt_client:
            return

        prefix = self._config.mqtt.discovery_prefix

        for device_id, device in self._devices.items():
            adapter = self._adapters.get(device.driver) if device.driver else None
            friendly_name = self._get_friendly_name(device)
            state = self._states.get(device_id)

            if not adapter or not state:
                continue

            # Device info for discovery
            device_info = {
                "identifiers": [device_id],
                "name": friendly_name,
                "model": device.model,
                "manufacturer": device.manufacturer,
            }
            if adapter.url:
                device_info["configuration_url"] = adapter.url

            for param in adapter.params:
                if param.address > 200:  # Skip service fields
                    continue

                entity_id = f"{device_id}_{param.address}"
                name = param.name or f"field_{param.address}"

                config_payload = {
                    "name": name.replace("_", " ").title(),
                    "unique_id": entity_id,
                    "state_topic": f"{self.base_topic}/{friendly_name}",
                    "value_template": f"{{{{ value_json.{name} }}}}",
                    "device": device_info,
                    "availability_topic": f"{self.base_topic}/{friendly_name}/availability",
                }

                # Determine component type
                if param.param_type == "bool":
                    if param.is_writable:
                        component = "switch"
                        config_payload["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                        config_payload["payload_on"] = json.dumps({name: True})
                        config_payload["payload_off"] = json.dumps({name: False})
                        config_payload["state_on"] = True
                        config_payload["state_off"] = False
                    else:
                        component = "binary_sensor"
                elif param.param_type in ("int", "float"):
                    if param.is_writable and param.view_params.get("type") == "dropdown":
                        component = "select"
                        config_payload["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                        config_payload["options"] = list(param.labels.keys()) if param.labels else []
                        config_payload["command_template"] = f'{{{{"{ name }": "{{{{ value }}}}"}}}}'
                    elif param.is_writable:
                        component = "number"
                        config_payload["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                        config_payload["command_template"] = f'{{{{"{ name }": {{{{ value }}}}}}}}'
                        if param.min_value is not None:
                            config_payload["min"] = param.min_value
                        if param.max_value is not None:
                            config_payload["max"] = param.max_value
                    else:
                        component = "sensor"
                        unit = param.view_params.get("unit")
                        if unit:
                            # Map units
                            unit_map = {
                                "unit_C": "°C",
                                "unit_%": "%",
                                "unit_voltage": "V",
                                "unit_power": "W",
                                "unit_mA": "mA",
                            }
                            config_payload["unit_of_measurement"] = unit_map.get(unit, unit)
                else:
                    continue

                topic = f"{prefix}/{component}/{device_id}/{param.address}/config"
                await self._mqtt_client.publish(
                    topic,
                    payload=json.dumps(config_payload),
                    retain=True,
                )

        _LOGGER.info("Published MQTT discovery for %d devices", len(self._devices))
