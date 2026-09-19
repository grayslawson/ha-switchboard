"""Minimal config flow; secrets remain in Home Assistant config-entry storage."""

from __future__ import annotations

from typing import Any

from .const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, DEFAULT_GATEWAY_URL, DOMAIN

try:  # pragma: no cover - exercised in the Home Assistant devcontainer
    import voluptuous as vol
    from homeassistant import config_entries
    from homeassistant.const import CONF_URL

    class JevConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
        VERSION = 1

        async def async_step_user(self, user_input: dict[str, Any] | None = None):
            errors: dict[str, str] = {}
            if user_input is not None:
                return self.async_create_entry(title="HA Switchboard", data=user_input)
            schema = vol.Schema(
                {
                    vol.Required(CONF_GATEWAY_URL, default=DEFAULT_GATEWAY_URL): str,
                    vol.Optional(CONF_GATEWAY_TOKEN, default=""): str,
                }
            )
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

except ImportError:

    class JevConfigFlow:  # type: ignore[no-redef]
        """Importable fallback for contract tests outside Home Assistant."""

        VERSION = 1

        def __init__(self, user_input: dict[str, Any] | None = None) -> None:
            self.user_input = user_input
