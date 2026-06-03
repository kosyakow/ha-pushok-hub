# Pushok Zigbee Hub Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

[Русская версия](README.ru.md)

Home Assistant integration for Pushok Zigbee Hub.

## Features

- Local and remote connection support
- Push-based communication via WebSocket
- Automatic device discovery
- Support for various Zigbee devices:
  - Switches and smart plugs
  - Sensors (temperature, humidity, power, etc.)
  - Binary sensors (motion, door/window, etc.)
  - Lights with brightness and color temperature
  - Number controls (sliders)
  - Select controls (dropdowns)
- Imports the hub's automations and exposes their local `State` parameters as HA entities (sensor / switch / number / binary_sensor) — one HA device per automation
- Alternative mode: standalone MQTT bridge in Zigbee2MQTT-compatible format — see [`mqtt_bridge/`](mqtt_bridge/README.md)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots menu and select "Custom repositories"
4. Add repository URL: `https://github.com/kosyakow/ha-pushok-hub`
5. Select category: "Integration"
6. Click "Add"
7. Find "Pushok Zigbee Hub" in the list and install
8. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/pushok_hub` folder
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to Settings → Devices & Services
2. Click "Add Integration"
3. Search for "Pushok Zigbee Hub"
4. Enter your hub's IP address and port (hub must be in pairing mode for first-time setup)
5. The integration will register with the hub and save authentication keys

### Switching to Remote Connection

After initial local setup, you can switch to remote connection (via cloud gateway):

1. Go to Settings → Devices & Services
2. Find "Pushok Zigbee Hub" and click on it
3. Click the three dots menu → "Reconfigure"
4. Select "Remote (via cloud)" connection type
5. Enter your Hub ID

This allows you to access your hub from anywhere without exposing it to the internet. Authentication keys are preserved when switching connection types.

## Supported Devices

The integration automatically discovers devices connected to your Pushok Hub and creates appropriate entities based on device capabilities.

## Hub Automations

Pushok hub runs its own flattened state-machine automations. Each automation has internal `State` variables — setpoints, modes, flags — that the integration imports as HA entities (`State.type == "local"`):

- Read-only states become `sensor` or `binary_sensor`
- Writable states become `number` or `switch`
- Each automation appears as a separate device in HA with all its states grouped under it

Toggle this behavior in the integration's options (Settings → Devices & Services → Pushok Hub → Configure). Disabling it removes the automation devices without affecting zigbee ones.

## MQTT Bridge (optional)

A standalone MQTT bridge is shipped alongside the integration. It exposes your hub's devices as Zigbee2MQTT-style MQTT topics and supports Home Assistant MQTT auto-discovery, so devices appear in HA via the standard MQTT integration instead of via this custom one.

Consider it if you already use MQTT in your setup, want Zigbee2MQTT-compatible topics for third-party tools, or prefer not to run a custom integration. Full setup and topic reference: [`mqtt_bridge/README.md`](mqtt_bridge/README.md).

## License

MIT
