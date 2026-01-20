#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone test script for Pushok Hub authentication.

Usage:
    python3 test_auth.py <hub_host> [port]

Example:
    python3 test_auth.py 192.168.1.100
    python3 test_auth.py 192.168.1.100 3001

Requirements:
    pip3 install cryptography websockets
"""

import asyncio
import base64
import json
import logging
import os
import sys
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

import websockets

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
_LOGGER = logging.getLogger(__name__)


class PushokAuth:
    """ECDSA P-256 + AES-GCM authentication."""

    def __init__(self):
        self._private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        self._user_id = os.urandom(32)
        self._gateway_public_key = None
        self._shared_key = None
        self._dev_nonce = None
        self._user_nonce = None

    @property
    def user_id_b64(self) -> str:
        return base64.b64encode(self._user_id).decode()

    @property
    def public_key_b64(self) -> str:
        key_bytes = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return base64.b64encode(key_bytes).decode()

    def set_gateway_public_key(self, key_b64: str):
        key_bytes = base64.b64decode(key_b64)
        self._gateway_public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), key_bytes
        )
        # Raw ECDH shared key (no HKDF)
        self._shared_key = self._private_key.exchange(ec.ECDH(), self._gateway_public_key)
        _LOGGER.debug("Shared key computed, length: %d", len(self._shared_key))

    def decrypt_challenge(self, encrypted_nonce_b64: str) -> bytes:
        encrypted = base64.b64decode(encrypted_nonce_b64)
        _LOGGER.debug("Challenge data length: %d", len(encrypted))

        aesgcm = AESGCM(self._shared_key)
        iv = bytes(12)  # 12 zero bytes
        self._dev_nonce = aesgcm.decrypt(iv, encrypted, None)
        _LOGGER.debug("Decrypted dev_nonce, length: %d", len(self._dev_nonce))
        return self._dev_nonce

    def create_auth_payload(self) -> str:
        self._user_nonce = os.urandom(32)

        # Sign: dev_nonce || user_nonce
        message = self._dev_nonce + self._user_nonce
        signature = self._private_key.sign(message, ec.ECDSA(hashes.SHA256()))
        _LOGGER.debug("Signature length: %d", len(signature))

        # Payload: signature + user_nonce
        payload = signature + self._user_nonce

        # Encrypt with AES-GCM, IV = dev_nonce[0:12]
        aesgcm = AESGCM(self._shared_key)
        iv = self._dev_nonce[:12]
        encrypted = aesgcm.encrypt(iv, payload, None)

        return base64.b64encode(encrypted).decode()


class PushokHubClient:
    """WebSocket client for Pushok Hub."""

    def __init__(self, host: str, port: int = 3001):
        self._host = host
        self._port = port
        self._auth = PushokAuth()
        self._ws = None
        self._command_id = 0

    async def connect(self):
        uri = f"ws://{self._host}:{self._port}"
        _LOGGER.info("Connecting to %s", uri)

        self._ws = await websockets.connect(uri, ping_interval=10, ping_timeout=15)
        _LOGGER.info("WebSocket connected")

        # Authenticate
        await self._authenticate()

    async def disconnect(self):
        if self._ws:
            await self._ws.close()

    async def _send_command(self, method: str, params: dict = None) -> dict:
        self._command_id += 1
        command = {"id": self._command_id, "m": method}
        if params:
            command["p"] = params

        _LOGGER.debug("Sending: %s", json.dumps(command))
        await self._ws.send(json.dumps(command))

        response = await self._ws.recv()
        data = json.loads(response)
        _LOGGER.debug("Received: %s", json.dumps(data)[:200])

        if "error" in data:
            raise Exception(f"{data['error']}: {data.get('msg', '')}")

        return data

    async def _authenticate(self):
        _LOGGER.info("Starting authentication...")
        _LOGGER.info("User ID: %s", self._auth.user_id_b64)

        # Step 1: Get gateway public key
        _LOGGER.info("Step 1: Getting gateway public key...")
        response = await self._send_command("pubKey")
        gateway_key = response["result"]["key"]
        _LOGGER.info("Gateway public key: %s...", gateway_key[:40])
        self._auth.set_gateway_public_key(gateway_key)

        # Step 2: Challenge
        _LOGGER.info("Step 2: Sending challenge...")
        response = await self._send_command("challenge", {"user_id": self._auth.user_id_b64})
        encrypted_nonce = response["result"]
        _LOGGER.info("Challenge response: %s...", encrypted_nonce[:40])

        try:
            self._auth.decrypt_challenge(encrypted_nonce)
            _LOGGER.info("Challenge decrypted successfully")
        except Exception as e:
            _LOGGER.error("Challenge decryption failed: %s", e)
            _LOGGER.info("User not registered, trying to register...")
            await self._register_user()
            return

        # Step 3: Authenticate
        _LOGGER.info("Step 3: Authenticating...")
        auth_payload = self._auth.create_auth_payload()
        response = await self._send_command("authenticate", {
            "password": auth_payload,
            "version": "0.1.0"
        })

        result = response.get("result", {})
        if result.get("authorized"):
            _LOGGER.info("Authentication successful! Role: %s", result.get("role"))
        else:
            _LOGGER.error("Authentication failed!")
            raise Exception("Authentication failed")

    async def _register_user(self):
        _LOGGER.info("Registering new user...")
        response = await self._send_command("addUser", {
            "user_id": self._auth.user_id_b64,
            "public_key": self._auth.public_key_b64,
            "role": 1  # admin
        })

        if response.get("result"):
            _LOGGER.info("User registered, re-authenticating...")
            await self._authenticate()
        else:
            raise Exception("Failed to register user")

    async def get_devices(self) -> list:
        response = await self._send_command("listObjects", {"type": "zigbee"})
        return response.get("result", [])


async def test_connection(host: str, port: int):
    _LOGGER.info("=" * 60)
    _LOGGER.info("Testing Pushok Hub connection")
    _LOGGER.info("Host: %s:%d", host, port)
    _LOGGER.info("=" * 60)

    client = PushokHubClient(host, port)

    try:
        await client.connect()

        _LOGGER.info("Fetching devices...")
        devices = await client.get_devices()
        _LOGGER.info("Found %d devices:", len(devices))

        for device in devices:
            _LOGGER.info("  - %s: %s %s",
                device.get("id"),
                device.get("mnf"),
                device.get("mdl")
            )

    except Exception as e:
        _LOGGER.error("Test failed: %s", e, exc_info=True)

    finally:
        await client.disconnect()
        _LOGGER.info("Disconnected")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3001

    asyncio.run(test_connection(host, port))


if __name__ == "__main__":
    main()
