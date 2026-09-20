"""Home Assistant Core integration entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .client import GatewayClient
from .const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, DOMAIN
from .coordinator import ProfileCoordinator
from .diagnostics import CoreDiagnosticLog
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
_CONFIG_ENTRY_VERSION = 1


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    return True


async def async_migrate_entry(hass: Any, entry: SwitchboardConfigEntry) -> bool:
    """Migrate legacy URL/token fields without deleting runtime state.

    The canonical fields always win during rotation. A legacy alias is only
    copied when its canonical field is absent, then both aliases are removed so
    a stale token cannot be selected on a later restart.
    """

    data = dict(getattr(entry, "data", {}))
    migrated = dict(data)
    legacy_url = migrated.pop("url", None)
    legacy_token = migrated.pop("token", None)
    if CONF_GATEWAY_URL not in migrated and isinstance(legacy_url, str) and legacy_url.strip():
        migrated[CONF_GATEWAY_URL] = legacy_url.strip()
    if CONF_GATEWAY_TOKEN not in migrated and isinstance(legacy_token, str) and legacy_token:
        migrated[CONF_GATEWAY_TOKEN] = legacy_token
    entry_version = getattr(entry, "version", _CONFIG_ENTRY_VERSION)
    needs_version_update = isinstance(entry_version, int) and entry_version < _CONFIG_ENTRY_VERSION
    if migrated != data or needs_version_update:
        updater = getattr(getattr(hass, "config_entries", None), "async_update_entry", None)
        if callable(updater):
            updater(entry, data=migrated, version=_CONFIG_ENTRY_VERSION)
            if hasattr(entry, "version"):
                entry.version = _CONFIG_ENTRY_VERSION
        else:  # Contract-test doubles may expose mutable entries only.
            entry.data = migrated
            if hasattr(entry, "version"):
                entry.version = _CONFIG_ENTRY_VERSION
    return True


async def _async_update_listener(hass: Any, entry: SwitchboardConfigEntry) -> None:
    """Use updated discovery credentials in a fresh client and coordinator."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: Any, entry: SwitchboardConfigEntry) -> bool:
    await async_migrate_entry(hass, entry)
    data = dict(getattr(entry, "data", {}))
    gateway_url = data.get(CONF_GATEWAY_URL)
    if not isinstance(gateway_url, str) or not gateway_url.strip():
        raise ConfigEntryNotReady("HA Switchboard gateway URL is not configured")
    gateway_token = data.get(CONF_GATEWAY_TOKEN, "")
    if not isinstance(gateway_token, str):
        gateway_token = ""

    coordinator = None
    diagnostics = CoreDiagnosticLog()
    try:
        client = GatewayClient.from_hass(hass, gateway_url.strip(), gateway_token)
        installation_key = str(getattr(entry, "unique_id", None) or entry.entry_id)
        adapter = HomeAssistantProfileAdapter(hass, installation_key)
        coordinator = ProfileCoordinator(hass, entry, client, adapter)
        executor = CoreHomeAssistantExecutor(hass, coordinator.capability_map, coordinator)
        await coordinator.async_start()
    except Exception as exc:
        if coordinator is not None:
            await coordinator.async_shutdown()
        raise ConfigEntryNotReady("HA Switchboard gateway or profile is unavailable") from exc

    runtime_data = SwitchboardRuntimeData(
        client=client,
        coordinator=coordinator,
        executor=executor,
        diagnostics=diagnostics,
    )
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
        # Do not retain a client carrying the previous gateway token after a
        # failed/rotated entry unload. The next setup creates a fresh client.
        entry.runtime_data = None
    if hasattr(hass, "data"):
        hass.data.get(_RUNTIME_DATA_KEY, {}).pop(entry.entry_id, None)
    return True
