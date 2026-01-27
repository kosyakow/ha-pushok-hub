"""WebSocket client for Pushok Hub."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import websockets
from websockets.client import WebSocketClientProtocol

from ..const import (
    CMD_ADD_USER,
    CMD_AUTHENTICATE,
    CMD_CHALLENGE,
    CMD_GET_ADAPTER,
    CMD_GET_ATTRIBUTES,
    CMD_GET_FORMAT,
    CMD_GET_STATE,
    CMD_LIST_OBJECTS,
    CMD_PUB_KEY,
    CMD_SET_STATE,
    COMMAND_TIMEOUT,
    ENTITY_TYPE_ZIGBEE,
    EVT_OBJECT_UPDATE,
    ROLE_ADMIN,
)
from .auth import PushokAuth
from .models import (
    DeviceAdapter,
    DeviceAttributes,
    DeviceDescription,
    DeviceFormat,
    DeviceState,
)

_LOGGER = logging.getLogger(__name__)


class PushokHubError(Exception):
    """Base exception for Pushok Hub errors."""


class AuthenticationError(PushokHubError):
    """Authentication failed."""


class ConnectionError(PushokHubError):
    """Connection error."""


class CommandError(PushokHubError):
    """Command execution error."""


class PushokHubClient:
    """WebSocket client for Pushok Hub."""

    def __init__(
        self,
        host: str,
        port: int = 3001,
        use_ssl: bool = False,
        auth: PushokAuth | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            host: Hub hostname or IP address
            port: WebSocket port (default 3001 for local, 443 for SSL)
            use_ssl: Use secure WebSocket (wss://)
            auth: Authentication handler (optional, will create if not provided)
        """
        self._host = host
        self._port = port
        self._use_ssl = use_ssl
        self._auth = auth or PushokAuth()

        self._ws: WebSocketClientProtocol | None = None
        self._command_id = 0
        self._pending_commands: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._receive_task: asyncio.Task | None = None
        self._broadcast_callback: Callable[[dict[str, Any]], None] | None = None
        self._connection_lost_callback: Callable[[], None] | None = None
        self._connected = False
        self._authorized = False
        self._role: int = 0

    @property
    def connected(self) -> bool:
        """Check if connected to the hub."""
        return self._connected

    @property
    def authorized(self) -> bool:
        """Check if authorized with the hub."""
        return self._authorized

    @property
    def auth(self) -> PushokAuth:
        """Get the authentication handler."""
        return self._auth

    def set_broadcast_callback(
        self, callback: Callable[[dict[str, Any]], None] | None
    ) -> None:
        """Set callback for broadcast messages.

        Args:
            callback: Function to call when broadcast is received
        """
        self._broadcast_callback = callback

    def set_connection_lost_callback(
        self, callback: Callable[[], None] | None
    ) -> None:
        """Set callback for connection lost event.

        Args:
            callback: Function to call when connection is lost
        """
        self._connection_lost_callback = callback

    async def connect(self) -> None:
        """Connect to the hub and authenticate."""
        scheme = "wss" if self._use_ssl else "ws"
        uri = f"{scheme}://{self._host}:{self._port}"

        _LOGGER.debug("Connecting to %s", uri)

        try:
            self._ws = await websockets.connect(
                uri,
                ping_interval=10,
                ping_timeout=15,
            )
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Authenticate
            await self._authenticate()
            self._authorized = True

            _LOGGER.info("Connected and authenticated to %s", self._host)

        except Exception as e:
            self._connected = False
            self._authorized = False
            raise ConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from the hub."""
        self._connected = False
        self._authorized = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        # Cancel pending commands
        for future in self._pending_commands.values():
            if not future.done():
                future.cancel()
        self._pending_commands.clear()

    async def _authenticate(self) -> None:
        """Perform authentication handshake.

        If user is not registered and hub is in free access mode (no users),
        this will automatically register the user.
        """
        # Step 1: Get gateway public key
        response = await self._send_command(CMD_PUB_KEY)
        gateway_key = response["result"]["key"]
        self._auth.set_gateway_public_key(gateway_key)

        # Step 2: Send challenge with user_id
        response = await self._send_command(
            CMD_CHALLENGE,
            {"user_id": self._auth.user_id_b64},
        )
        encrypted_nonce = response["result"]

        # Try to decrypt challenge - may fail if user not registered
        try:
            self._auth.decrypt_challenge(encrypted_nonce)
        except Exception as e:
            _LOGGER.debug("Challenge decryption failed (user may not be registered): %s", e)
            # Try to register as new user (works only if hub has no users)
            await self._try_register_user()
            return

        # Step 3: Authenticate with signed payload
        auth_payload = self._auth.create_auth_payload()
        response = await self._send_command(
            CMD_AUTHENTICATE,
            {"password": auth_payload, "version": "0.1.0"},
        )

        result = response.get("result", {})
        if not result.get("authorized"):
            # User not registered - try to register
            _LOGGER.debug("Authentication failed, trying to register user")
            await self._try_register_user()
            return

        self._role = result.get("role", 0)
        _LOGGER.debug("Authentication successful, role: %s", self._role)

    async def _try_register_user(self) -> None:
        """Try to register user on hub (works only if hub has no users)."""
        try:
            # Add user with public key
            response = await self._send_command(
                CMD_ADD_USER,
                {
                    "user_id": self._auth.user_id_b64,
                    "public_key": self._auth.public_key_b64,
                    "role": ROLE_ADMIN,
                },
            )

            if response.get("result"):
                _LOGGER.info("User registered successfully, re-authenticating")
                # Re-authenticate after registration
                await self._authenticate()
            else:
                raise AuthenticationError("Failed to register user")

        except CommandError as e:
            raise AuthenticationError(f"Registration failed: {e}") from e

    async def _send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = COMMAND_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a command and wait for response.

        Args:
            method: Command method name
            params: Command parameters
            timeout: Response timeout in seconds

        Returns:
            Response dict
        """
        if not self._ws:
            raise ConnectionError("Not connected")

        self._command_id += 1
        cmd_id = self._command_id

        command = {"id": cmd_id, "m": method}
        if params:
            command["p"] = params

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_commands[cmd_id] = future

        try:
            await self._ws.send(json.dumps(command))
            response = await asyncio.wait_for(future, timeout)

            if "error" in response:
                raise CommandError(f"{response['error']}: {response.get('msg', '')}")

            return response

        except asyncio.TimeoutError as e:
            raise CommandError(f"Command {method} timed out") from e
        finally:
            self._pending_commands.pop(cmd_id, None)

    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket."""
        if not self._ws:
            return

        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    # Binary message handling (for file operations)
                    _LOGGER.debug("Received binary message: %d bytes", len(message))
                    continue

                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    _LOGGER.warning("Invalid JSON received: %s", message[:100])
                    continue

                # Check if it's a broadcast
                if "broadcast" in data:
                    self._handle_broadcast(data["broadcast"])
                    continue

                # Check if it's a command response
                cmd_id = data.get("id")
                if cmd_id and cmd_id in self._pending_commands:
                    future = self._pending_commands[cmd_id]
                    if not future.done():
                        future.set_result(data)

        except websockets.ConnectionClosed:
            _LOGGER.info("WebSocket connection closed")
            was_connected = self._connected
            self._connected = False
            self._authorized = False
            if was_connected and self._connection_lost_callback:
                self._connection_lost_callback()
        except Exception as e:
            _LOGGER.error("Error in receive loop: %s", e)
            was_connected = self._connected
            self._connected = False
            self._authorized = False
            if was_connected and self._connection_lost_callback:
                self._connection_lost_callback()

    def _handle_broadcast(self, data: dict[str, Any]) -> None:
        """Handle broadcast message from hub."""
        evt = data.get("evt")
        _LOGGER.debug("Received broadcast: %s", evt)

        if self._broadcast_callback:
            self._broadcast_callback(data)

    # High-level API methods

    async def get_devices(
        self, entity_type: str = ENTITY_TYPE_ZIGBEE
    ) -> list[DeviceDescription]:
        """Get list of devices.

        Args:
            entity_type: Type of entities to list (zigbee, automation, gateway)

        Returns:
            List of device descriptions
        """
        response = await self._send_command(CMD_LIST_OBJECTS, {"type": entity_type})
        devices = []
        for item in response.get("result", []):
            try:
                devices.append(DeviceDescription.from_dict(item))
            except Exception as e:
                _LOGGER.warning("Failed to parse device: %s", e)
        return devices

    async def get_state(
        self,
        device_id: str,
        entity_type: str = ENTITY_TYPE_ZIGBEE,
        fields: list[int] | None = None,
    ) -> DeviceState:
        """Get device state.

        Args:
            device_id: Device ID (IEEE address or network ID)
            entity_type: Entity type
            fields: Specific fields to request (optional)

        Returns:
            Device state
        """
        params: dict[str, Any] = {"id": device_id, "type": entity_type}
        if fields:
            params["fields"] = fields

        response = await self._send_command(CMD_GET_STATE, params)
        return DeviceState.from_dict(device_id, response.get("result", {}))

    async def set_state(
        self,
        device_id: str,
        field: int,
        value: Any,
        entity_type: str = ENTITY_TYPE_ZIGBEE,
    ) -> bool:
        """Set device state.

        Args:
            device_id: Device ID
            field: Field ID to set
            value: Value to set
            entity_type: Entity type

        Returns:
            True if successful
        """
        response = await self._send_command(
            CMD_SET_STATE,
            {
                "id": device_id,
                "type": entity_type,
                "field": field,
                "value": value,
            },
        )
        return response.get("result", False)

    async def get_attributes(
        self,
        device_id: str,
        entity_type: str = ENTITY_TYPE_ZIGBEE,
    ) -> DeviceAttributes:
        """Get device attributes.

        Args:
            device_id: Device ID
            entity_type: Entity type

        Returns:
            Device attributes
        """
        response = await self._send_command(
            CMD_GET_ATTRIBUTES,
            {"id": device_id, "type": entity_type},
        )
        result = response.get("result", {})
        # Result may be a JSON string, parse it
        if isinstance(result, str):
            import json
            result = json.loads(result)
        return DeviceAttributes.from_dict(result)

    async def get_format(
        self,
        device_id: str,
        entity_type: str = ENTITY_TYPE_ZIGBEE,
    ) -> DeviceFormat:
        """Get device format (field metadata).

        Args:
            device_id: Device ID
            entity_type: Entity type

        Returns:
            Device format with field definitions
        """
        response = await self._send_command(
            CMD_GET_FORMAT,
            {"id": device_id, "type": entity_type},
        )
        return DeviceFormat.from_dict(device_id, response.get("result", {}))

    async def get_adapter(self, driver: str) -> DeviceAdapter:
        """Get device adapter (full JSON description).

        Args:
            driver: Driver name (e.g., "contact", "ts011f_v5")

        Returns:
            Device adapter with parameters, metadata, and Yandex mappings
        """
        response = await self._send_command(
            CMD_GET_ADAPTER,
            {"drv": driver},
        )
        return DeviceAdapter.from_response(driver, response.get("result", {}))
