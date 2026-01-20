"""Light platform for Pushok Hub integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PushokHubCoordinator
from .entity import PushokHubEntity

_LOGGER = logging.getLogger(__name__)

# Field IDs for light devices (adjust based on your driver implementation)
FIELD_ON_OFF = 0
FIELD_BRIGHTNESS = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pushok Hub lights.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: PushokHubCoordinator = entry.runtime_data

    entities: list[PushokHubLight] = []

    for device_id, device in coordinator.devices.items():
        fmt = coordinator.formats.get(device_id)
        if not fmt:
            continue

        # Check if device has light-like fields (on/off boolean + optional brightness)
        has_on_off = FIELD_ON_OFF in fmt.fields and fmt.fields[FIELD_ON_OFF].is_bool
        has_brightness = FIELD_BRIGHTNESS in fmt.fields and fmt.fields[FIELD_BRIGHTNESS].is_numeric

        if has_on_off:
            entities.append(
                PushokHubLight(
                    coordinator,
                    device,
                    on_off_field=FIELD_ON_OFF,
                    brightness_field=FIELD_BRIGHTNESS if has_brightness else None,
                )
            )

    async_add_entities(entities)


class PushokHubLight(PushokHubEntity, LightEntity):
    """Light entity for Pushok Hub."""

    def __init__(
        self,
        coordinator: PushokHubCoordinator,
        device,
        on_off_field: int,
        brightness_field: int | None = None,
    ) -> None:
        """Initialize the light.

        Args:
            coordinator: Data coordinator
            device: Device description
            on_off_field: Field ID for on/off state
            brightness_field: Field ID for brightness (optional)
        """
        super().__init__(coordinator, device, on_off_field, name_suffix="Light")

        self._on_off_field = on_off_field
        self._brightness_field = brightness_field

        if brightness_field is not None:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        else:
            self._attr_color_mode = ColorMode.ONOFF
            self._attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool | None:
        """Return true if the light is on."""
        value = self._state_value
        if value is None:
            return None
        return bool(value)

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        if self._brightness_field is None:
            return None

        if not self.coordinator.data:
            return None

        state = self.coordinator.data.get(self._device.id)
        if not state:
            return None

        prop = state.properties.get(self._brightness_field)
        if not prop:
            return None

        # Convert 0-100 to 0-255
        return int(prop.value * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if ATTR_BRIGHTNESS in kwargs and self._brightness_field is not None:
            # Convert 0-255 to 0-100
            brightness = int(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            await self.coordinator.async_set_device_state(
                self._device.id,
                self._brightness_field,
                brightness,
            )

        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_set_value(False)
