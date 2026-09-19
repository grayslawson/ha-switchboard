"""Home Assistant Core integration entrypoint."""

from __future__ import annotations

from typing import Any

from .client import GatewayClient
from .const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, DEFAULT_GATEWAY_URL
from .conversation import JevConversationEntity

CONFIG_SCHEMA = None

try:  # pragma: no cover - exercised in the Home Assistant runtime
    from homeassistant.helpers import config_validation as cv

    CONFIG_SCHEMA = cv.empty_config_schema
except ImportError:
    CONFIG_SCHEMA = None

_PLATFORMS = ["conversation"]


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    return True


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    data = dict(getattr(entry, "data", {}))
    client = GatewayClient(
        data.get(CONF_GATEWAY_URL, DEFAULT_GATEWAY_URL),
        data.get(CONF_GATEWAY_TOKEN, ""),
    )
    if hasattr(hass, "data"):
        hass.data.setdefault("ha_switchboard", {})[entry.entry_id] = client
    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_forward_entry_setups"):
        await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_unload_platforms"):
        if not await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
            return False
    if hasattr(hass, "data"):
        hass.data.get("ha_switchboard", {}).pop(entry.entry_id, None)
    return True
