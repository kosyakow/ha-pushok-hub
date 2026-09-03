"""Sensor platform for Pushok Hub integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MAX_FIELD_ID,
    resolve_sensor_classes,
)
from .coordinator import PushokHubCoordinator
from .entity import PushokHubEntity

_LOGGER = logging.getLogger(__name__)


def _build_entities_for_device(
    coordinator: PushokHubCoordinator, device
) -> list:
    """Build sensor entities for a single device."""
    entities: list = []

    adapter = coordinator.get_adapter_for_device(device.id)
    if adapter and adapter.params:
        for param in adapter.params:
            if not device.is_automation and param.address > MAX_FIELD_ID:
                continue
            if param.param_type in ("int", "float") and not param.is_writable:
                entities.append(PushokHubSensor(coordinator, device, param.address))
    elif not device.is_automation:
        # format only exists for zigbee — automations always come with an adapter
        fmt = coordinator.formats.get(device.id)
        if fmt:
            for field_id, field_fmt in fmt.fields.items():
                if field_id > MAX_FIELD_ID:
                    continue
                if field_fmt.is_numeric and field_fmt.is_read_only:
                    entities.append(PushokHubSensor(coordinator, device, field_id))

    # LQI is a radio-link concept — only applies to zigbee devices.
    if not device.is_automation:
        entities.append(PushokHubLQISensor(coordinator, device))
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub sensors."""
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list = []
    for device in coordinator.devices.values():
        entities.extend(_build_entities_for_device(coordinator, device))
    async_add_entities(entities)

    coordinator.register_platform_builder(_build_entities_for_device, async_add_entities)


class PushokHubSensor(PushokHubEntity, SensorEntity):
    """Sensor entity for Pushok Hub."""

    def __init__(self, coordinator, device, field_id) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, field_id)

        # Build value to label mapping if labels exist
        self._value_to_label: dict[int | bool, str] = {}
        if self._adapter_param and self._adapter_param.labels:
            for label, value in self._adapter_param.labels.items():
                self._value_to_label[value] = label

        unit = self._get_ha_unit()

        # Pure enum params vs numeric measurements that merely have named
        # threshold markers in `labels` — see AdapterParam.is_enum_like.
        self._is_enum = bool(self._adapter_param and self._adapter_param.is_enum_like)

        if self._is_enum:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = sorted(set(self._value_to_label.values()))
        else:
            raw_unit = (
                self._adapter_param.view_params.get("unit")
                if self._adapter_param else None
            )
            param_name = self._adapter_param.name if self._adapter_param else None
            device_class_str, state_class_str = resolve_sensor_classes(
                param_name, raw_unit
            )
            if device_class_str:
                try:
                    self._attr_device_class = SensorDeviceClass(device_class_str)
                except ValueError:
                    # Older HA cores may lack a class from the mapping table.
                    pass
            if state_class_str:
                self._attr_state_class = SensorStateClass(state_class_str)

            if unit:
                self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self):
        """Return the sensor value."""
        if self._is_enum:
            raw_value = self._raw_state_value
            if raw_value in self._value_to_label:
                return self._value_to_label[raw_value]
            return None

        value = self._state_value
        if isinstance(value, float):
            return round(value, 2)
        return value


class PushokHubLQISensor(PushokHubEntity, SensorEntity):
    """LQI (Link Quality Indicator) sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator: PushokHubCoordinator, device) -> None:
        """Initialize the LQI sensor."""
        super().__init__(coordinator, device, field_id=-1, name_suffix="Link Quality")
        self._attr_unique_id = f"{DOMAIN}_{device.id}_lqi"

    @property
    def native_value(self):
        """Return the LQI value."""
        return self._device.lqi

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "last_seen": self._device.last_seen,
            "network_id": self._device.network_id,
        }
