"""Main bridge class for Pushok Hub MQTT Bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

# Add parent directory to path for importing api module as package
_root_path = Path(__file__).parent.parent
sys.path.insert(0, str(_root_path))

from custom_components.pushok_hub.api.client import PushokHubClient
from custom_components.pushok_hub.api.auth import PushokAuth
from custom_components.pushok_hub.api.models import (
    AdapterParam,
    DeviceAdapter,
    DeviceAttributes,
    DeviceDescription,
    DeviceState,
    PropertyValue,
)

import paho.mqtt.client as mqtt

from .config import BridgeConfig

_LOGGER = logging.getLogger(__name__)


class PushokMqttBridge:
    """MQTT Bridge for Pushok Hub in Zigbee2MQTT format."""

    def __init__(self, config: BridgeConfig) -> None:
        """Initialize the bridge."""
        self._config = config
        self._hub_client: PushokHubClient | None = None
        self._mqtt_client: mqtt.Client | None = None
        self._mqtt_connected = False
        self._loop: asyncio.AbstractEventLoop | None = None

        self._devices: dict[str, DeviceDescription] = {}
        self._attributes: dict[str, DeviceAttributes] = {}
        self._adapters: dict[str, DeviceAdapter] = {}
        self._states: dict[str, DeviceState] = {}

        self._running = False

    @property
    def base_topic(self) -> str:
        """Get base MQTT topic."""
        return self._config.mqtt.base_topic

    async def start(self) -> None:
        """Start the bridge."""
        _LOGGER.info("Starting Pushok Hub MQTT Bridge")
        self._running = True
        self._loop = asyncio.get_event_loop()

        # Connect to hub
        await self._connect_hub()

        # Connect to MQTT
        self._connect_mqtt()

        # Run main loop
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop the bridge."""
        _LOGGER.info("Stopping Pushok Hub MQTT Bridge")
        self._running = False

        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()

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

    def _connect_mqtt(self) -> None:
        """Connect to MQTT broker."""
        self._mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._config.mqtt.client_id,
        )

        if self._config.mqtt.username:
            self._mqtt_client.username_pw_set(
                self._config.mqtt.username,
                self._config.mqtt.password,
            )

        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self._mqtt_client.on_message = self._on_mqtt_message

        _LOGGER.info("Connecting to MQTT broker at %s:%d",
                     self._config.mqtt.host, self._config.mqtt.port)

        try:
            self._mqtt_client.connect(
                self._config.mqtt.host,
                self._config.mqtt.port,
                keepalive=60,
            )
            _LOGGER.info("MQTT connect() called successfully")
        except Exception as e:
            _LOGGER.error("MQTT connect() failed: %s", e)
            return
        self._mqtt_client.loop_start()
        _LOGGER.info("MQTT loop_start() called")

    def _on_mqtt_connect(self, client: mqtt.Client, userdata: Any,
                         flags: Any, reason_code: Any, properties: Any = None) -> None:
        """Handle MQTT connect."""
        rc = reason_code.value if hasattr(reason_code, 'value') else int(reason_code)
        if rc == 0:
            _LOGGER.info("Connected to MQTT broker")
            self._mqtt_connected = True

            # Subscribe to command topics
            client.subscribe(f"{self.base_topic}/+/set")
            client.subscribe(f"{self.base_topic}/bridge/request/#")

            # Schedule async initialization
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._on_mqtt_ready(),
                    self._loop
                )
        else:
            _LOGGER.error("MQTT connection failed with code %d", rc)

    def _on_mqtt_disconnect(self, client: mqtt.Client, userdata: Any,
                            disconnect_flags: Any, reason_code: Any, properties: Any = None) -> None:
        """Handle MQTT disconnect."""
        self._mqtt_connected = False
        rc = reason_code.value if hasattr(reason_code, 'value') else int(reason_code) if reason_code else 0
        _LOGGER.warning("Disconnected from MQTT broker (rc=%d)", rc)

    def _on_mqtt_message(self, client: mqtt.Client, userdata: Any,
                         message: mqtt.MQTTMessage) -> None:
        """Handle incoming MQTT message."""
        topic = message.topic
        payload = message.payload.decode() if message.payload else ""

        _LOGGER.debug("MQTT message: %s = %s", topic, payload)

        # Handle set commands
        if topic.endswith("/set"):
            friendly_name = topic.split("/")[-2]
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._handle_set_command(friendly_name, payload),
                    self._loop
                )

    async def _on_mqtt_ready(self) -> None:
        """Called when MQTT is connected and ready."""
        # Publish bridge state
        self._publish_bridge_state("online")

        # Publish device list
        self._publish_bridge_devices()

        # Publish initial states
        self._publish_all_states()

        # Publish HA discovery
        if self._config.mqtt.discovery_enabled:
            self._publish_discovery()

    def _handle_hub_broadcast(self, data: dict[str, Any]) -> None:
        """Handle broadcast message from hub."""
        evt = data.get("evt")
        if evt == "object_update":
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._handle_object_update(data),
                    self._loop
                )

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
        self._publish_device_state(device)

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
            param = self._get_param_by_name(adapter, key)
            if param is not None:
                # Convert label to value if needed
                converted_value = self._convert_value_for_hub(param, value)
                _LOGGER.info("Setting %s.%s (%d) = %s (raw: %s)",
                           friendly_name, key, param.address, value, converted_value)
                if self._hub_client:
                    await self._hub_client.set_state(device.id, param.address, converted_value)

    def _get_param_by_name(self, adapter: DeviceAdapter | None, name: str) -> AdapterParam | None:
        """Get parameter by name."""
        if not adapter:
            return None

        param = adapter.get_param_by_name(name)
        if param:
            return param

        # Try lowercase
        name_lower = name.lower()
        for param in adapter.params:
            if param.name and param.name.lower() == name_lower:
                return param

        return None

    def _convert_value_for_hub(self, param: AdapterParam, value: Any) -> Any:
        """Convert value from MQTT format to hub format.

        - Converts label strings to their numeric/bool values
        - Applies inversion formula if defined
        """
        converted = value

        # Convert label to raw value
        if param.labels and isinstance(value, str):
            if value in param.labels:
                converted = param.labels[value]
            else:
                # Try case-insensitive match
                value_lower = value.lower()
                for label, label_value in param.labels.items():
                    if label.lower() == value_lower:
                        converted = label_value
                        break

        # Apply inversion formula (for writing to hub)
        if param.convert and "inversion" in param.convert:
            converted = self._apply_conversion(converted, param.convert["inversion"])

        return converted

    def _convert_value_from_hub(self, param: AdapterParam, value: Any) -> Any:
        """Convert value from hub format to MQTT format.

        - Applies conversion formula if defined
        - Converts numeric values to label strings
        """
        converted = value

        # Apply conversion formula (for reading from hub)
        if param.convert and "conversion" in param.convert:
            converted = self._apply_conversion(converted, param.convert["conversion"])

        # Convert raw value to label
        if param.labels:
            for label, label_value in param.labels.items():
                if label_value == converted:
                    return label

        return converted

    def _apply_conversion(self, value: Any, formula: list) -> Any:
        """Apply conversion formula to value.

        Formula format: ['self', operand, operation]
        - 'self' represents the value
        - operand is a number
        - operation is '+', '-', '*', '/'
        """
        if not formula or len(formula) < 3:
            return value

        try:
            # formula is like ['self', 100, '*'] or ['self', 100.0, '/']
            operand = float(formula[1])
            operation = formula[2]

            if operation == '+':
                return value + operand
            elif operation == '-':
                return value - operand
            elif operation == '*':
                result = value * operand
                return int(result) if isinstance(operand, int) else result
            elif operation == '/':
                return value / operand
        except (TypeError, ValueError, IndexError) as e:
            _LOGGER.warning("Failed to apply conversion %s to %s: %s", formula, value, e)

        return value

    def _find_device_by_name(self, friendly_name: str) -> DeviceDescription | None:
        """Find device by friendly name or IEEE address."""
        for device_id, device in self._devices.items():
            if self._get_friendly_name(device) == friendly_name:
                return device
            # Also try without prefix
            if self._get_friendly_name(device, with_prefix=False) == friendly_name:
                return device
            if device_id == friendly_name:
                return device
        return None

    def _get_friendly_name(self, device: DeviceDescription, with_prefix: bool = True) -> str:
        """Get friendly name for device.

        Args:
            device: Device to get name for
            with_prefix: Whether to include device_prefix from config
        """
        attrs = self._attributes.get(device.id)
        base_name = attrs.name if attrs and attrs.name else device.id

        if with_prefix and self._config.mqtt.device_prefix:
            return f"{self._config.mqtt.device_prefix}{base_name}"
        return base_name

    def _publish(self, topic: str, payload: str, retain: bool = False) -> None:
        """Publish message to MQTT."""
        if self._mqtt_client and self._mqtt_connected:
            self._mqtt_client.publish(topic, payload, retain=retain)

    def _publish_bridge_state(self, state: str) -> None:
        """Publish bridge state."""
        self._publish(
            f"{self.base_topic}/bridge/state",
            json.dumps({"state": state}),
            retain=True,
        )

    def _publish_bridge_devices(self) -> None:
        """Publish device list."""
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

        self._publish(
            f"{self.base_topic}/bridge/devices",
            json.dumps(devices_list),
            retain=True,
        )

    def _publish_all_states(self) -> None:
        """Publish all device states."""
        for device_id, device in self._devices.items():
            self._publish_device_state(device)

    def _publish_device_state(self, device: DeviceDescription) -> None:
        """Publish device state to MQTT."""
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
                if param:
                    value = self._convert_value_from_hub(param, value)

            payload[name] = value

        # Add device metadata
        payload["linkquality"] = device.lqi

        self._publish(
            f"{self.base_topic}/{friendly_name}",
            json.dumps(payload),
            retain=True,
        )

        # Publish availability
        self._publish(
            f"{self.base_topic}/{friendly_name}/availability",
            "online" if not device.warning else "offline",
            retain=True,
        )

    def _get_param_name(self, adapter: DeviceAdapter | None, field_id: int) -> str:
        """Get parameter name by field ID."""
        if adapter:
            param = adapter.get_param_by_address(field_id)
            if param and param.name:
                return param.name
        return f"field_{field_id}"

    def _publish_discovery(self) -> None:
        """Publish Home Assistant MQTT discovery messages."""
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

                entity_id = f"pushok_{device_id}_{param.address}"
                name = param.name or f"field_{param.address}"

                # Use bracket notation for names with spaces/special chars
                value_template = f"{{{{ value_json['{name}'] }}}}"

                # Create safe object_id for HA entity_id
                safe_name = name.lower().replace(" ", "_").replace("-", "_")
                object_id = f"{friendly_name}_{safe_name}".lower().replace(" ", "_")

                config_payload = {
                    "name": name.replace("_", " ").title(),
                    "unique_id": entity_id,
                    "object_id": object_id,
                    "state_topic": f"{self.base_topic}/{friendly_name}",
                    "value_template": value_template,
                    "device": device_info,
                    "availability_topic": f"{self.base_topic}/{friendly_name}/availability",
                }

                # Determine component type
                if param.param_type == "bool":
                    # Get label values for on/off states (if defined)
                    label_on = "on"
                    label_off = "off"
                    if param.labels:
                        for label, val in param.labels.items():
                            if val is True or val == 1:
                                label_on = label
                            elif val is False or val == 0:
                                label_off = label

                    if param.is_writable:
                        component = "switch"
                        config_payload["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                        config_payload["payload_on"] = json.dumps({name: True})
                        config_payload["payload_off"] = json.dumps({name: False})
                        config_payload["state_on"] = label_on
                        config_payload["state_off"] = label_off
                    else:
                        component = "binary_sensor"
                        config_payload["payload_on"] = label_on
                        config_payload["payload_off"] = label_off
                elif param.param_type in ("int", "float"):
                    if param.is_writable and param.view_params.get("type") == "dropdown":
                        component = "select"
                        config_payload["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                        config_payload["options"] = list(param.labels.keys()) if param.labels else []
                        # Use Jinja2 string concatenation to build JSON payload
                        config_payload["command_template"] = '{{ \'{"' + name + '": "\' ~ value ~ \'"}\' }}'
                    elif param.is_writable:
                        component = "number"
                        config_payload["command_topic"] = f"{self.base_topic}/{friendly_name}/set"
                        # Use Jinja2 string concatenation to build JSON payload
                        config_payload["command_template"] = '{{ \'{"' + name + '": \' ~ value ~ \'}\' }}'
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
                self._publish(topic, json.dumps(config_payload), retain=True)

        _LOGGER.info("Published MQTT discovery for %d devices", len(self._devices))
