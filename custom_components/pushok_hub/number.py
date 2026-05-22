"""Number platform for Pushok Hub integration."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_FIELD_ID
from .coordinator import PushokHubCoordinator
from .entity import PushokHubEntity

_LOGGER = logging.getLogger(__name__)


def _build_entities_for_device(
    coordinator: PushokHubCoordinator, device
) -> list:
    """Build number entities for a single device."""
    entities: list = []
    adapter = coordinator.get_adapter_for_device(device.id)
    if adapter and adapter.params:
        device_type = (adapter.device_type or "").lower()
        is_light_device = any(t in device_type for t in ["light", "dimmer", "bulb"])
        for param in adapter.params:
            if param.address > MAX_FIELD_ID:
                continue
            if param.param_type in ("int", "float") and param.is_writable:
                view_type = param.view_params.get("type", "")
                if view_type == "dropdown":
                    continue
                if is_light_device:
                    continue
                if view_type in ("slider", "value"):
                    entities.append(
                        PushokHubNumber(coordinator, device, param.address)
                    )
    else:
        fmt = coordinator.formats.get(device.id)
        if fmt:
            for field_id, field_fmt in fmt.fields.items():
                if field_id > MAX_FIELD_ID:
                    continue
                if field_fmt.is_numeric and not field_fmt.is_read_only:
                    entities.append(PushokHubNumber(coordinator, device, field_id))
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub numbers."""
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list = []
    for device in coordinator.devices.values():
        entities.extend(_build_entities_for_device(coordinator, device))
    async_add_entities(entities)

    coordinator.register_platform_builder(_build_entities_for_device, async_add_entities)


class PushokHubNumber(PushokHubEntity, NumberEntity):
    """Number entity for Pushok Hub."""

    def __init__(self, coordinator, device, field_id) -> None:
        """Initialize the number."""
        super().__init__(coordinator, device, field_id)

        # Set mode to slider
        self._attr_mode = NumberMode.SLIDER

        # Set min/max from adapter param
        if self._adapter_param:
            if self._adapter_param.min_value is not None:
                self._attr_native_min_value = float(self._adapter_param.min_value)
            if self._adapter_param.max_value is not None:
                self._attr_native_max_value = float(self._adapter_param.max_value)

        # Set unit from adapter
        unit = self._get_ha_unit()
        if unit:
            self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = self._state_value
        if value is None:
            return None
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        # Convert to int if the param type is int
        if self._adapter_param and self._adapter_param.param_type == "int":
            value = int(value)
        await self._async_set_value(value)
