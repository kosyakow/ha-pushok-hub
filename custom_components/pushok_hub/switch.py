"""Switch platform for Pushok Hub integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_FIELD_ID, SWITCH_DEVICE_CLASS_MAPPING
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
        # First try to use adapter params (more complete info)
        adapter = coordinator.get_adapter_for_device(device_id)
        if adapter and adapter.params:
            for param in adapter.params:
                # Skip service fields (ID > MAX_FIELD_ID)
                if param.address > MAX_FIELD_ID:
                    continue
                # Create switch for boolean read-write params
                if param.param_type == "bool" and param.is_writable:
                    # Skip if this is a light device (handled by light platform)
                    device_type = (adapter.device_type or "").lower()
                    if any(t in device_type for t in ["light", "dimmer", "bulb"]):
                        continue
                    entities.append(
                        PushokHubSwitch(coordinator, device, param.address)
                    )
        else:
            # Fallback to format if no adapter
            fmt = coordinator.formats.get(device_id)
            if fmt:
                for field_id, field_fmt in fmt.fields.items():
                    # Skip service fields (ID > MAX_FIELD_ID)
                    if field_id > MAX_FIELD_ID:
                        continue
                    if field_fmt.is_bool and not field_fmt.is_read_only:
                        entities.append(
                            PushokHubSwitch(coordinator, device, field_id)
                        )

    async_add_entities(entities)


class PushokHubSwitch(PushokHubEntity, SwitchEntity):
    """Switch entity for Pushok Hub."""

    def __init__(self, coordinator, device, field_id) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device, field_id)

        # Set device class based on param name or adapter device type
        adapter = coordinator.get_adapter_for_device(device.id)
        if adapter:
            device_type = (adapter.device_type or "").lower()
            if "plug" in device_type or "socket" in device_type:
                self._attr_device_class = SwitchDeviceClass.OUTLET
            elif "switch" in device_type:
                self._attr_device_class = SwitchDeviceClass.SWITCH

        # Try to set from param name
        if not hasattr(self, "_attr_device_class") or self._attr_device_class is None:
            if self._adapter_param and self._adapter_param.name:
                param_name = self._adapter_param.name.lower()
                device_class_str = SWITCH_DEVICE_CLASS_MAPPING.get(param_name)
                if device_class_str:
                    try:
                        self._attr_device_class = SwitchDeviceClass(device_class_str)
                    except ValueError:
                        pass

        # Set icon for common switch types
        if self._adapter_param and self._adapter_param.name:
            name = self._adapter_param.name.lower()
            if "indicator" in name or "led" in name:
                self._attr_icon = "mdi:led-on"
            elif "child_lock" in name:
                self._attr_icon = "mdi:lock"
            elif "backlight" in name:
                self._attr_icon = "mdi:lightbulb"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        value = self._state_value
        _LOGGER.debug(
            "Switch %s field %d is_on check: raw=%s, converted=%s",
            self._device.id[:8],
            self._field_id,
            self._raw_state_value,
            value,
        )
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set_value(False)
