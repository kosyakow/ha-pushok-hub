"""Binary sensor platform for Pushok Hub integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
)
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
    """Set up Pushok Hub binary sensors.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list[PushokHubBinarySensor] = []

    for device_id, device in coordinator.devices.items():
        fmt = coordinator.formats.get(device_id)
        if not fmt:
            continue

        for field_id, field_fmt in fmt.fields.items():
            # Create binary sensor for boolean read-only fields
            if field_fmt.is_bool and field_fmt.is_read_only:
                entities.append(
                    PushokHubBinarySensor(coordinator, device, field_id)
                )

    async_add_entities(entities)


class PushokHubBinarySensor(PushokHubEntity, BinarySensorEntity):
    """Binary sensor entity for Pushok Hub."""

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        value = self._state_value
        if value is None:
            return None
        return bool(value)
