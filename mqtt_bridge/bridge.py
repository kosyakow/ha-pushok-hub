"""Main bridge class for Pushok Hub MQTT Bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Add parent directory to path for importing api module as package
_root_path = Path(__file__).parent.parent
sys.path.insert(0, str(_root_path))

from custom_components.pushok_hub.api.client import PushokHubClient
from custom_components.pushok_hub.api.auth import PushokAuth
from custom_components.pushok_hub.api.automation import build_automation_pseudo_adapter
from custom_components.pushok_hub.api.models import (
    AdapterParam,
    DeviceAdapter,
    DeviceAttributes,
    DeviceDescription,
    DeviceState,
    PropertyValue,
)
from custom_components.pushok_hub.const import (
    ENTITY_TYPE_AUTOMATION,
    ENTITY_TYPE_ZIGBEE,
    TOTAL_INCREASING_DEVICE_CLASSES,
    UNIT_MAPPING,
    resolve_sensor_device_class,
)

import paho.mqtt.client as mqtt

from .config import BridgeConfig

_LOGGER = logging.getLogger(__name__)


def _is_gateway_id(device_id: str | None) -> bool:
    """The hub exposes itself either as id "0" (broadcasts) or "0000…000"
    (get_devices). Both mean "this is the gateway, not a real device"."""
    return bool(device_id) and set(device_id) == {"0"}


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

        # Track last published payloads to ignore echo messages
        self._last_published: dict[str, str] = {}

        # MQTT reconnect backstop (real link death is caught by paho keepalive)
        self._mqtt_health_task: asyncio.Task | None = None
        self._mqtt_ever_connected = False
        self._mqtt_disconnected_since: float | None = None

        # Connection state
        self._hub_connected = False
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_interval = 10  # seconds

        # Fallback poll of device list (safety net for missed object_add/remove broadcasts)
        self._device_poll_task: asyncio.Task | None = None
        self._device_poll_interval = 600  # seconds

        # Per-device list of published MQTT discovery topics, to be cleared on removal
        self._discovery_topics: dict[str, list[str]] = {}

        # Retained discovery configs already in the broker, collected at startup
        # (device_id -> list of config topics) so we can purge orphans whose
        # device no longer exists on the hub.
        self._retained_discovery: dict[str, list[str]] = {}

        self._running = False

    @property
    def base_topic(self) -> str:
        """Get base MQTT topic."""
        return self._config.mqtt.base_topic

    def _get_adapter(self, device: DeviceDescription) -> DeviceAdapter | None:
        """Resolve the adapter for a device or automation.

        Zigbee adapters are cached by driver name; automations use a synthetic
        adapter keyed by "_automation_<id>".
        """
        if device.is_automation:
            return self._adapters.get(f"_automation_{device.id}")
        if device.driver:
            return self._adapters.get(device.driver)
        return None

    async def start(self) -> None:
        """Start the bridge."""
        _LOGGER.info("Starting Pushok Hub MQTT Bridge")
        self._running = True
        self._loop = asyncio.get_event_loop()

        # Connect to hub
        await self._connect_hub()

        # Connect to MQTT
        self._connect_mqtt()

        # Periodic device-list re-poll as a safety net
        self._device_poll_task = asyncio.create_task(self._device_list_poll_loop())

        # Active MQTT health check: round-trip ping + reconnect watchdog
        self._mqtt_health_task = asyncio.create_task(self._mqtt_health_loop())

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

        # Cancel reconnect task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        # Cancel device poll task
        if self._device_poll_task and not self._device_poll_task.done():
            self._device_poll_task.cancel()
            try:
                await self._device_poll_task
            except asyncio.CancelledError:
                pass

        # Cancel MQTT health task
        if self._mqtt_health_task and not self._mqtt_health_task.done():
            self._mqtt_health_task.cancel()
            try:
                await self._mqtt_health_task
            except asyncio.CancelledError:
                pass

        # Publish offline status before disconnecting
        self._publish_offline_status()

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
        self._hub_client.set_connection_lost_callback(self._handle_hub_connection_lost)

        await self._hub_client.connect()
        self._hub_connected = True
        _LOGGER.info("Connected to Pushok Hub at %s:%d", self._config.hub.host, self._config.hub.port)

        # Load devices
        await self._load_devices()

    async def _fetch_all_objects(self) -> list[DeviceDescription]:
        """Fetch zigbee devices and all automations from the hub.

        Every automation is imported (enabled or not) — its run state is exposed
        as an "enabled" switch.
        """
        if not self._hub_client:
            return []
        items = [
            d for d in await self._hub_client.get_devices(ENTITY_TYPE_ZIGBEE)
            if not _is_gateway_id(d.id)
        ]
        try:
            automations = [
                d for d in await self._hub_client.get_devices(ENTITY_TYPE_AUTOMATION)
                if not _is_gateway_id(d.id)
            ]
        except Exception as e:
            _LOGGER.debug("Failed to list automations: %s", e)
            automations = []
        if automations:
            _LOGGER.info("Loaded %d automation(s)", len(automations))
        items.extend(automations)
        return items

    async def _load_devices(self) -> None:
        """Load all zigbee devices and automations from hub."""
        if not self._hub_client:
            return

        devices = await self._fetch_all_objects()
        self._devices = {d.id: d for d in devices}
        _LOGGER.info("Loaded %d objects", len(self._devices))

        for device_id, device in self._devices.items():
            _LOGGER.debug("Processing %s %s: %s", device.entity_type, device_id, device.model)
            await self._load_single_device(device)

    async def _load_single_device(self, device: DeviceDescription) -> None:
        """Load state/attributes/adapter for a single device or automation."""
        if not self._hub_client:
            return

        try:
            state = await self._hub_client.get_state(
                device.id, entity_type=device.entity_type
            )
            self._states[device.id] = state
        except Exception as e:
            _LOGGER.warning("Failed to load state for %s: %s", device.id, e)

        try:
            attrs = await self._hub_client.get_attributes(
                device.id, entity_type=device.entity_type
            )
            self._attributes[device.id] = attrs
        except Exception as e:
            _LOGGER.debug("No attributes for %s: %s", device.id, e)

        if device.is_automation:
            # Automations have no adapter via getAdapter — synthesize from the
            # State descriptors in attributes.
            attrs = self._attributes.get(device.id)
            if attrs is not None:
                self._adapters[f"_automation_{device.id}"] = (
                    build_automation_pseudo_adapter(device.id, attrs)
                )
        elif device.driver and device.driver not in self._adapters:
            try:
                adapter = await self._hub_client.get_adapter(device.driver)
                self._adapters[device.driver] = adapter
                _LOGGER.debug("Loaded adapter %s", device.driver)
            except Exception as e:
                _LOGGER.warning("Failed to load adapter %s: %s", device.driver, e)

    def _handle_hub_connection_lost(self) -> None:
        """Handle connection lost event from hub client."""
        self._hub_connected = False
        _LOGGER.warning("Connection to hub lost")

        # Publish offline status
        if self._loop:
            self._loop.call_soon_threadsafe(self._publish_offline_status)
            self._loop.call_soon_threadsafe(self._schedule_reconnect)

    def _publish_offline_status(self) -> None:
        """Publish offline status for bridge and all devices."""
        # Bridge state
        self._publish_bridge_state("offline")

        # All devices unavailable
        for device_id in self._devices:
            self._publish(
                f"{self.base_topic}/{device_id}/availability",
                "offline",
                retain=True,
            )

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        if self._reconnect_task and not self._reconnect_task.done():
            return

        if self._loop:
            self._reconnect_task = self._loop.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect to the hub."""
        while self._running and not self._hub_connected:
            await asyncio.sleep(self._reconnect_interval)

            if self._hub_connected:
                break

            _LOGGER.info("Attempting to reconnect to hub...")

            try:
                if self._hub_client:
                    # Tear down the previous connection first: connect() spawns a
                    # fresh receive/watchdog task pair, and without this the old
                    # watchdog survives (its `if not self._connected` guard sees
                    # _connected flipped back to True at reconnect) and accumulates
                    # one extra probing task per hub flap. The HA coordinator does
                    # the same disconnect-before-connect.
                    await self._hub_client.disconnect()
                    await self._hub_client.connect()
                    self._hub_connected = True
                    _LOGGER.info("Reconnected to hub")

                    # Reload devices and publish online status
                    await self._load_devices()
                    self._publish_bridge_state("online")
                    self._publish_all_states()

                    if self._config.mqtt.discovery_enabled:
                        self._publish_discovery()

                    break
            except Exception as e:
                _LOGGER.warning("Reconnect failed: %s, retrying in %ds...", e, self._reconnect_interval)

    def _connect_mqtt(self) -> None:
        """Connect to MQTT broker.

        Uses connect_async() so paho's network loop handles the initial connect
        too — if the broker is unreachable at startup, paho will keep retrying
        in the background instead of leaving the bridge stuck.
        """
        self._mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._config.mqtt.client_id,
        )

        if self._config.mqtt.username:
            self._mqtt_client.username_pw_set(
                self._config.mqtt.username,
                self._config.mqtt.password,
            )

        # LWT: if the bridge process dies or loses the broker connection,
        # the broker publishes "offline" on bridge/state so HA marks the
        # bridge unavailable without us needing to send anything.
        self._mqtt_client.will_set(
            f"{self.base_topic}/bridge/state",
            json.dumps({"state": "offline"}),
            retain=True,
        )

        # Bounded reconnect backoff (paho default is 1–120s).
        self._mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self._mqtt_client.on_message = self._on_mqtt_message

        # At DEBUG, route paho's own protocol log (PINGREQ/PINGRESP, PUBACK,
        # CONNACK, and DISCONNECT reason codes) through our logger so a real
        # broker-side drop is visible instead of just its symptom.
        if self._config.log_level.upper() == "DEBUG":
            self._mqtt_client.enable_logger(_LOGGER)

        _LOGGER.info("Connecting to MQTT broker at %s:%d",
                     self._config.mqtt.host, self._config.mqtt.port)

        # connect_async never raises on DNS/refused — it queues the connect
        # for the network loop, which keeps retrying with reconnect_delay_set.
        # keepalive=30 so paho detects a broken TCP socket in ~45s instead of ~90s.
        self._mqtt_client.connect_async(
            self._config.mqtt.host,
            self._config.mqtt.port,
            keepalive=30,
        )
        self._mqtt_client.loop_start()
        _LOGGER.info("MQTT loop_start() called")

    def _on_mqtt_connect(self, client: mqtt.Client, userdata: Any,
                         flags: Any, reason_code: Any, properties: Any = None) -> None:
        """Handle MQTT connect."""
        rc = reason_code.value if hasattr(reason_code, 'value') else int(reason_code)
        if rc == 0:
            reconnect = self._mqtt_ever_connected
            _LOGGER.info("%s to MQTT broker", "Reconnected" if reconnect else "Connected")
            self._mqtt_connected = True
            self._mqtt_ever_connected = True
            self._mqtt_disconnected_since = None

            # Seed retained state and subscribe from the event loop (see
            # _on_mqtt_ready): seeding must happen strictly before subscribing so
            # the broker's retained replay of our own topics is filtered as an
            # echo. Doing it there (not here on paho's network thread) also avoids
            # iterating the device dicts concurrently with the async add/remove
            # handlers.
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
        self._mqtt_disconnected_since = time.monotonic()
        rc = reason_code.value if hasattr(reason_code, 'value') else int(reason_code) if reason_code else 0
        _LOGGER.warning("Disconnected from MQTT broker (rc=%d); paho will auto-reconnect", rc)

    def _on_mqtt_message(self, client: mqtt.Client, userdata: Any,
                         message: mqtt.MQTTMessage) -> None:
        """Paho callback wrapper.

        An exception escaping here would kill paho's network thread and silently
        freeze ALL MQTT traffic (no PINGREQ, no PUBACK, no delivery) with no
        recovery. Contain every error so a single bad message can't do that.
        """
        try:
            self._handle_mqtt_message(client, userdata, message)
        except Exception:
            _LOGGER.exception(
                "Error handling MQTT message on %s; connection kept alive",
                getattr(message, "topic", "?"),
            )

    def _handle_mqtt_message(self, client: mqtt.Client, userdata: Any,
                             message: mqtt.MQTTMessage) -> None:
        """Handle incoming MQTT message."""
        topic = message.topic
        payload = message.payload.decode(errors="replace") if message.payload else ""

        _LOGGER.debug("MQTT message: %s = %s", topic, payload)

        # Collect retained discovery configs published under the discovery prefix
        # so the startup orphan-purge knows what's already in the broker. Format:
        # {prefix}/{component}/{device_id}/{address}/config
        prefix = self._config.mqtt.discovery_prefix
        if topic.startswith(f"{prefix}/") and topic.endswith("/config"):
            if payload:  # ignore our own tombstones (empty retained payloads)
                dparts = topic.split("/")
                if len(dparts) == 5:
                    self._retained_discovery.setdefault(dparts[2], []).append(topic)
            return

        # Skip bridge topics and availability
        if "/bridge/" in topic or topic.endswith("/availability"):
            return

        # Retained messages are NOT blanket-dropped: external controllers such as
        # iobroker publish commands with retain=true, so we must accept them. Our
        # own retained state — replayed by the broker on subscribe — is filtered
        # by the value-based echo check below. _last_published is seeded before we
        # subscribe (see _on_mqtt_ready), so those replays always match and are
        # dropped, while a genuine command carries a different value and passes.
        parts = topic.split("/")
        if len(parts) < 2 or parts[0] != self.base_topic:
            return

        # Ignore echo of our own published messages
        if topic in self._last_published and self._last_published[topic] == payload:
            _LOGGER.debug("Ignoring echo message on %s", topic)
            return

        # Handle JSON set commands: {base}/{device_id}/set
        if len(parts) == 3 and parts[2] == "set":
            device_id = parts[1]
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._handle_set_command(device_id, payload),
                    self._loop
                )
            return

        # Handle individual property set: {base}/{device_id}/{property}/set
        if len(parts) == 4 and parts[3] == "set":
            device_id = parts[1]
            prop_name = parts[2]
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._handle_property_command(device_id, prop_name, payload),
                    self._loop
                )
            return

        # Handle individual property topic: {base}/{device_id}/{property}
        if len(parts) == 3 and parts[2] != "set":
            device_id = parts[1]
            prop_name = parts[2]
            device = self._devices.get(device_id)
            if device:
                adapter = self._get_adapter(device)
                if adapter:
                    param = self._get_param_by_name(adapter, prop_name)
                    if param and param.is_writable:
                        if self._loop:
                            asyncio.run_coroutine_threadsafe(
                                self._handle_property_command(device_id, prop_name, payload),
                                self._loop
                            )
            return

        # Handle main device topic with JSON: {base}/{device_id}
        if len(parts) == 2:
            device_id = parts[1]
            device = self._devices.get(device_id)
            if device and payload:
                try:
                    data = json.loads(payload)
                    adapter = self._get_adapter(device)
                    if adapter and self._has_writable_params(adapter, data):
                        _LOGGER.debug("Processing command from main topic: %s", topic)
                        if self._loop:
                            asyncio.run_coroutine_threadsafe(
                                self._handle_set_command(device_id, payload),
                                self._loop
                            )
                except json.JSONDecodeError:
                    pass

    async def _on_mqtt_ready(self) -> None:
        """Seed retained state, subscribe, then publish HA discovery.

        Order matters: we publish (and record in _last_published) our own retained
        topics BEFORE subscribing, so the broker's retained replay of those topics
        is recognized as an echo and dropped — instead of being mistaken for a
        fresh command and pushed back to the hub. Genuine commands from external
        clients (e.g. iobroker, which publishes retained) carry a different value
        and still pass through.
        """
        client = self._mqtt_client
        if not client:
            return

        # 1. Seed our own retained state first (populates _last_published).
        self._publish_bridge_state("online")
        self._publish_bridge_devices()
        self._publish_all_states()

        # 2. Now subscribe.
        client.subscribe(f"{self.base_topic}/+/set")        # JSON commands
        client.subscribe(f"{self.base_topic}/+")            # Main device topic
        client.subscribe(f"{self.base_topic}/+/+")          # Individual property topics
        client.subscribe(f"{self.base_topic}/+/+/set")      # Individual property /set topics
        client.subscribe(f"{self.base_topic}/bridge/request/#")
        _LOGGER.info("Subscribed to command topics")

        # Subscribe to our own retained discovery configs so we can find and purge
        # orphans (devices removed from the hub while we were down).
        if self._config.mqtt.discovery_enabled:
            self._retained_discovery = {}
            client.subscribe(
                f"{self._config.mqtt.discovery_prefix}/+/+/+/config"
            )

        # 3. Publish HA discovery
        if self._config.mqtt.discovery_enabled:
            self._publish_discovery()
            # Retained discovery configs stream in right after our subscribe;
            # give them a moment to arrive, then purge orphans.
            await asyncio.sleep(3)
            self._purge_orphan_discovery()

    def _purge_orphan_discovery(self) -> None:
        """Clear retained discovery configs for devices no longer on the hub.

        On startup the broker replays every retained discovery config we ever
        published. Any whose device_id isn't in the current object list belongs
        to a device/automation that was removed while we were down — publish an
        empty payload to make HA forget it.
        """
        purged = 0
        for device_id, topics in self._retained_discovery.items():
            if device_id in self._devices:
                continue
            for topic in topics:
                self._publish(topic, "", retain=True)
                purged += 1
            # The device's retained state/availability topics linger too; clear
            # the availability one so anything keying off it sees it go away.
            self._publish(
                f"{self.base_topic}/{device_id}/availability", "offline", retain=True
            )
        if purged:
            _LOGGER.info("Purged %d orphan discovery topic(s)", purged)
        self._retained_discovery = {}

    def _handle_hub_broadcast(self, data: dict[str, Any]) -> None:
        """Handle broadcast message from hub."""
        evt = data.get("evt")
        if not self._loop:
            return

        if evt == "object_update":
            asyncio.run_coroutine_threadsafe(
                self._handle_object_update(data), self._loop
            )
        elif evt == "object_add":
            device_id = data.get("id")
            obj_type = data.get("type")
            if (
                device_id
                and not _is_gateway_id(device_id)
                and obj_type in (ENTITY_TYPE_ZIGBEE, ENTITY_TYPE_AUTOMATION)
                and device_id not in self._devices
            ):
                asyncio.run_coroutine_threadsafe(
                    self._handle_object_add(device_id, obj_type), self._loop
                )
        elif evt == "object_remove":
            device_id = data.get("id")
            if device_id and device_id in self._devices:
                asyncio.run_coroutine_threadsafe(
                    self._handle_object_remove(device_id), self._loop
                )

    async def _handle_object_add(self, device_id: str, entity_type: str) -> None:
        """Fetch a newly-added device/automation and publish it."""
        if not self._hub_client or _is_gateway_id(device_id):
            return
        try:
            devices = await self._hub_client.get_devices(entity_type)
        except Exception as e:
            _LOGGER.warning("Failed to fetch objects after object_add: %s", e)
            return
        for device in devices:
            if device.id == device_id:
                await self._add_device(device)
                return
        _LOGGER.debug("object_add for %s but %s not in list yet", device_id, entity_type)

    async def _add_device(self, device: DeviceDescription) -> None:
        """Add a device locally and publish its MQTT discovery + initial state."""
        if device.id in self._devices:
            return
        _LOGGER.info("Adding new device %s (%s)", device.id, device.model)
        self._devices[device.id] = device
        await self._load_single_device(device)
        self._publish_device_state(device)
        if self._config.mqtt.discovery_enabled:
            self._publish_discovery_for_device(device)
        self._publish_bridge_devices()

    async def _handle_object_remove(self, device_id: str) -> None:
        """Remove a device locally and clear its MQTT discovery + state topics."""
        device = self._devices.pop(device_id, None)
        if not device:
            return
        _LOGGER.info("Removing device %s", device_id)
        self._states.pop(device_id, None)
        self._attributes.pop(device_id, None)
        # Adapters stay cached — shared across devices.

        # Mark device offline so HA shows the entities as unavailable while
        # discovery removal propagates.
        self._publish(
            f"{self.base_topic}/{device_id}/availability", "offline", retain=True
        )

        # Clear HA discovery — empty retained payload makes HA forget the entity.
        for topic in self._discovery_topics.pop(device_id, []):
            self._publish(topic, "", retain=True)

        self._publish_bridge_devices()

    async def _device_list_poll_loop(self) -> None:
        """Periodically refresh the device list as a safety net."""
        while self._running:
            try:
                await asyncio.sleep(self._device_poll_interval)
            except asyncio.CancelledError:
                return
            if not self._hub_connected or not self._hub_client:
                continue
            try:
                devices = await self._fetch_all_objects()
            except Exception as e:
                _LOGGER.debug("Periodic device list refresh failed: %s", e)
                continue

            remote_ids = {d.id for d in devices}
            known_ids = set(self._devices.keys())
            added = [d for d in devices if d.id not in known_ids]
            removed = known_ids - remote_ids

            if added or removed:
                _LOGGER.info(
                    "Device list drift: +%d -%d", len(added), len(removed)
                )

            for device in added:
                await self._add_device(device)
            for device_id in removed:
                await self._handle_object_remove(device_id)

    async def _mqtt_health_loop(self) -> None:
        """Backstop reconnect watchdog for MQTT.

        A real broken link is detected by paho's native keepalive (PINGREQ /
        PINGRESP at the protocol level), which fires on_disconnect and triggers
        paho's own auto-reconnect. We do NOT add an application-level round-trip
        ping: iobroker's broker does not echo a client its own publications in
        real time, so such a probe false-positives during quiet periods and
        would reconnect a perfectly healthy link (causing a retained-replay
        storm on resubscribe).

        This loop only backstops the rare case where paho reports the socket
        disconnected but its own auto-reconnect appears to have stalled.
        """
        CHECK_INTERVAL = 30     # seconds between checks
        RECONNECT_STALL = 90    # force reconnect if disconnected at least this long

        while self._running:
            try:
                await asyncio.sleep(CHECK_INTERVAL)
            except asyncio.CancelledError:
                return

            client = self._mqtt_client
            if not client or self._mqtt_connected:
                continue

            now = time.monotonic()
            since = self._mqtt_disconnected_since or now
            if self._mqtt_ever_connected and now - since > RECONNECT_STALL:
                _LOGGER.warning(
                    "MQTT still disconnected after %ds; forcing reconnect",
                    RECONNECT_STALL,
                )
                # Reconnect OFF the event loop: client.reconnect() does a
                # blocking socket.create_connection() that would otherwise freeze
                # every bridge task (hub receive loop, watchdog, callbacks) for up
                # to the connect timeout. The helper also stops paho's network
                # thread first — so we don't race its own auto-reconnect on the
                # socket — and starts a fresh one after: a bare reconnect() opens a
                # socket that nothing pumps if that thread had died, which is
                # exactly the wedged case this backstop is meant to rescue.
                if self._loop:
                    await self._loop.run_in_executor(
                        None, self._force_mqtt_reconnect, client
                    )
                self._mqtt_disconnected_since = now

    def _force_mqtt_reconnect(self, client: mqtt.Client) -> None:
        """Restart paho's network loop from a worker thread.

        Called via run_in_executor so the blocking socket connect never stalls
        the asyncio loop. loop_stop() joins the current network thread (avoiding a
        concurrent reconnect on the socket); loop_start() revives the thread that
        actually pumps the socket so CONNACK gets read and on_connect fires.
        """
        try:
            client.loop_stop()
        except Exception as e:
            _LOGGER.debug("loop_stop during forced reconnect: %s", e)
        try:
            client.reconnect()
        except Exception as e:
            _LOGGER.warning("Forced MQTT reconnect failed: %s", e)
        try:
            client.loop_start()
        except Exception as e:
            _LOGGER.warning("loop_start after forced reconnect failed: %s", e)

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

    async def _handle_set_command(self, device_id: str, payload: str) -> None:
        """Handle set command for device (JSON payload with multiple properties)."""
        device = self._devices.get(device_id)
        if not device:
            _LOGGER.warning("Device not found: %s", device_id)
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            _LOGGER.warning("Invalid JSON payload: %s", payload)
            return

        adapter = self._get_adapter(device)

        for key, value in data.items():
            param = self._get_param_by_name(adapter, key)
            if param is not None:
                # Convert label to value if needed
                converted_value = self._convert_value_for_hub(param, value)
                _LOGGER.info("Setting %s.%s (%d) = %s (raw: %s)",
                           device_id, key, param.address, value, converted_value)
                if self._hub_client:
                    await self._hub_client.set_state(
                        device.id, param.address, converted_value,
                        entity_type=device.entity_type,
                    )

    async def _handle_property_command(self, device_id: str, prop_name: str, payload: str) -> None:
        """Handle command for individual property topic."""
        device = self._devices.get(device_id)
        if not device:
            _LOGGER.warning("Device not found: %s", device_id)
            return

        adapter = self._get_adapter(device)
        param = self._get_param_by_name(adapter, prop_name)

        if not param:
            _LOGGER.warning("Property not found: %s.%s", device_id, prop_name)
            return

        if not param.is_writable:
            _LOGGER.debug("Property %s.%s is read-only", device_id, prop_name)
            return

        # Parse value from payload
        value = self._parse_property_value(payload, param)
        converted_value = self._convert_value_for_hub(param, value)

        _LOGGER.info("Setting %s.%s (%d) = %s (raw: %s)",
                     device_id, prop_name, param.address, value, converted_value)

        if self._hub_client:
            await self._hub_client.set_state(
                device.id, param.address, converted_value,
                entity_type=device.entity_type,
            )

    def _parse_property_value(self, payload: str, param: AdapterParam) -> Any:
        """Parse property value from string payload."""
        # Try JSON first
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            pass

        # Handle boolean strings
        payload_lower = payload.lower().strip()
        if payload_lower in ("true", "on", "1"):
            return True
        if payload_lower in ("false", "off", "0"):
            return False

        # Try numeric
        if param.param_type == "int":
            try:
                return int(payload)
            except ValueError:
                pass
        elif param.param_type == "float":
            try:
                return float(payload)
            except ValueError:
                pass

        # Return as string (for labels)
        return payload

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

        # Convert raw value to label — only for params whose discovery config
        # expects label payloads: bools (state_on/off), writable dropdowns
        # (select options) and enum-like sensors. Numeric params (float or
        # with a unit) must stay numeric: their discovery carries state_class,
        # and a label string there breaks HA statistics.
        if param.labels and (
            param.param_type == "bool"
            or (param.is_writable and param.view_params.get("type") == "dropdown")
            or param.is_enum_like
        ):
            for label, label_value in param.labels.items():
                if label_value == converted:
                    return label

        return converted

    def _apply_conversion(self, value: Any, formula: list) -> Any:
        """Apply conversion formula to value.

        Formula format: ['self', operand, operation]
        - 'self' represents the value
        - operand is a number
        - operation is '+', '-', '*', '/', '^', 'log10'
        """
        import math

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
            elif operation == '^':
                return value ** operand
            elif operation == 'log10':
                return math.log10(value) if value > 0 else 0
        except (TypeError, ValueError, IndexError) as e:
            _LOGGER.warning("Failed to apply conversion %s to %s: %s", formula, value, e)

        return value

    def _has_writable_params(self, adapter: DeviceAdapter, data: dict[str, Any]) -> bool:
        """Check if data contains any writable parameters."""
        for key in data.keys():
            param = self._get_param_by_name(adapter, key)
            if param and param.is_writable:
                return True
        return False

    def _get_friendly_name(self, device: DeviceDescription) -> str:
        """Get friendly name for device."""
        attrs = self._attributes.get(device.id)
        if attrs and attrs.name:
            return attrs.name
        return device.id

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
            adapter = self._get_adapter(device)
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

        adapter = self._get_adapter(device)
        friendly_name = self._get_friendly_name(device)
        device_id = device.id

        # Build state payload and collect ack statuses
        payload = {}
        ack_statuses: dict[str, bool] = {}

        for field_id, prop in state.properties.items():
            name = self._get_param_name(adapter, field_id)
            value = prop.value

            # Apply conversion if available
            if adapter:
                param = adapter.get_param_by_address(field_id)
                if param:
                    value = self._convert_value_from_hub(param, value)

            payload[name] = value
            ack_statuses[name] = prop.ack

        # Add device metadata
        payload["name"] = friendly_name
        # linkquality is a zigbee radio metric; automations don't have it.
        if not device.is_automation:
            payload["linkquality"] = device.lqi

        # Use device_id in topic (more stable than friendly_name)
        topic = f"{self.base_topic}/{device_id}"
        payload_str = json.dumps(payload)

        # Store for echo detection before publishing
        self._last_published[topic] = payload_str

        self._publish(topic, payload_str, retain=True)

        # Publish each property to separate topic
        for prop_name, prop_value in payload.items():
            prop_topic = f"{self.base_topic}/{device_id}/{prop_name}"
            # Bools must render as "true"/"false" (not Python's "True"/"False")
            # so they match the discovery state_on/off for label-less bools.
            # Check bool before str since bool is an int subclass.
            if isinstance(prop_value, bool):
                prop_payload = "true" if prop_value else "false"
            elif isinstance(prop_value, str):
                prop_payload = prop_value
            else:
                prop_payload = str(prop_value)
            self._last_published[prop_topic] = prop_payload
            self._publish(prop_topic, prop_payload, retain=True)

        # Publish ack status for each property
        for prop_name, ack_value in ack_statuses.items():
            ack_topic = f"{self.base_topic}/{device_id}/ack/{prop_name}"
            ack_payload = "true" if ack_value else "false"
            self._publish(ack_topic, ack_payload, retain=True)

        # Publish availability
        self._publish(
            f"{self.base_topic}/{device_id}/availability",
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
        """Publish Home Assistant MQTT discovery for all known devices."""
        for device in self._devices.values():
            self._publish_discovery_for_device(device)
        _LOGGER.info("Published MQTT discovery for %d devices", len(self._devices))

    def _publish_discovery_for_device(self, device: DeviceDescription) -> None:
        """Publish HA MQTT discovery messages for a single device.

        Tracks every published config topic in self._discovery_topics so it can
        be cleared when the device is removed.
        """
        prefix = self._config.mqtt.discovery_prefix
        device_id = device.id
        adapter = self._get_adapter(device)
        friendly_name = self._get_friendly_name(device)
        state = self._states.get(device_id)

        if not adapter or not state:
            return

        # Prefix automation identifiers so they can't collide with a zigbee
        # IEEE in HA's device registry (mirrors the integration). Topics still
        # use the raw device_id.
        identifier = f"auto_{device_id}" if device.is_automation else device_id
        device_info = {
            "identifiers": [identifier],
            "name": friendly_name,
            "model": "Automation" if device.is_automation else device.model,
            "manufacturer": "Pushok" if device.is_automation else device.manufacturer,
        }
        if adapter.url:
            device_info["configuration_url"] = adapter.url

        topics: list[str] = []
        for param in adapter.params:
            # Skip zigbee service fields; automation params (incl. the enabled
            # switch on field 255) are all valid.
            if not device.is_automation and param.address > 200:
                continue

            entity_id = f"pushok_{device_id}_{param.address}"
            name = param.name or f"field_{param.address}"

            safe_name = name.lower().replace(" ", "_").replace("-", "_")
            object_id = f"{friendly_name}_{safe_name}".lower().replace(" ", "_")

            prop_state_topic = f"{self.base_topic}/{device_id}/{name}"
            prop_command_topic = f"{self.base_topic}/{device_id}/{name}/set"

            config_payload = {
                "name": name.replace("_", " ").title(),
                "unique_id": entity_id,
                "object_id": object_id,
                "state_topic": prop_state_topic,
                "device": device_info,
                "availability_topic": f"{self.base_topic}/{device_id}/availability",
            }

            if param.param_type == "bool":
                if param.labels:
                    label_on = "on"
                    label_off = "off"
                    for label, val in param.labels.items():
                        if val is True or val == 1:
                            label_on = label
                        elif val is False or val == 0:
                            label_off = label
                else:
                    # Label-less bool is published as "true"/"false" by
                    # _publish_device_state, so state must match that.
                    label_on = "true"
                    label_off = "false"

                if param.is_writable:
                    component = "switch"
                    config_payload["command_topic"] = prop_command_topic
                    config_payload["payload_on"] = "true"
                    config_payload["payload_off"] = "false"
                    config_payload["state_on"] = label_on
                    config_payload["state_off"] = label_off
                else:
                    component = "binary_sensor"
                    config_payload["payload_on"] = label_on
                    config_payload["payload_off"] = label_off
            elif param.param_type in ("int", "float"):
                if param.is_writable and param.view_params.get("type") == "dropdown":
                    component = "select"
                    config_payload["command_topic"] = prop_command_topic
                    config_payload["options"] = list(param.labels.keys()) if param.labels else []
                elif param.is_writable:
                    component = "number"
                    config_payload["command_topic"] = prop_command_topic
                    if param.min_value is not None:
                        config_payload["min"] = param.min_value
                    if param.max_value is not None:
                        config_payload["max"] = param.max_value
                    # Without an explicit step HA's MQTT number defaults to 1,
                    # which forbids decimals on float params.
                    is_float = param.param_type == "float"
                    config_payload["step"] = 0.01 if is_float else 1
                    span = (
                        (param.max_value - param.min_value)
                        if param.min_value is not None and param.max_value is not None
                        else None
                    )
                    if is_float or span is None or span > 256:
                        config_payload["mode"] = "box"
                    else:
                        config_payload["mode"] = "slider"
                else:
                    component = "sensor"
                    unit = param.view_params.get("unit")
                    if unit:
                        config_payload["unit_of_measurement"] = UNIT_MAPPING.get(unit, unit)
                    # Labeled int params publish label strings (enum-like), so
                    # they must not carry a numeric state/device class.
                    if not param.is_enum_like:
                        # device_class only alongside a unit: HA rejects the
                        # whole MQTT config for unit-requiring classes without
                        # one, and then the entity is never created.
                        device_class = resolve_sensor_device_class(name, unit) if unit else None
                        if device_class:
                            config_payload["device_class"] = device_class
                        config_payload["state_class"] = (
                            "total_increasing"
                            if device_class in TOTAL_INCREASING_DEVICE_CLASSES
                            else "measurement"
                        )
            else:
                continue

            topic = f"{prefix}/{component}/{device_id}/{param.address}/config"
            self._publish(topic, json.dumps(config_payload), retain=True)
            topics.append(topic)

        self._discovery_topics[device_id] = topics
