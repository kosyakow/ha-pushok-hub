"""Config flow for Pushok Hub integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)

from .api import PushokHubClient, PushokAuth
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_USE_SSL,
    CONF_REMOTE_MODE,
    CONF_HUB_ID,
    DEFAULT_PORT,
    DEFAULT_USE_SSL,
    REMOTE_GATEWAY_HOST,
    REMOTE_GATEWAY_PORT,
    STORAGE_KEY_PRIVATE_KEY,
    STORAGE_KEY_USER_ID,
)

_LOGGER = logging.getLogger(__name__)

STEP_LOCAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USE_SSL, default=DEFAULT_USE_SSL): bool,
        vol.Optional(CONF_NAME): str,
    }
)

STEP_REMOTE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HUB_ID): str,
        vol.Optional(CONF_NAME): str,
    }
)


def _build_remote_path(hub_id: str) -> str:
    """Build WebSocket path for remote connection."""
    return f"/{hub_id}/client"


class PushokHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pushok Hub."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._reconfig_entry_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - local connection only."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            use_ssl = user_input.get(CONF_USE_SSL, DEFAULT_USE_SSL)

            # Check for duplicate entries
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            # Test connection
            auth = PushokAuth()
            client = PushokHubClient(
                host=host,
                port=port,
                use_ssl=use_ssl,
                auth=auth,
            )

            try:
                await client.connect()
                await client.disconnect()

                # Create entry with auth keys
                name = user_input.get(CONF_NAME) or f"Pushok Hub ({host})"

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_USE_SSL: use_ssl,
                        CONF_REMOTE_MODE: False,
                        STORAGE_KEY_PRIVATE_KEY: auth.private_key_hex,
                        STORAGE_KEY_USER_ID: auth.user_id_b64,
                    },
                )

            except Exception as e:
                _LOGGER.error("Failed to connect to hub: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_LOCAL_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle remote connection setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            hub_id = user_input[CONF_HUB_ID]
            path = _build_remote_path(hub_id)

            # Check for duplicate entries
            await self.async_set_unique_id(f"remote:{hub_id}")
            self._abort_if_unique_id_configured()

            # Test connection
            auth = PushokAuth()
            client = PushokHubClient(
                host=REMOTE_GATEWAY_HOST,
                port=REMOTE_GATEWAY_PORT,
                use_ssl=True,
                path=path,
                auth=auth,
            )

            try:
                await client.connect()
                await client.disconnect()

                # Create entry with auth keys
                name = user_input.get(CONF_NAME) or f"Pushok Hub (Remote)"

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: REMOTE_GATEWAY_HOST,
                        CONF_PORT: REMOTE_GATEWAY_PORT,
                        CONF_USE_SSL: True,
                        CONF_REMOTE_MODE: True,
                        CONF_HUB_ID: hub_id,
                        STORAGE_KEY_PRIVATE_KEY: auth.private_key_hex,
                        STORAGE_KEY_USER_ID: auth.user_id_b64,
                    },
                )

            except Exception as e:
                _LOGGER.error("Failed to connect to hub via remote gateway: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="remote",
            data_schema=STEP_REMOTE_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration - choose connection type."""
        entry = self._get_reconfigure_entry()
        self._reconfig_entry_id = entry.entry_id
        current_remote = entry.data.get(CONF_REMOTE_MODE, False)

        if user_input is not None:
            if user_input.get("connection_type") == "remote":
                return await self.async_step_reconfigure_remote()
            return await self.async_step_reconfigure_local()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "connection_type",
                        default="remote" if current_remote else "local",
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="local", label="Local (direct IP)"),
                                SelectOptionDict(value="remote", label="Remote (via cloud)"),
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    def _get_entry(self) -> ConfigEntry:
        """Get the config entry for reconfiguration."""
        # Try to get entry from stored ID first
        if self._reconfig_entry_id:
            entry = self.hass.config_entries.async_get_entry(self._reconfig_entry_id)
            if entry:
                return entry
        # Fallback to standard method
        return self._get_reconfigure_entry()

    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle local reconfiguration."""
        errors: dict[str, str] = {}
        try:
            entry = self._get_entry()
            _LOGGER.debug("Reconfigure local: got entry %s", entry.entry_id)
        except Exception as e:
            _LOGGER.error("Failed to get entry for reconfigure: %s", e)
            return self.async_abort(reason="unknown")

        # Get current values (if was local mode)
        current_host = entry.data.get(CONF_HOST, "")
        current_port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        current_ssl = entry.data.get(CONF_USE_SSL, DEFAULT_USE_SSL)

        # If was remote mode, reset to defaults
        if entry.data.get(CONF_REMOTE_MODE, False):
            current_host = ""
            current_port = DEFAULT_PORT
            current_ssl = DEFAULT_USE_SSL

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            use_ssl = user_input.get(CONF_USE_SSL, DEFAULT_USE_SSL)

            # Test connection with existing auth keys
            auth = PushokAuth(
                private_key_hex=entry.data[STORAGE_KEY_PRIVATE_KEY],
                user_id=entry.data[STORAGE_KEY_USER_ID],
            )
            client = PushokHubClient(
                host=host,
                port=port,
                use_ssl=use_ssl,
                auth=auth,
            )

            try:
                await client.connect()
                await client.disconnect()

                # Update entry
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_USE_SSL: use_ssl,
                        CONF_REMOTE_MODE: False,
                        STORAGE_KEY_PRIVATE_KEY: entry.data[STORAGE_KEY_PRIVATE_KEY],
                        STORAGE_KEY_USER_ID: entry.data[STORAGE_KEY_USER_ID],
                    },
                )

            except Exception as e:
                _LOGGER.error("Failed to connect to hub: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure_local",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=current_host): str,
                    vol.Optional(CONF_PORT, default=current_port): int,
                    vol.Optional(CONF_USE_SSL, default=current_ssl): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle remote reconfiguration."""
        errors: dict[str, str] = {}
        try:
            entry = self._get_entry()
            _LOGGER.debug("Reconfigure remote: got entry %s", entry.entry_id)
        except Exception as e:
            _LOGGER.error("Failed to get entry for reconfigure: %s", e)
            return self.async_abort(reason="unknown")

        # Get current hub_id if was remote mode
        current_hub_id = entry.data.get(CONF_HUB_ID, "")

        if user_input is not None:
            hub_id = user_input[CONF_HUB_ID]
            path = _build_remote_path(hub_id)

            # Test connection with existing auth keys
            auth = PushokAuth(
                private_key_hex=entry.data[STORAGE_KEY_PRIVATE_KEY],
                user_id=entry.data[STORAGE_KEY_USER_ID],
            )
            client = PushokHubClient(
                host=REMOTE_GATEWAY_HOST,
                port=REMOTE_GATEWAY_PORT,
                use_ssl=True,
                path=path,
                auth=auth,
            )

            try:
                await client.connect()
                await client.disconnect()

                # Update entry
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_HOST: REMOTE_GATEWAY_HOST,
                        CONF_PORT: REMOTE_GATEWAY_PORT,
                        CONF_USE_SSL: True,
                        CONF_REMOTE_MODE: True,
                        CONF_HUB_ID: hub_id,
                        STORAGE_KEY_PRIVATE_KEY: entry.data[STORAGE_KEY_PRIVATE_KEY],
                        STORAGE_KEY_USER_ID: entry.data[STORAGE_KEY_USER_ID],
                    },
                )

            except Exception as e:
                _LOGGER.error("Failed to connect to hub via remote gateway: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure_remote",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HUB_ID, default=current_hub_id): str,
                }
            ),
            errors=errors,
        )
