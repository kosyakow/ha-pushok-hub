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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub numbers.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list[PushokHubNumber] = []

    for device_id, device in coordinator.devices.items():
        adapter = coordinator.get_adapter_for_device(device_id)
        if adapter and adapter.params:
            for param in adapter.params:
                # Skip service fields (ID > MAX_FIELD_ID)
                if param.address > MAX_FIELD_ID:
                    continue
                # Create number for numeric read-write params with slider viewType
                if param.param_type in ("int", "float") and param.is_writable:
                    view_type = param.view_params.get("type", "")
                    # Only create number for slider type, skip values used for lights
                    if view_type == "slider":
                        entities.append(
                            PushokHubNumber(coordinator, device, param.address)
                        )
        else:
            # Fallback to format if no adapter
            fmt = coordinator.formats.get(device_id)
            if fmt:
                for field_id, field_fmt in fmt.fields.items():
                    # Skip service fields (ID > MAX_FIELD_ID)
                    if field_id > MAX_FIELD_ID:
                        continue
                    if field_fmt.is_numeric and not field_fmt.is_read_only:
                        entities.append(
                            PushokHubNumber(coordinator, device, field_id)
                        )

    async_add_entities(entities)


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
