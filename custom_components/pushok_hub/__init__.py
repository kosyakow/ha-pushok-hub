"""The Pushok Hub integration."""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

# Allow importing this module without homeassistant (for standalone API use)
try:
    from typing import TypeAlias

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant

    from .const import DOMAIN
    from .coordinator import PushokHubCoordinator

    PLATFORMS: list[Platform] = [
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
        Platform.SWITCH,
        Platform.LIGHT,
        Platform.NUMBER,
        Platform.SELECT,
    ]

    PushokHubConfigEntry: TypeAlias = ConfigEntry
    _HA_AVAILABLE = True
except ImportError:
    _HA_AVAILABLE = False


if _HA_AVAILABLE:
    async def async_setup_entry(hass: HomeAssistant, entry: PushokHubConfigEntry) -> bool:
        """Set up Pushok Hub from a config entry.

        Args:
            hass: Home Assistant instance
            entry: Config entry to set up

        Returns:
            True if setup was successful
        """
        coordinator = PushokHubCoordinator(hass, entry)

        if not await coordinator.async_setup():
            _LOGGER.warning("Hub connection failed, will retry in background")

        entry.runtime_data = coordinator

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        entry.async_on_unload(coordinator.async_shutdown)

        return True

    async def async_unload_entry(hass: HomeAssistant, entry: PushokHubConfigEntry) -> bool:
        """Unload a config entry.

        Args:
            hass: Home Assistant instance
            entry: Config entry to unload

        Returns:
            True if unload was successful
        """
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
