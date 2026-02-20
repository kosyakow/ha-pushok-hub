"""Constants for the Pushok Hub integration."""

from typing import Final

DOMAIN: Final = "pushok_hub"

# Configuration
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USE_SSL: Final = "use_ssl"
CONF_REMOTE_MODE: Final = "remote_mode"
CONF_HUB_ID: Final = "hub_id"

# Defaults
DEFAULT_PORT: Final = 3001
DEFAULT_PORT_SSL: Final = 443
DEFAULT_USE_SSL: Final = False

# Remote gateway settings
REMOTE_GATEWAY_HOST: Final = "iotgate.pushok.net"
REMOTE_GATEWAY_PORT: Final = 443

# API Commands
CMD_PUB_KEY: Final = "pubKey"
CMD_CHALLENGE: Final = "challenge"
CMD_AUTHENTICATE: Final = "authenticate"
CMD_ADD_USER: Final = "addUser"
CMD_LIST_OBJECTS: Final = "listObjects"
CMD_GET_STATE: Final = "getState"
CMD_SET_STATE: Final = "setState"
CMD_GET_ATTRIBUTES: Final = "getAttributes"
CMD_SET_ATTRIBUTES: Final = "setAttributes"
CMD_GET_FORMAT: Final = "getFormat"
CMD_GET_ADAPTER: Final = "getAdapter"

# User Roles
ROLE_GUEST: Final = 0
ROLE_ADMIN: Final = 1
ROLE_USER: Final = 2

# Entity Types
ENTITY_TYPE_ZIGBEE: Final = "zigbee"
ENTITY_TYPE_AUTOMATION: Final = "automation"
ENTITY_TYPE_GATEWAY: Final = "gateway"

# Data Types (from Berry protocol)
DATA_TYPE_BOOL: Final = 0
DATA_TYPE_UINT8: Final = 1
DATA_TYPE_UINT16: Final = 2
DATA_TYPE_UINT32: Final = 3
DATA_TYPE_INT8: Final = 4
DATA_TYPE_INT16: Final = 5
DATA_TYPE_INT32: Final = 6
DATA_TYPE_FLOAT: Final = 7

# Broadcast Events
EVT_OBJECT_UPDATE: Final = "object_update"
EVT_NOTIFICATION: Final = "notification"
EVT_DEVICE_STATE_CHANGE: Final = "device_state_change"

# Timeouts
COMMAND_TIMEOUT: Final = 5.0
RECONNECT_INTERVAL: Final = 10.0

# Storage
STORAGE_KEY_PRIVATE_KEY: Final = "ec_private_key"
STORAGE_KEY_USER_ID: Final = "user_id"

# Unit mappings: adapter viewParams.unit -> HA native_unit_of_measurement
UNIT_MAPPING: Final = {
    "unit_C": "°C",
    "unit_F": "°F",
    "unit_%": "%",
    "unit_voltage": "V",
    "unit_mV": "mV",
    "unit_power": "W",
    "unit_mA": "mA",
    "unit_A": "A",
    "unit_energy": "kWh",
    "unit_lux": "lx",
    "unit_ppm": "ppm",
    "unit_ppb": "ppb",
    "unit_hPa": "hPa",
    "unit_Pa": "Pa",
    "unit_cm": "cm",
    "unit_m": "m",
    "unit_s": "s",
    "unit_min": "min",
    "unit_Hz": "Hz",
    "unit_dB": "dB",
    "unit_L": "L",
    "unit_mL": "mL",
    "unit_m3": "m³",
    "unit_ugm3": "µg/m³",
}

# Sensor device class mappings: param name -> SensorDeviceClass
SENSOR_DEVICE_CLASS_MAPPING: Final = {
    "temperature": "temperature",
    "temp": "temperature",
    "humidity": "humidity",
    "hum": "humidity",
    "pressure": "pressure",
    "battery": "battery",
    "voltage": "voltage",
    "current": "current",
    "power": "power",
    "energy": "energy",
    "illuminance": "illuminance",
    "lux": "illuminance",
    "co2": "co2",
    "pm25": "pm25",
    "pm10": "pm10",
    "voc": "volatile_organic_compounds",
    "frequency": "frequency",
    "signal_strength": "signal_strength",
    "distance": "distance",
}

# Binary sensor device class mappings: param name -> BinarySensorDeviceClass
BINARY_SENSOR_DEVICE_CLASS_MAPPING: Final = {
    "state": "opening",
    "contact": "opening",
    "open": "opening",
    "door": "door",
    "window": "window",
    "motion": "motion",
    "presense": "occupancy",
    "presence": "occupancy",
    "occupancy": "occupancy",
    "smoke": "smoke",
    "gas": "gas",
    "co": "co",
    "water_leak": "moisture",
    "leak": "moisture",
    "moisture": "moisture",
    "vibration": "vibration",
    "tamper": "tamper",
    "battery_low": "battery",
    "problem": "problem",
}

# Switch device class mappings: param name -> SwitchDeviceClass
SWITCH_DEVICE_CLASS_MAPPING: Final = {
    "outlet": "outlet",
    "switch": "switch",
}

# Maximum field ID to include in entities (fields > this are internal/service fields)
MAX_FIELD_ID: Final = 200
