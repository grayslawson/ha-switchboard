"""Home Assistant Core integration entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .client import GatewayClient
from .const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, DOMAIN
from .coordinator import ProfileCoordinator
from .execution import CoreHomeAssistantExecutor
from .profile_adapter import HomeAssistantProfileAdapter
from .runtime import SwitchboardRuntimeData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    SwitchboardConfigEntry = ConfigEntry[SwitchboardRuntimeData]
else:
    SwitchboardConfigEntry = Any

CONFIG_SCHEMA = None

try:  # pragma: no cover - exercised in the Home Assistant runtime
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers import config_validation as cv

    CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)
except ImportError:  # pragma: no cover - contract tests outside HA
    class ConfigEntryNotReady(RuntimeError):
        pass


_PLATFORMS = ["conversation", "sensor"]
_RUNTIME_DATA_KEY = DOMAIN


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    return True


async def _async_update_listener(hass: Any, entry: SwitchboardConfigEntry) -> None:
    """Use updated discovery credentials in a fresh client and coordinator."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: Any, entry: SwitchboardConfigEntry) -> bool:
    data = dict(getattr(entry, "data", {}))
    gateway_url = data.get(CONF_GATEWAY_URL)
    if not isinstance(gateway_url, str) or not gateway_url.strip():
        raise ConfigEntryNotReady("HA Switchboard gateway URL is not configured")

    coordinator = None
    try:
        client = GatewayClient.from_hass(hass, gateway_url, str(data.get(CONF_GATEWAY_TOKEN, "")))
        installation_key = str(getattr(entry, "unique_id", None) or entry.entry_id)
        adapter = HomeAssistantProfileAdapter(hass, installation_key)
        coordinator = ProfileCoordinator(hass, entry, client, adapter)
        executor = CoreHomeAssistantExecutor(hass, coordinator.capability_map, coordinator)
        await coordinator.async_start()
    except Exception as exc:
        if coordinator is not None:
            await coordinator.async_shutdown()
        raise ConfigEntryNotReady("HA Switchboard gateway or profile is unavailable") from exc

    runtime_data = SwitchboardRuntimeData(client=client, coordinator=coordinator, executor=executor)
    entry.runtime_data = runtime_data
    if hasattr(hass, "data"):
        hass.data.setdefault(_RUNTIME_DATA_KEY, {})[entry.entry_id] = runtime_data
    try:
        await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    except BaseException:
        await coordinator.async_shutdown()
        if hasattr(hass, "data"):
            hass.data.get(_RUNTIME_DATA_KEY, {}).pop(entry.entry_id, None)
        entry.runtime_data = None
        raise
    return True


async def async_unload_entry(hass: Any, entry: SwitchboardConfigEntry) -> bool:
    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_unload_platforms"):
        if not await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
            return False
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is not None:
        await runtime_data.coordinator.async_shutdown()
    if hasattr(hass, "data"):
        hass.data.get(_RUNTIME_DATA_KEY, {}).pop(entry.entry_id, None)
    return True
