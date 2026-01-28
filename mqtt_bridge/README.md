# Pushok Hub MQTT Bridge

MQTT bridge for Pushok Zigbee Hub in Zigbee2MQTT-compatible format.

## Features

- Publishes device states to MQTT in Zigbee2MQTT format
- Per-property topics for simple integrations
- Multiple command formats supported
- Home Assistant MQTT auto-discovery support
- Supports all device types (sensors, switches, numbers, selects)
- Automatic reconnection on hub connection loss

## MQTT Topics

Topics use stable `device_id` (IEEE address) instead of friendly name for reliability.

### State topics
- `pushok_hub/{device_id}` - Device state (JSON with all properties)
- `pushok_hub/{device_id}/{property}` - Individual property value
- `pushok_hub/{device_id}/name` - Device friendly name
- `pushok_hub/{device_id}/availability` - Device availability (online/offline)

### Command topics (all formats supported)
- `pushok_hub/{device_id}/set` - JSON command `{"state": true}`
- `pushok_hub/{device_id}` - JSON command (same format)
- `pushok_hub/{device_id}/{property}` - Direct value `true`
- `pushok_hub/{device_id}/{property}/set` - Direct value `true`

### Bridge topics
- `pushok_hub/bridge/state` - Bridge state (online/offline)
- `pushok_hub/bridge/devices` - Device list

### Example

```bash
# Read device state
mosquitto_sub -t "pushok_hub/0x00158d0001234567/#" -v

# Output:
# pushok_hub/0x00158d0001234567 {"state":"on","power":45.2,"name":"Kitchen Socket","linkquality":120}
# pushok_hub/0x00158d0001234567/state on
# pushok_hub/0x00158d0001234567/power 45.2
# pushok_hub/0x00158d0001234567/name Kitchen Socket

# Send commands (all equivalent)
mosquitto_pub -t "pushok_hub/0x00158d0001234567/set" -m '{"state": false}'
mosquitto_pub -t "pushok_hub/0x00158d0001234567/state" -m "false"
mosquitto_pub -t "pushok_hub/0x00158d0001234567/state/set" -m "false"
```

## Installation

### Quick start

```bash
# 1. Create virtual environment and install dependencies
cd mqtt_bridge
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Copy config template
cp config.example.yaml config.yaml

# 3. Register on hub (first time only)
#    Enable registration mode on your hub first!
./run.sh --register --hub-host 192.168.1.151

# 4. Edit config (set MQTT broker address)
nano config.yaml

# 5. Run
./run.sh
```

### Two modes of operation

**Registration mode** - first time setup:
```bash
# Enable registration on hub, then run:
./run.sh --register --hub-host 192.168.1.151

# Keys will be saved to config.yaml automatically
```

**Normal mode** - regular operation:
```bash
# Uses saved keys from config.yaml
./run.sh

# With custom MQTT broker
./run.sh --mqtt-host 192.168.1.100
```

### Manual run

```bash
# From mqtt_bridge directory
.venv/bin/python -m mqtt_bridge -c config.yaml

# Registration mode
.venv/bin/python -m mqtt_bridge --register -c config.yaml --hub-host 192.168.1.151

# With CLI options
.venv/bin/python -m mqtt_bridge -c config.yaml \
  --mqtt-host 192.168.1.100 \
  --mqtt-port 1883 \
  --log-level DEBUG
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
  # Using JSON topic
  - trigger:
      platform: mqtt
      topic: "pushok_hub/0x00158d0001234567"
    action:
      service: notify.mobile_app
      data:
        message: "Temperature: {{ trigger.payload_json.temperature }}°C"

  # Using per-property topic (simpler)
  - trigger:
      platform: mqtt
      topic: "pushok_hub/0x00158d0001234567/temperature"
    action:
      service: notify.mobile_app
      data:
        message: "Temperature: {{ trigger.payload }}°C"
```

## Connection handling

The bridge automatically handles connection loss:
- Publishes `offline` status when hub connection is lost
- Attempts to reconnect every 10 seconds
- Republishes all states and discovery after reconnection
