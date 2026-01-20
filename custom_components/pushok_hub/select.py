"""Select platform for Pushok Hub integration."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
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
    """Set up Pushok Hub selects.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list[PushokHubSelect] = []

    for device_id, device in coordinator.devices.items():
        adapter = coordinator.get_adapter_for_device(device_id)
        if adapter and adapter.params:
            for param in adapter.params:
                # Skip service fields (ID > MAX_FIELD_ID)
                if param.address > MAX_FIELD_ID:
                    continue
                # Create select for params with dropdown viewType and labels
                view_type = param.view_params.get("type", "")
                if view_type == "dropdown" and param.labels and param.is_writable:
                    entities.append(
                        PushokHubSelect(coordinator, device, param.address)
                    )

    async_add_entities(entities)


class PushokHubSelect(PushokHubEntity, SelectEntity):
    """Select entity for Pushok Hub."""

    def __init__(self, coordinator, device, field_id) -> None:
        """Initialize the select."""
        super().__init__(coordinator, device, field_id)

        # Build options from labels
        self._label_to_value: dict[str, int | bool] = {}
        self._value_to_label: dict[int | bool, str] = {}

        if self._adapter_param and self._adapter_param.labels:
            for label, value in self._adapter_param.labels.items():
                self._label_to_value[label] = value
                self._value_to_label[value] = label

        self._attr_options = list(self._label_to_value.keys())

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = self._raw_state_value
        if value is None:
            return None
        return self._value_to_label.get(value)

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        value = self._label_to_value.get(option)
        if value is not None:
            await self.coordinator.async_set_device_state(
                self._device.id,
                self._field_id,
                value,
            )
