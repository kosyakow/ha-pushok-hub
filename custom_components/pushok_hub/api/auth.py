"""Authentication module for Pushok Hub using ECDSA P-256 + AES-GCM."""

from __future__ import annotations

import base64
import os
import logging
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ec import (
        EllipticCurvePrivateKey,
        EllipticCurvePublicKey,
    )

_LOGGER = logging.getLogger(__name__)


class PushokAuth:
    """Handles ECDSA P-256 authentication with the hub."""

    def __init__(
        self,
        private_key_hex: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Initialize authentication.

        Args:
            private_key_hex: Hex-encoded 32-byte private key (optional, will generate if not provided)
            user_id: Base64-encoded 32-byte user ID (optional, will generate if not provided)
        """
        if private_key_hex:
            self._private_key = self._load_private_key(private_key_hex)
        else:
            self._private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

        if user_id:
            self._user_id = base64.b64decode(user_id)
        else:
            self._user_id = os.urandom(32)

        self._gateway_public_key: EllipticCurvePublicKey | None = None
        self._shared_key: bytes | None = None
        self._dev_nonce: bytes | None = None
        self._user_nonce: bytes | None = None  # Saved for gateway signature verification

    @property
    def private_key_hex(self) -> str:
        """Get private key as hex string for storage."""
        private_bytes = self._private_key.private_numbers().private_value
        return private_bytes.to_bytes(32, "big").hex()

    @property
    def user_id_b64(self) -> str:
        """Get user ID as base64 string for storage."""
        return base64.b64encode(self._user_id).decode()

    @property
    def public_key_bytes(self) -> bytes:
        """Get public key as uncompressed bytes (65 bytes)."""
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )

    @property
    def public_key_b64(self) -> str:
        """Get public key as base64 string for registration."""
        return base64.b64encode(self.public_key_bytes).decode()

    def _load_private_key(self, hex_key: str) -> EllipticCurvePrivateKey:
        """Load private key from hex string."""
        private_value = int(hex_key, 16)
        return ec.derive_private_key(private_value, ec.SECP256R1(), default_backend())

    def set_gateway_public_key(self, key_b64: str) -> None:
        """Set gateway public key from base64-encoded bytes.

        Args:
            key_b64: Base64-encoded uncompressed public key (65 bytes)
        """
        key_bytes = base64.b64decode(key_b64)
        self._gateway_public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), key_bytes
        )
        # Compute shared key using ECDH (raw, no HKDF)
        self._shared_key = self._private_key.exchange(ec.ECDH(), self._gateway_public_key)

    def decrypt_challenge(self, encrypted_nonce_b64: str) -> bytes:
        """Decrypt the challenge (dev_nonce) from the hub.

        Args:
            encrypted_nonce_b64: Base64-encoded encrypted nonce with GCM tag

        Returns:
            Decrypted dev_nonce (32 bytes)
        """
        if not self._shared_key:
            raise RuntimeError("Gateway public key not set")

        encrypted = base64.b64decode(encrypted_nonce_b64)
        # AES-GCM with IV=0 (12 zero bytes) for challenge
        aesgcm = AESGCM(self._shared_key)
        iv = bytes(12)
        self._dev_nonce = aesgcm.decrypt(iv, encrypted, None)
        return self._dev_nonce

    def create_auth_payload(self) -> str:
        """Create encrypted authentication payload.

        Returns:
            Base64-encoded encrypted payload with signature
        """
        if not self._shared_key or not self._dev_nonce:
            raise RuntimeError("Challenge not completed")

        # Generate user nonce and save for gateway signature verification
        user_nonce = os.urandom(32)
        self._user_nonce = user_nonce

        # Sign: dev_nonce || user_nonce
        message = self._dev_nonce + user_nonce
        signature = self._private_key.sign(message, ec.ECDSA(hashes.SHA256()))

        # Build payload: signature + user_nonce (no public_key - already known to hub)
        payload = signature + user_nonce

        # Encrypt with AES-GCM, IV = dev_nonce[0:12]
        aesgcm = AESGCM(self._shared_key)
        iv = self._dev_nonce[:12]
        encrypted = aesgcm.encrypt(iv, payload, None)

        return base64.b64encode(encrypted).decode()

    def verify_gateway_signature(self, encrypted_signature_b64: str) -> bool:
        """Verify the gateway's response signature.

        Args:
            encrypted_signature_b64: Base64-encoded encrypted signature

        Returns:
            True if signature is valid
        """
        if not self._shared_key or not self._dev_nonce or not self._gateway_public_key:
            raise RuntimeError("Authentication not completed")

        try:
            encrypted = base64.b64decode(encrypted_signature_b64)
            aesgcm = AESGCM(self._shared_key)
            iv = self._dev_nonce[:12]
            decrypted = aesgcm.decrypt(iv, encrypted, None)

            # Gateway signs user_nonce (the same we sent in authenticate)
            # Signature is in ASN.1 DER format
            signature = decrypted

            # Verify signature over user_nonce
            if not self._user_nonce:
                raise RuntimeError("User nonce not set")
            self._gateway_public_key.verify(
                signature, self._user_nonce, ec.ECDSA(hashes.SHA256())
            )
            return True
        except Exception as e:
            _LOGGER.warning("Gateway signature verification failed: %s", e)
            return False
