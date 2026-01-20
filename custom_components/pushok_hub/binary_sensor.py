"""Binary sensor platform for Pushok Hub integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, BINARY_SENSOR_DEVICE_CLASS_MAPPING
from .coordinator import PushokHubCoordinator
from .entity import PushokHubEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub binary sensors.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list[PushokHubBinarySensor] = []

    for device_id, device in coordinator.devices.items():
        # First try to use adapter params (more complete info)
        adapter = coordinator.get_adapter_for_device(device_id)
        if adapter and adapter.params:
            for param in adapter.params:
                # Create binary sensor for boolean read-only params
                if param.param_type == "bool" and not param.is_writable:
                    entities.append(
                        PushokHubBinarySensor(coordinator, device, param.address)
                    )
        else:
            # Fallback to format if no adapter
            fmt = coordinator.formats.get(device_id)
            if fmt:
                for field_id, field_fmt in fmt.fields.items():
                    if field_fmt.is_bool and field_fmt.is_read_only:
                        entities.append(
                            PushokHubBinarySensor(coordinator, device, field_id)
                        )

    async_add_entities(entities)


class PushokHubBinarySensor(PushokHubEntity, BinarySensorEntity):
    """Binary sensor entity for Pushok Hub."""

    def __init__(self, coordinator, device, field_id) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device, field_id)

        # Set device class based on param name
        if self._adapter_param and self._adapter_param.name:
            param_name = self._adapter_param.name.lower()
            device_class_str = BINARY_SENSOR_DEVICE_CLASS_MAPPING.get(param_name)
            if device_class_str:
                try:
                    self._attr_device_class = BinarySensorDeviceClass(device_class_str)
                except ValueError:
                    pass

        # Set icon based on device class or param name
        if not hasattr(self, "_attr_device_class") or self._attr_device_class is None:
            if self._adapter_param and self._adapter_param.name:
                name = self._adapter_param.name.lower()
                if "motion" in name or "presence" in name:
                    self._attr_icon = "mdi:motion-sensor"
                elif "door" in name or "window" in name or "contact" in name:
                    self._attr_icon = "mdi:door"
                elif "smoke" in name:
                    self._attr_icon = "mdi:smoke-detector"
                elif "water" in name or "leak" in name:
                    self._attr_icon = "mdi:water-alert"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        value = self._state_value
        if value is None:
            return None
        return bool(value)
