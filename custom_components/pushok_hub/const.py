"""Constants for the Pushok Hub integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pushok_hub"

# Configuration
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USE_SSL: Final = "use_ssl"
CONF_REMOTE_MODE: Final = "remote_mode"
CONF_HUB_ID: Final = "hub_id"

# Virtual field id for an automation's "enabled" bit. The hub returns it via
# getState; the field isn't part of the automation's State descriptors.
AUTOMATION_ENABLED_FIELD: Final = 255

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
EVT_OBJECT_ADD: Final = "object_add"
EVT_OBJECT_REMOVE: Final = "object_remove"
EVT_NOTIFICATION: Final = "notification"
EVT_DEVICE_STATE_CHANGE: Final = "device_state_change"

# Timeouts
COMMAND_TIMEOUT: Final = 5.0
RECONNECT_INTERVAL: Final = 10.0
# Fallback re-poll of the device list (safety net for missed object_add/object_remove broadcasts)
DEVICE_LIST_POLL_INTERVAL: Final = 600.0

# Storage
STORAGE_KEY_PRIVATE_KEY: Final = "ec_private_key"
STORAGE_KEY_USER_ID: Final = "user_id"

# Unit mappings: adapter viewParams.unit -> HA native_unit_of_measurement
#
# Keys mirror the canonical unit dictionary of zigbee-remote-app
# (app/pushok_iot/assets/locales/drivers_locale_en.json) — the hub only ever
# sends keys from that dictionary. Keep the two in sync when units are added
# there. Values follow HA-native spellings where HA is picky about them
# ("lx" not "lux", "d" not "days", "L" not "l", "var" not "VAr"); the rest
# match the app's English display values.
UNIT_MAPPING: Final = {
    "unit_%": "%",
    "unit_A": "A",
    "unit_bar": "bar",
    "unit_C": "°C",
    "unit_cm": "cm",
    "unit_days": "d",
    "unit_dB": "dB",
    "unit_dbm": "dBm",
    "unit_deg": "°",
    "unit_ds": "1/10 s",
    "unit_energy": "kWh",
    "unit_hours": "h",
    "unit_hpa": "hPa",
    "unit_Hz": "Hz",
    "unit_kb": "kB",
    "unit_kPa": "kPa",
    "unit_kW": "kW",
    "unit_l": "L",
    "unit_lel": "LEL %",
    "unit_liter_in_minute": "L/min",
    "unit_lux": "lx",
    "unit_m": "m",
    "unit_m_s": "m/s",
    "unit_mA": "mA",
    "unit_mgm3": "mg/m³",
    "unit_min": "min",
    "unit_mm": "mm",
    "unit_mmhg": "mmHg",
    "unit_ms": "ms",
    "unit_mV": "mV",
    "unit_power": "W",
    "unit_ppb": "ppb",
    "unit_ppm": "ppm",
    "unit_psi": "psi",
    "unit_s": "s",
    "unit_ug_m3": "µg/m³",
    "unit_um": "µm",
    "unit_uS_cm": "µS/cm",
    "unit_VAr": "var",
    "unit_voc": "VOC",
    "unit_voltage": "V",
    # Legacy aliases: keys dropped from the app dictionary by the
    # duplicate-long-forms cleanup (zigbee-remote-app 470e03c0). Hubs keep
    # sending them until their bundled drivers are updated, so map them to
    # the same values as their canonical replacements. Safe to remove once
    # deployed hubs no longer ship pre-cleanup drivers.
    "unit_seconds": "s",
    "unit_minutes": "min",
    "unit_hour": "h",
    "unit_h": "h",
    "unit_degrees": "°",
    "unit_meter": "m",
    "unit_meters": "m",
    "unit_liter": "L",
    "unit_watt": "W",
    "unit_kpa": "kPa",
    "unit_us_cm": "µS/cm",
    "unit_ugm3": "µg/m³",
    "unit_db_m": "dBm",
    "kW": "kW",  # one pre-cleanup driver shipped the unit without the unit_ prefix
}

# Sensor device class mappings: param name -> SensorDeviceClass
SENSOR_DEVICE_CLASS_MAPPING: Final = {
    "temperature": "temperature",
    "temp": "temperature",
    "humidity": "humidity",
    "hum": "humidity",
    "pressure": "pressure",
    "battery": "battery",
    "battery percent": "battery",
    "battery_percent": "battery",
    "voltage": "voltage",
    "current": "current",
    "power": "power",
    "energy": "energy",
    "illuminance": "illuminance",
    "lux": "illuminance",
    "co2": "carbon_dioxide",
    "pm25": "pm25",
    "pm10": "pm10",
    "voc": "volatile_organic_compounds",
    "frequency": "frequency",
    "signal_strength": "signal_strength",
    "distance": "distance",
}

# Device classes that are cumulative counters. HA requires state_class
# "total_increasing" for them: "measurement" would demand a last_reset
# attribute and breaks long-term statistics / the Energy dashboard.
TOTAL_INCREASING_DEVICE_CLASSES: Final = {"energy"}

# Raw adapter units HA accepts for each sensor device class. An MQTT
# discovery config whose unit_of_measurement is invalid for its device_class
# is rejected wholesale (the entity is never created), so a class is only
# published when a unit is present AND fits. Every class used in the mapping
# above must have an entry here, every unit must exist in UNIT_MAPPING
# (legacy aliases included — hubs with pre-cleanup drivers still send them),
# and every pair must be valid on the OLDEST supported HA core (hacs.json
# "homeassistant", currently 2024.1.0) — newer cores only ever widen these
# sets. Params whose unit fits no class here still get a state_class via
# UNIT_MAPPING, just no device_class.
SENSOR_DEVICE_CLASS_UNITS: Final = {
    "temperature": {"unit_C"},
    "humidity": {"unit_%"},
    "pressure": {"unit_hpa", "unit_kPa", "unit_kpa", "unit_bar", "unit_mmhg", "unit_psi"},
    "battery": {"unit_%"},
    "voltage": {"unit_voltage", "unit_mV"},
    "current": {"unit_A", "unit_mA"},
    "power": {"unit_power", "unit_watt", "unit_kW", "kW"},
    "energy": {"unit_energy"},
    "illuminance": {"unit_lux"},
    "carbon_dioxide": {"unit_ppm"},
    "pm25": {"unit_ug_m3", "unit_ugm3"},
    "pm10": {"unit_ug_m3", "unit_ugm3"},
    "volatile_organic_compounds": {"unit_ug_m3", "unit_ugm3"},
    "frequency": {"unit_Hz"},
    "signal_strength": {"unit_dB", "unit_dbm", "unit_db_m"},
    "distance": {"unit_mm", "unit_cm", "unit_m", "unit_meter", "unit_meters"},
}


def resolve_sensor_classes(
    name: str | None, raw_unit: str | None
) -> tuple[str | None, str | None]:
    """Resolve the (device_class, state_class) pair for a numeric sensor param.

    device_class is only ever returned together with a unit HA accepts for
    it: every mapped class is unit-requiring, so a param without a unit — or
    with one HA rejects for that class (a "battery" param carrying mV) —
    gets no class at all. Better no device_class than a rejected MQTT config
    or a unit-mismatch warning. The one remap: "battery" in volt units
    becomes the voltage class.

    state_class is granted only to real measurements — a resolved device
    class or at least a unit known to UNIT_MAPPING. Unclassified numbers
    with no recognized unit (ids, codes, raw counters) must not grow HA
    long-term statistics; an unmapped unit is published raw, and statistics
    recorded under it would break the day the unit gets mapped. Cumulative
    counters get "total_increasing": "measurement" would demand a last_reset
    attribute and breaks statistics. Cumulativeness follows the resolved
    device class when there is one and falls back to the name-based class
    otherwise, so a counter stays cumulative even when its unit is wrong
    for the class.
    """
    named_class = SENSOR_DEVICE_CLASS_MAPPING.get(name.lower()) if name else None

    device_class = None
    if named_class and raw_unit:
        # Fail closed: a class with no SENSOR_DEVICE_CLASS_UNITS entry gets
        # no class at all — skipping the unit guard would let an invalid
        # class/unit pair through and HA would reject the whole MQTT
        # discovery config.
        if raw_unit in SENSOR_DEVICE_CLASS_UNITS.get(named_class, ()):
            device_class = named_class
        elif (
            named_class == "battery"
            and raw_unit in SENSOR_DEVICE_CLASS_UNITS.get("voltage", ())
        ):
            device_class = "voltage"

    state_class = None
    if device_class or (raw_unit and raw_unit in UNIT_MAPPING):
        effective_class = device_class or named_class
        state_class = (
            "total_increasing"
            if effective_class in TOTAL_INCREASING_DEVICE_CLASSES
            else "measurement"
        )

    return device_class, state_class


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
