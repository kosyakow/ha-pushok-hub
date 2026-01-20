"""Config flow for Pushok Hub integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME

from .api import PushokHubClient, PushokAuth
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_USE_SSL,
    DEFAULT_PORT,
    DEFAULT_USE_SSL,
    STORAGE_KEY_PRIVATE_KEY,
    STORAGE_KEY_USER_ID,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USE_SSL, default=DEFAULT_USE_SSL): bool,
        vol.Optional(CONF_NAME): str,
    }
)


class PushokHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pushok Hub."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        Args:
            user_input: User provided configuration

        Returns:
            Config flow result
        """
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
                        STORAGE_KEY_PRIVATE_KEY: auth.private_key_hex,
                        STORAGE_KEY_USER_ID: auth.user_id_b64,
                    },
                )

            except Exception as e:
                _LOGGER.error("Failed to connect to hub: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
