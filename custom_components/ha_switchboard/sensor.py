"""Read-only diagnostic sensors for the HA Switchboard gateway."""

from __future__ import annotations

from typing import Any, Mapping

from .client import GatewayClientError
from .const import DOMAIN

try:  # pragma: no cover - exercised in Home Assistant
    from homeassistant.components.sensor import SensorEntity
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity import EntityCategory
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    HA_AVAILABLE = True
except ImportError:  # pragma: no cover - contract tests run without HA
    HA_AVAILABLE = False

    class SensorEntity:  # type: ignore[no-redef]
        _attr_should_poll = True


_STATUS_KEYS = frozenset({"status", "stale", "capability_count", "last_reconciled_at"})


def _safe_status(status: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only non-sensitive, bounded diagnostic values from the gateway."""

    safe: dict[str, Any] = {}
    for key in _STATUS_KEYS:
        value = status.get(key)
        if key in {"status", "last_reconciled_at"} and isinstance(value, str):
            safe[key] = value[:128]
        elif key == "stale" and isinstance(value, bool):
            safe[key] = value
        elif key == "capability_count" and isinstance(value, int) and value >= 0:
            safe[key] = value
    return safe


class _SwitchboardDiagnosticSensor(SensorEntity):
    _attr_should_poll = True
    _attr_has_entity_name = True
    if HA_AVAILABLE:
        _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, client: Any, entry_id: str, kind: str) -> None:
        self._client = client
        self._kind = kind
        self._attr_unique_id = f"{entry_id}_{kind}"
        self._attr_name = {
            "ready": "Gateway ready",
            "capabilities": "Capabilities",
            "last_scan": "Last scan",
        }[kind]
        self._attr_native_value: Any = None
        self._attr_available = False
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_update(self) -> None:
        try:
            status = await self._client.status()
        except (GatewayClientError, OSError, TimeoutError, RuntimeError):
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        if not isinstance(status, Mapping):
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return
        safe = _safe_status(status)
        self._attr_available = True
        self._attr_extra_state_attributes = safe
        if self._kind == "ready":
            monitor = status.get("monitor", {})
            pending = monitor.get("pending_sections", ()) if isinstance(monitor, Mapping) else ()
            self._attr_native_value = (
                "ready" if status.get("status") == "active" and not status.get("stale", False) and not pending
                else "degraded"
            )
        elif self._kind == "capabilities":
            value = status.get("capability_count")
            self._attr_native_value = value if isinstance(value, int) and value >= 0 else 0
        else:
            value = status.get("last_reconciled_at")
            self._attr_native_value = value if isinstance(value, str) and value else "Never"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create diagnostic sensors using the already authenticated runtime client."""

    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return
    async_add_entities(
        [_SwitchboardDiagnosticSensor(runtime.client, entry.entry_id, kind) for kind in ("ready", "capabilities", "last_scan")]
    )


__all__ = ["async_setup_entry", "_SwitchboardDiagnosticSensor"]
