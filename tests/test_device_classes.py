#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consistency tests for the sensor device class tables and helpers.

Usage:
    python3 tests/test_device_classes.py   # standalone, no dependencies
    pytest tests/                          # also works

The HA_* snapshots below are taken from Home Assistant 2026.1.2
(homeassistant.components.sensor: SensorDeviceClass, DEVICE_CLASS_UNITS).
Refresh them when targeting a newer HA release.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.pushok_hub.api.models import AdapterParam
from custom_components.pushok_hub.const import (
    SENSOR_DEVICE_CLASS_MAPPING,
    SENSOR_DEVICE_CLASS_UNITS,
    TOTAL_INCREASING_DEVICE_CLASSES,
    UNIT_MAPPING,
    resolve_sensor_device_class,
)

# Valid SensorDeviceClass values. An invalid value in an MQTT discovery
# payload makes HA reject the whole config — the entity is never created
# (this is how "co2" instead of "carbon_dioxide" broke CO2 sensors).
HA_SENSOR_DEVICE_CLASSES = {
    "absolute_humidity", "apparent_power", "aqi", "area",
    "atmospheric_pressure", "battery", "blood_glucose_concentration",
    "carbon_dioxide", "carbon_monoxide", "conductivity", "current",
    "data_rate", "data_size", "date", "distance", "duration", "energy",
    "energy_distance", "energy_storage", "enum", "frequency", "gas",
    "humidity", "illuminance", "irradiance", "moisture", "monetary",
    "nitrogen_dioxide", "nitrogen_monoxide", "nitrous_oxide", "ozone", "ph",
    "pm1", "pm10", "pm25", "pm4", "power", "power_factor", "precipitation",
    "precipitation_intensity", "pressure", "reactive_energy",
    "reactive_power", "signal_strength", "sound_pressure", "speed",
    "sulphur_dioxide", "temperature", "temperature_delta", "timestamp",
    "volatile_organic_compounds", "volatile_organic_compounds_parts",
    "voltage", "volume", "volume_flow_rate", "volume_storage", "water",
    "weight", "wind_direction", "wind_speed",
}

# Units HA accepts per device class (only the classes this project maps).
# HA spells micro with GREEK SMALL LETTER MU (U+03BC); UNIT_MAPPING uses
# MICRO SIGN (U+00B5), which HA normalizes via AMBIGUOUS_UNITS before
# validating — _ha_normalize() mirrors that.
HA_DEVICE_CLASS_UNITS = {
    "temperature": {"K", "°C", "°F"},
    "humidity": {"%"},
    "pressure": {"Pa", "bar", "cbar", "hPa", "inHg", "inH₂O", "kPa", "mPa",
                 "mbar", "mmHg", "psi"},
    "battery": {"%"},
    "voltage": {"MV", "V", "kV", "mV", "μV"},
    "current": {"A", "mA"},
    "power": {"GW", "MW", "TW", "W", "kW", "mW"},
    "energy": {"GJ", "GWh", "Gcal", "J", "MJ", "MWh", "Mcal", "TWh", "Wh",
               "cal", "kJ", "kWh", "kcal", "mWh"},
    "illuminance": {"lx"},
    "carbon_dioxide": {"ppm"},
    "pm25": {"μg/m³"},
    "pm10": {"μg/m³"},
    "volatile_organic_compounds": {"mg/m³", "μg/m³"},
    "frequency": {"GHz", "Hz", "MHz", "kHz"},
    "signal_strength": {"dB", "dBm"},
    "distance": {"cm", "ft", "in", "km", "m", "mi", "mm", "nmi", "yd"},
}


def _ha_normalize(unit: str) -> str:
    """Mirror HA's AMBIGUOUS_UNITS micro-sign normalization."""
    return unit.replace("µ", "μ")


def _param(**kwargs) -> AdapterParam:
    kwargs.setdefault("address", 1)
    kwargs.setdefault("access", "r")
    kwargs.setdefault("param_type", "int")
    return AdapterParam(**kwargs)


def test_mapping_values_are_valid_device_classes():
    for name, device_class in SENSOR_DEVICE_CLASS_MAPPING.items():
        assert device_class in HA_SENSOR_DEVICE_CLASSES, (
            f"SENSOR_DEVICE_CLASS_MAPPING[{name!r}] = {device_class!r} is not "
            f"a valid HA SensorDeviceClass value; HA rejects the whole MQTT "
            f"discovery config for it"
        )


def test_guard_units_exist_in_unit_mapping():
    for device_class, raw_units in SENSOR_DEVICE_CLASS_UNITS.items():
        for raw_unit in raw_units:
            assert raw_unit in UNIT_MAPPING, (
                f"SENSOR_DEVICE_CLASS_UNITS[{device_class!r}] lists "
                f"{raw_unit!r} which UNIT_MAPPING cannot translate; the raw "
                f"string would be published as unit_of_measurement and HA "
                f"would reject the config (this is how 'unit_V' broke "
                f"voltage sensors)"
            )


def test_every_mapped_class_has_a_units_entry():
    # A class absent from SENSOR_DEVICE_CLASS_UNITS accepts any unit
    # (fail-open), silently disabling the guard this table exists for.
    for name, device_class in SENSOR_DEVICE_CLASS_MAPPING.items():
        assert device_class in SENSOR_DEVICE_CLASS_UNITS, (
            f"device class {device_class!r} (from param name {name!r}) has "
            f"no SENSOR_DEVICE_CLASS_UNITS entry"
        )


def test_allowed_pairs_pass_ha_validation():
    for device_class, raw_units in SENSOR_DEVICE_CLASS_UNITS.items():
        ha_units = HA_DEVICE_CLASS_UNITS.get(device_class)
        assert ha_units is not None, (
            f"no HA units snapshot for {device_class!r} — add it from "
            f"homeassistant.components.sensor.DEVICE_CLASS_UNITS"
        )
        for raw_unit in raw_units:
            mapped = _ha_normalize(UNIT_MAPPING.get(raw_unit, raw_unit))
            assert mapped in ha_units, (
                f"{raw_unit!r} maps to {mapped!r} which HA does not accept "
                f"for device class {device_class!r}"
            )


def test_total_increasing_classes_are_valid():
    assert TOTAL_INCREASING_DEVICE_CLASSES <= HA_SENSOR_DEVICE_CLASSES


def test_resolve_basic_mapping():
    assert resolve_sensor_device_class("temperature", "unit_C") == "temperature"
    assert resolve_sensor_device_class("Temperature", "unit_F") == "temperature"
    assert resolve_sensor_device_class(None, "unit_C") is None
    assert resolve_sensor_device_class("no_such_param", "unit_C") is None


def test_resolve_keeps_class_without_unit():
    assert resolve_sensor_device_class("energy", None) == "energy"


def test_resolve_co2_is_carbon_dioxide():
    # Regression: "co2" is not a valid SensorDeviceClass value.
    assert resolve_sensor_device_class("co2", "unit_ppm") == "carbon_dioxide"


def test_resolve_drops_class_on_unit_mismatch():
    assert resolve_sensor_device_class("pressure", "unit_mPa") is None
    assert resolve_sensor_device_class("battery", "unit_s") is None
    # unit_V is not a real hub unit (absent from UNIT_MAPPING) and must not
    # be treated as a voltage spelling.
    assert resolve_sensor_device_class("voltage", "unit_V") is None


def test_resolve_battery_voltage_remap():
    assert resolve_sensor_device_class("battery", "unit_%") == "battery"
    assert resolve_sensor_device_class("battery", "unit_mV") == "voltage"
    assert resolve_sensor_device_class("battery", "unit_voltage") == "voltage"
    assert resolve_sensor_device_class("battery", "unit_kV") == "voltage"


def test_is_enum_like():
    assert _param(labels={"off": 0, "on": 1}).is_enum_like
    # Float params and params with a unit are numeric measurements whose
    # labels are only threshold markers.
    assert not _param(labels={"low": 10}, param_type="float").is_enum_like
    assert not _param(
        labels={"low": 10}, view_params={"unit": "unit_%"}
    ).is_enum_like
    assert not _param().is_enum_like


if __name__ == "__main__":
    failed = 0
    for test_name, test_fn in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test_fn):
            try:
                test_fn()
                print(f"PASS {test_name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {test_name}: {exc}")
    sys.exit(1 if failed else 0)
