# Pushok Hub MQTT Bridge

MQTT bridge for Pushok Zigbee Hub in Zigbee2MQTT-compatible format.

## Features

- Publishes device states to MQTT in Zigbee2MQTT format
- Accepts commands via MQTT
- Home Assistant MQTT auto-discovery support
- Supports all device types (sensors, switches, numbers, selects)

## MQTT Topics

### State topics
- `pushok_hub/{friendly_name}` - Device state (JSON)
- `pushok_hub/{friendly_name}/availability` - Device availability (online/offline)

### Command topics
- `pushok_hub/{friendly_name}/set` - Set device state (JSON)

### Bridge topics
- `pushok_hub/bridge/state` - Bridge state
- `pushok_hub/bridge/devices` - Device list

## Installation

### Using pip

```bash
pip install -r requirements.txt
python -m mqtt_bridge -c config.yaml
```

### Using Docker

```bash
docker-compose up -d
```

## Configuration

### Config file (config.yaml)

```yaml
hub:
  host: "192.168.1.151"
  port: 3001
  use_ssl: false

mqtt:
  host: "localhost"
  port: 1883
  base_topic: "pushok_hub"
  discovery_enabled: true

log_level: "INFO"
```

### Environment variables

- `PUSHOK_HUB_HOST` - Hub IP address
- `PUSHOK_HUB_PORT` - Hub port (default: 3001)
- `PUSHOK_HUB_SSL` - Use SSL (default: false)
- `PUSHOK_HUB_PRIVATE_KEY` - Authentication private key
- `PUSHOK_HUB_USER_ID` - User ID
- `MQTT_HOST` - MQTT broker host
- `MQTT_PORT` - MQTT broker port (default: 1883)
- `MQTT_USERNAME` - MQTT username
- `MQTT_PASSWORD` - MQTT password
- `MQTT_BASE_TOPIC` - Base topic (default: pushok_hub)
- `MQTT_DISCOVERY_ENABLED` - Enable HA discovery (default: true)
- `LOG_LEVEL` - Logging level (default: INFO)

## Example usage with Home Assistant

1. Start the bridge
2. Add MQTT integration in Home Assistant
3. Devices will be auto-discovered

Or use in your automations:

```yaml
automation:
  - trigger:
      platform: mqtt
      topic: "pushok_hub/Living Room Sensor"
    action:
      service: notify.mobile_app
      data:
        message: "Temperature: {{ trigger.payload_json.temperature }}°C"
```
