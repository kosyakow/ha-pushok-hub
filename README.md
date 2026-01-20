# Pushok Zigbee Hub Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for Pushok Zigbee Hub.

## Features

- Local push-based communication via WebSocket
- Automatic device discovery
- Support for various Zigbee devices:
  - Switches and smart plugs
  - Sensors (temperature, humidity, power, etc.)
  - Binary sensors (motion, door/window, etc.)
  - Lights with brightness and color temperature
  - Number controls (sliders)
  - Select controls (dropdowns)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots menu and select "Custom repositories"
4. Add repository URL: `https://github.com/pushok/ha-pushok-hub`
5. Select category: "Integration"
6. Click "Add"
7. Find "Pushok Zigbee Hub" in the list and install
8. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/pushok_hub` folder
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to Settings → Devices & Services
2. Click "Add Integration"
3. Search for "Pushok Zigbee Hub"
4. Enter your hub's IP address and port

## Supported Devices

The integration automatically discovers devices connected to your Pushok Hub and creates appropriate entities based on device capabilities.

## License

MIT
