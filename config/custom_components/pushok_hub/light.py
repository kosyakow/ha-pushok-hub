"""Light platform for Pushok Hub integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
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


def _find_light_fields(coordinator: PushokHubCoordinator, device_id: str) -> dict | None:
    """Find light-related fields from adapter.

    Returns dict with field IDs for on_off, brightness, color_temp if found.
    """
    adapter = coordinator.get_adapter_for_device(device_id)
    if not adapter:
        return None

    # Check if device type is light-related
    device_type = (adapter.device_type or "").lower()
    if not any(t in device_type for t in ["light", "dimmer", "bulb", "led"]):
        return None

    fields = {
        "on_off": None,
        "brightness": None,
        "color_temp": None,
    }

    for param in adapter.params:
        name = (param.name or "").lower()

        # Find on/off field
        if name in ("state", "on", "switch") and param.param_type == "bool":
            fields["on_off"] = param.address

        # Find brightness field
        if name in ("brightness", "level", "dim") and param.param_type in ("int", "float"):
            fields["brightness"] = param.address

        # Find color temperature field
        if name in ("color_temp", "colortemp", "color_temperature") and param.param_type in ("int", "float"):
            fields["color_temp"] = param.address

    # Must have at least on/off to be a light
    if fields["on_off"] is None:
        return None

    return fields


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
        light_fields = _find_light_fields(coordinator, device_id)
        if light_fields:
            entities.append(
                PushokHubLight(
                    coordinator,
                    device,
                    on_off_field=light_fields["on_off"],
                    brightness_field=light_fields["brightness"],
                    color_temp_field=light_fields["color_temp"],
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
        color_temp_field: int | None = None,
    ) -> None:
        """Initialize the light.

        Args:
            coordinator: Data coordinator
            device: Device description
            on_off_field: Field ID for on/off state
            brightness_field: Field ID for brightness (optional)
            color_temp_field: Field ID for color temperature (optional)
        """
        super().__init__(coordinator, device, on_off_field, name_suffix="Light")

        self._on_off_field = on_off_field
        self._brightness_field = brightness_field
        self._color_temp_field = color_temp_field

        # Store adapter params for brightness and color temp
        adapter = coordinator.get_adapter_for_device(device.id)
        self._brightness_param = None
        self._color_temp_param = None

        if adapter:
            if brightness_field is not None:
                self._brightness_param = adapter.get_param_by_address(brightness_field)
            if color_temp_field is not None:
                self._color_temp_param = adapter.get_param_by_address(color_temp_field)

        # Determine color modes
        if color_temp_field is not None:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            # Set min/max color temp if available
            if self._color_temp_param:
                if self._color_temp_param.min_value:
                    self._attr_min_mireds = int(self._color_temp_param.min_value)
                if self._color_temp_param.max_value:
                    self._attr_max_mireds = int(self._color_temp_param.max_value)
        elif brightness_field is not None:
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
        """Return the brightness of the light (0-255)."""
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

        value = prop.value

        # Apply conversion if available
        if self._brightness_param and self._brightness_param.convert:
            conversion = self._brightness_param.convert.get("conversion")
            if conversion:
                value = self._apply_conversion(value, conversion)

        # Convert to 0-255 range
        # Assume value is in 0-100 range after conversion
        return int(value * 255 / 100)

    @property
    def color_temp(self) -> int | None:
        """Return the color temperature in mireds."""
        if self._color_temp_field is None:
            return None

        if not self.coordinator.data:
            return None

        state = self.coordinator.data.get(self._device.id)
        if not state:
            return None

        prop = state.properties.get(self._color_temp_field)
        if not prop:
            return None

        value = prop.value

        # Apply conversion if available
        if self._color_temp_param and self._color_temp_param.convert:
            conversion = self._color_temp_param.convert.get("conversion")
            if conversion:
                value = self._apply_conversion(value, conversion)

        return int(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        # Handle color temperature
        if ATTR_COLOR_TEMP in kwargs and self._color_temp_field is not None:
            color_temp = kwargs[ATTR_COLOR_TEMP]

            # Apply inversion if available
            if self._color_temp_param and self._color_temp_param.convert:
                inversion = self._color_temp_param.convert.get("inversion")
                if inversion:
                    color_temp = self._apply_conversion(color_temp, inversion)

            await self.coordinator.async_set_device_state(
                self._device.id,
                self._color_temp_field,
                int(color_temp),
            )

        # Handle brightness
        if ATTR_BRIGHTNESS in kwargs and self._brightness_field is not None:
            # Convert 0-255 to 0-100
            brightness = int(kwargs[ATTR_BRIGHTNESS] * 100 / 255)

            # Apply inversion if available
            if self._brightness_param and self._brightness_param.convert:
                inversion = self._brightness_param.convert.get("inversion")
                if inversion:
                    brightness = self._apply_conversion(brightness, inversion)

            await self.coordinator.async_set_device_state(
                self._device.id,
                self._brightness_field,
                int(brightness),
            )

        # Turn on
        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_set_value(False)
