"""Switch platform for Pushok Hub integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PushokHubCoordinator
from .entity import PushokHubEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub switches.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list[PushokHubSwitch] = []

    for device_id, device in coordinator.devices.items():
        fmt = coordinator.formats.get(device_id)
        if not fmt:
            continue

        for field_id, field_fmt in fmt.fields.items():
            # Create switch for boolean read-write fields
            if field_fmt.is_bool and not field_fmt.is_read_only:
                entities.append(
                    PushokHubSwitch(coordinator, device, field_id)
                )

    async_add_entities(entities)


class PushokHubSwitch(PushokHubEntity, SwitchEntity):
    """Switch entity for Pushok Hub."""

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        value = self._state_value
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set_value(False)
