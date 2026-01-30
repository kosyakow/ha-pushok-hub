#!/bin/bash
# Pushok Hub MQTT Bridge launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default config file
CONFIG_FILE="${SCRIPT_DIR}/config.yaml"

# Check for virtual environment
if [ -d "${SCRIPT_DIR}/.venv" ]; then
    PYTHON="${SCRIPT_DIR}/.venv/bin/python"
elif [ -d "${PROJECT_ROOT}/.venv" ]; then
    PYTHON="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON="python3"
fi

# Show help
show_help() {
    echo "Pushok Hub MQTT Bridge"
    echo ""
    echo "Usage:"
    echo "  $0                    - Run bridge (requires prior registration)"
    echo "  $0 --register         - Register on hub and save keys"
    echo "  $0 --help             - Show this help"
    echo ""
    echo "Examples:"
    echo "  # First time setup (enable registration on hub first!)"
    echo "  $0 --register --hub-host 192.168.1.151"
    echo ""
    echo "  # Normal run"
    echo "  $0"
    echo ""
    echo "  # Run with custom MQTT broker"
    echo "  $0 --mqtt-host 192.168.1.100"
}

# Parse arguments
if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    show_help
    exit 0
fi

# Check if config exists for normal run (not registration)
if [[ ! " $@ " =~ " --register " ]] && [ ! -f "$CONFIG_FILE" ]; then
    echo "Config file not found: $CONFIG_FILE"
    echo ""
    echo "For first time setup:"
    echo "  1. Copy config.example.yaml to config.yaml"
    echo "  2. Run: $0 --register --hub-host YOUR_HUB_IP"
    exit 1
fi

# Run the bridge
cd "$PROJECT_ROOT"
export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/custom_components:${PYTHONPATH:-}"
exec "$PYTHON" -m mqtt_bridge -c "$CONFIG_FILE" "$@"
