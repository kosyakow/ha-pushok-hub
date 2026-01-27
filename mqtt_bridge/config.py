"""Configuration for Pushok Hub MQTT Bridge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class HubConfig:
    """Pushok Hub connection configuration."""

    host: str = "localhost"
    port: int = 3001
    use_ssl: bool = False
    private_key: str | None = None
    user_id: str | None = None


@dataclass
class MqttConfig:
    """MQTT broker configuration."""

    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "pushok_hub_bridge"
    base_topic: str = "pushok_hub"
    device_prefix: str = ""  # Prefix for device names (e.g., "Hub1 " -> "Hub1 Living Room Sensor")
    discovery_prefix: str = "homeassistant"
    discovery_enabled: bool = True


@dataclass
class BridgeConfig:
    """Bridge configuration."""

    hub: HubConfig = field(default_factory=HubConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    log_level: str = "INFO"

    @classmethod
    def from_file(cls, path: str | Path) -> BridgeConfig:
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BridgeConfig:
        """Create configuration from dictionary."""
        hub_data = data.get("hub", {})
        mqtt_data = data.get("mqtt", {})

        return cls(
            hub=HubConfig(
                host=hub_data.get("host", "localhost"),
                port=hub_data.get("port", 3001),
                use_ssl=hub_data.get("use_ssl", False),
                private_key=hub_data.get("private_key"),
                user_id=hub_data.get("user_id"),
            ),
            mqtt=MqttConfig(
                host=mqtt_data.get("host", "localhost"),
                port=mqtt_data.get("port", 1883),
                username=mqtt_data.get("username"),
                password=mqtt_data.get("password"),
                client_id=mqtt_data.get("client_id", "pushok_hub_bridge"),
                base_topic=mqtt_data.get("base_topic", "pushok_hub"),
                device_prefix=mqtt_data.get("device_prefix", ""),
                discovery_prefix=mqtt_data.get("discovery_prefix", "homeassistant"),
                discovery_enabled=mqtt_data.get("discovery_enabled", True),
            ),
            log_level=data.get("log_level", "INFO"),
        )

    @classmethod
    def from_env(cls) -> BridgeConfig:
        """Create configuration from environment variables."""
        return cls(
            hub=HubConfig(
                host=os.getenv("PUSHOK_HUB_HOST", "localhost"),
                port=int(os.getenv("PUSHOK_HUB_PORT", "3001")),
                use_ssl=os.getenv("PUSHOK_HUB_SSL", "false").lower() == "true",
                private_key=os.getenv("PUSHOK_HUB_PRIVATE_KEY"),
                user_id=os.getenv("PUSHOK_HUB_USER_ID"),
            ),
            mqtt=MqttConfig(
                host=os.getenv("MQTT_HOST", "localhost"),
                port=int(os.getenv("MQTT_PORT", "1883")),
                username=os.getenv("MQTT_USERNAME"),
                password=os.getenv("MQTT_PASSWORD"),
                client_id=os.getenv("MQTT_CLIENT_ID", "pushok_hub_bridge"),
                base_topic=os.getenv("MQTT_BASE_TOPIC", "pushok_hub"),
                device_prefix=os.getenv("MQTT_DEVICE_PREFIX", ""),
                discovery_prefix=os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant"),
                discovery_enabled=os.getenv("MQTT_DISCOVERY_ENABLED", "true").lower() == "true",
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
