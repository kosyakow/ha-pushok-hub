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

from .const import DOMAIN, DATA_TYPE_FLOAT
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

    @property
    def native_value(self):
        """Return the sensor value."""
        return self._state_value


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
