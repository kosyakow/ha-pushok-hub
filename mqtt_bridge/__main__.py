"""Entry point for Pushok Hub MQTT Bridge."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import yaml

# Auto-configure path for API module
_this_dir = Path(__file__).parent.resolve()
_project_root = _this_dir.parent
_components_path = _project_root / "custom_components"

# Add paths if not already present
for path in [str(_project_root), str(_components_path)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from .bridge import PushokMqttBridge
from .config import BridgeConfig

_LOGGER = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def save_keys_to_config(
    config_path: str,
    private_key: str,
    user_id: str,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Save authentication keys and hub address to config file."""
    path = Path(config_path)

    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    if "hub" not in data:
        data["hub"] = {}

    data["hub"]["private_key"] = private_key
    data["hub"]["user_id"] = user_id
    if host:
        data["hub"]["host"] = host
    if port:
        data["hub"]["port"] = port

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    _LOGGER.info("Keys saved to %s", config_path)


async def register_on_hub(config: BridgeConfig, config_path: str | None) -> bool:
    """Register on hub and save keys."""
    from pushok_hub.api.auth import PushokAuth
    from pushok_hub.api.client import PushokHubClient

    print("\n" + "=" * 50)
    print("REGISTRATION MODE")
    print("=" * 50)
    print(f"\nConnecting to hub at {config.hub.host}:{config.hub.port}")
    print("\n>>> Enable registration mode on your hub NOW <<<")
    print("    (usually by pressing button on the device)")
    print("\nWaiting for connection...")

    # Generate new keys
    auth = PushokAuth()

    client = PushokHubClient(
        host=config.hub.host,
        port=config.hub.port,
        use_ssl=config.hub.use_ssl,
        auth=auth,
    )

    try:
        await client.connect()
        print("\n[OK] Successfully registered on hub!")
        print(f"\nYour keys:")
        print(f"  private_key: {auth.private_key_hex}")
        print(f"  user_id: {auth.user_id_b64}")

        # Save to config if path provided
        if config_path:
            save_keys_to_config(
                config_path,
                auth.private_key_hex,
                auth.user_id_b64,
                host=config.hub.host,
                port=config.hub.port,
            )
            print(f"\n[OK] Keys saved to {config_path}")
        else:
            print("\nAdd these to your config.yaml:")
            print("hub:")
            print(f'  host: "{config.hub.host}"')
            print(f'  port: {config.hub.port}')
            print(f'  private_key: "{auth.private_key_hex}"')
            print(f'  user_id: "{auth.user_id_b64}"')

        await client.disconnect()
        return True

    except Exception as e:
        print(f"\n[ERROR] Registration failed: {e}")
        print("\nMake sure:")
        print("  1. Hub is reachable at the specified address")
        print("  2. Registration mode is enabled on the hub")
        return False


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Pushok Hub MQTT Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Register on hub (first time setup)
  %(prog)s --register -c config.yaml --hub-host 192.168.1.151

  # Normal run
  %(prog)s -c config.yaml

  # Run with custom MQTT broker
  %(prog)s -c config.yaml --mqtt-host 192.168.1.100
"""
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        help="Path to configuration file (YAML)",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register on hub and save keys (enable registration mode on hub first)",
    )
    parser.add_argument(
        "--hub-host",
        type=str,
        help="Pushok Hub host",
    )
    parser.add_argument(
        "--hub-port",
        type=int,
        help="Pushok Hub port",
    )
    parser.add_argument(
        "--mqtt-host",
        type=str,
        help="MQTT broker host",
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        help="MQTT broker port",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Load configuration
    if args.config:
        config_path = args.config
        if Path(config_path).exists():
            config = BridgeConfig.from_file(config_path)
        else:
            config = BridgeConfig()
    else:
        config_path = None
        config = BridgeConfig.from_env()

    # Override with command line arguments
    if args.hub_host:
        config.hub.host = args.hub_host
    if args.hub_port:
        config.hub.port = args.hub_port
    if args.mqtt_host:
        config.mqtt.host = args.mqtt_host
    if args.mqtt_port:
        config.mqtt.port = args.mqtt_port
    if args.log_level:
        config.log_level = args.log_level

    setup_logging(config.log_level)

    # Registration mode
    if args.register:
        success = await register_on_hub(config, config_path)
        sys.exit(0 if success else 1)

    # Normal mode - check for keys
    if not config.hub.private_key or not config.hub.user_id:
        print("\n[ERROR] No authentication keys found!")
        print("\nRun with --register to register on hub first:")
        print(f"  python -m mqtt_bridge --register -c {config_path or 'config.yaml'} --hub-host {config.hub.host}")
        sys.exit(1)

    # Create and run bridge
    bridge = PushokMqttBridge(config)

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def shutdown_handler():
        asyncio.create_task(bridge.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_handler)

    try:
        await bridge.start()
    except KeyboardInterrupt:
        pass
    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
