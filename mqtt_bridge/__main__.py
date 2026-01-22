"""Entry point for Pushok Hub MQTT Bridge."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from .bridge import PushokMqttBridge
from .config import BridgeConfig


def setup_logging(level: str) -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Pushok Hub MQTT Bridge")
    parser.add_argument(
        "-c", "--config",
        type=str,
        help="Path to configuration file (YAML)",
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
        config = BridgeConfig.from_file(args.config)
    else:
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
