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

from .const import DOMAIN, SENSOR_DEVICE_CLASS_MAPPING
from .coordinator import PushokHubCoordinator
from .entity import PushokHubEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub sensors.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list[PushokHubSensor] = []

    for device_id, device in coordinator.devices.items():
        fmt = coordinator.formats.get(device_id)
        if not fmt:
            continue

        for field_id, field_fmt in fmt.fields.items():
            # Create sensor for numeric read-only fields
            if field_fmt.is_numeric and field_fmt.is_read_only:
                entities.append(
                    PushokHubSensor(coordinator, device, field_id)
                )

    # Add LQI sensor for each device
    for device_id, device in coordinator.devices.items():
        entities.append(PushokHubLQISensor(coordinator, device))

    async_add_entities(entities)


class PushokHubSensor(PushokHubEntity, SensorEntity):
    """Sensor entity for Pushok Hub."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device, field_id) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, field_id)

        # Set device class based on param name
        if self._adapter_param and self._adapter_param.name:
            param_name = self._adapter_param.name.lower()
            device_class_str = SENSOR_DEVICE_CLASS_MAPPING.get(param_name)
            if device_class_str:
                try:
                    self._attr_device_class = SensorDeviceClass(device_class_str)
                except ValueError:
                    pass

        # Set unit from adapter
        unit = self._get_ha_unit()
        if unit:
            self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self):
        """Return the sensor value."""
        value = self._state_value
        # Round float values for display
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
