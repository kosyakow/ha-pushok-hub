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

from .const import DOMAIN, BINARY_SENSOR_DEVICE_CLASS_MAPPING, MAX_FIELD_ID
from .coordinator import PushokHubCoordinator
from .entity import PushokHubEntity

_LOGGER = logging.getLogger(__name__)


def _build_entities_for_device(
    coordinator: PushokHubCoordinator, device
) -> list:
    """Build binary sensor entities for a single device."""
    entities: list = []
    adapter = coordinator.get_adapter_for_device(device.id)
    if adapter and adapter.params:
        for param in adapter.params:
            if param.address > MAX_FIELD_ID:
                continue
            if param.param_type == "bool" and not param.is_writable:
                entities.append(
                    PushokHubBinarySensor(coordinator, device, param.address)
                )
    else:
        fmt = coordinator.formats.get(device.id)
        if fmt:
            for field_id, field_fmt in fmt.fields.items():
                if field_id > MAX_FIELD_ID:
                    continue
                if field_fmt.is_bool and field_fmt.is_read_only:
                    entities.append(
                        PushokHubBinarySensor(coordinator, device, field_id)
                    )
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub binary sensors."""
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list = []
    for device in coordinator.devices.values():
        entities.extend(_build_entities_for_device(coordinator, device))
    async_add_entities(entities)

    coordinator.register_platform_builder(_build_entities_for_device, async_add_entities)


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
