#!/usr/bin/env python3
"""Consistency tests for the sensor device class tables and helpers.

Usage:
    python3 tests/test_device_classes.py   # standalone, no dependencies
    pytest tests/                          # also works

The HA_* snapshots below are taken from Home Assistant 2026.1.2
(homeassistant.components.sensor: SensorDeviceClass, DEVICE_CLASS_UNITS,
DEVICE_CLASS_STATE_CLASSES), verified against the 2026.1.2 source. When
homeassistant is importable, test_snapshots_match_installed_ha re-verifies
every snapshot against the live tables; refresh them when it fails on a
newer HA release.
"""

import sys
import unittest
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
# MICRO SIGN (U+00B5), which HA normalizes before any unit validation:
# sensor.SensorEntity.__native_unit_of_measurement_compat runs every
# sensor's unit (including MQTT-discovered ones) through AMBIGUOUS_UNITS.
# _ha_normalize() mirrors that.
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


# State classes HA allows per device class (only the classes this project
# maps). Publishing a state_class outside this set (e.g. the old
# "measurement" on an energy sensor) is invalid — HA warns and statistics
# break. From homeassistant.components.sensor.DEVICE_CLASS_STATE_CLASSES.
HA_DEVICE_CLASS_STATE_CLASSES = {
    "temperature": {"measurement"},
    "humidity": {"measurement"},
    "pressure": {"measurement"},
    "battery": {"measurement"},
    "voltage": {"measurement"},
    "current": {"measurement"},
    "power": {"measurement"},
    "energy": {"total", "total_increasing"},
    "illuminance": {"measurement"},
    "carbon_dioxide": {"measurement"},
    "pm25": {"measurement"},
    "pm10": {"measurement"},
    "volatile_organic_compounds": {"measurement"},
    "frequency": {"measurement"},
    "signal_strength": {"measurement"},
    "distance": {"measurement", "measurement_angle", "total", "total_increasing"},
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


def test_emitted_state_class_is_valid_for_every_class():
    # Regression: HA validates state_class against device_class
    # (DEVICE_CLASS_STATE_CLASSES) — "measurement" on an energy sensor is
    # exactly the invalid pair this PR started from.
    for device_class in set(SENSOR_DEVICE_CLASS_MAPPING.values()):
        emitted = (
            "total_increasing"
            if device_class in TOTAL_INCREASING_DEVICE_CLASSES
            else "measurement"
        )
        allowed = HA_DEVICE_CLASS_STATE_CLASSES.get(device_class)
        assert allowed is not None, (
            f"no HA state-class snapshot for {device_class!r} — add it from "
            f"homeassistant.components.sensor.DEVICE_CLASS_STATE_CLASSES"
        )
        assert emitted in allowed, (
            f"we would publish state_class {emitted!r} for device class "
            f"{device_class!r}, but HA only allows {sorted(allowed)}"
        )


def test_resolve_basic_mapping():
    assert resolve_sensor_device_class("temperature", "unit_C") == "temperature"
    assert resolve_sensor_device_class("Temperature", "unit_F") == "temperature"
    # HA's UnitOfPressure includes millipascal ("mPa"), so the hub's
    # unit_mPa keeps the pressure class.
    assert resolve_sensor_device_class("pressure", "unit_mPa") == "pressure"
    assert resolve_sensor_device_class(None, "unit_C") is None
    assert resolve_sensor_device_class("no_such_param", "unit_C") is None


def test_resolve_keeps_class_without_unit():
    assert resolve_sensor_device_class("energy", None) == "energy"


def test_resolve_co2_is_carbon_dioxide():
    # Regression: "co2" is not a valid SensorDeviceClass value.
    assert resolve_sensor_device_class("co2", "unit_ppm") == "carbon_dioxide"


def test_resolve_drops_class_on_unit_mismatch():
    assert resolve_sensor_device_class("pressure", "unit_mm") is None
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


def test_snapshots_match_installed_ha():
    """Verify every HA_* snapshot against an installed homeassistant.

    Skipped when homeassistant is not importable (the standalone runner and
    the bridge venv). Run inside an HA venv to validate the snapshots for
    the release actually deployed.
    """
    try:
        from homeassistant.components.sensor import (
            DEVICE_CLASS_STATE_CLASSES,
            DEVICE_CLASS_UNITS,
            SensorDeviceClass,
        )
    except ImportError as exc:
        raise unittest.SkipTest(f"homeassistant not installed ({exc})") from exc

    real_classes = {cls.value for cls in SensorDeviceClass}
    assert HA_SENSOR_DEVICE_CLASSES == real_classes, (
        f"HA_SENSOR_DEVICE_CLASSES snapshot is stale: "
        f"missing={sorted(real_classes - HA_SENSOR_DEVICE_CLASSES)} "
        f"extra={sorted(HA_SENSOR_DEVICE_CLASSES - real_classes)}"
    )

    for device_class, snapshot_units in HA_DEVICE_CLASS_UNITS.items():
        real_units = {
            str(unit)
            for unit in DEVICE_CLASS_UNITS[SensorDeviceClass(device_class)]
            if unit is not None
        }
        assert snapshot_units == real_units, (
            f"HA_DEVICE_CLASS_UNITS[{device_class!r}] snapshot is stale: "
            f"missing={sorted(real_units - snapshot_units)} "
            f"extra={sorted(snapshot_units - real_units)}"
        )

    for device_class, snapshot_states in HA_DEVICE_CLASS_STATE_CLASSES.items():
        real_states = {
            str(state_class)
            for state_class in DEVICE_CLASS_STATE_CLASSES[
                SensorDeviceClass(device_class)
            ]
        }
        assert snapshot_states == real_states, (
            f"HA_DEVICE_CLASS_STATE_CLASSES[{device_class!r}] snapshot is "
            f"stale: missing={sorted(real_states - snapshot_states)} "
            f"extra={sorted(snapshot_states - real_states)}"
        )


if __name__ == "__main__":
    failed = 0
    for test_name, test_fn in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test_fn):
            try:
                test_fn()
                print(f"PASS {test_name}")
            except unittest.SkipTest as exc:
                print(f"SKIP {test_name}: {exc}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {test_name}: {exc}")
    sys.exit(1 if failed else 0)
