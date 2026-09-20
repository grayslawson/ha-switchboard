"""Core-owned profile lifecycle and bounded request context."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping

from .capabilities import CapabilityMap, CapabilityTarget
from .client import GatewayClientError
from .const import (
    CONF_PROFILE_REFRESH_MINUTES,
    DEFAULT_PROFILE_REFRESH_MINUTES,
    MAX_PROFILE_REFRESH_MINUTES,
    MIN_PROFILE_REFRESH_MINUTES,
    PROFILE_EVENT_TYPES,
    STATE_CHANGED_EVENT,
)
from .profile_adapter import HomeAssistantProfileAdapter, ProfileBuild

try:  # Home Assistant runs @callback listeners on its event-loop thread.
    from homeassistant.core import callback
except ImportError:  # Contract tests run without Home Assistant installed.
    def callback(func):
        return func


try:  # Keep scan failure reporting bounded when Home Assistant is installed.
    from homeassistant.exceptions import HomeAssistantError
except ImportError:  # Contract tests run without Home Assistant installed.
    class HomeAssistantError(Exception):
        """Fallback marker for Home Assistant operation failures."""


_SCAN_ERRORS = (GatewayClientError, HomeAssistantError, OSError, RuntimeError, TypeError, ValueError, KeyError)


_STATE_ATTRIBUTES = frozenset(
    {"brightness", "brightness_pct", "volume_level", "temperature", "hvac_mode", "last_triggered"}
)


def _safe_state_attribute(value: Any) -> str | int | float | bool | None:
    """Keep bounded, JSON-safe state in a request; omit unsupported objects."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value[:256]
    if isinstance(value, int):
        return value if abs(value) <= 1_000_000_000 else None
    if isinstance(value, float):
        return value if isfinite(value) else None
    return None


def _bounded_refresh(value: Any) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PROFILE_REFRESH_MINUTES
    return max(MIN_PROFILE_REFRESH_MINUTES, min(MAX_PROFILE_REFRESH_MINUTES, value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileCoordinator:
    """Build, invalidate, and atomically activate Core profile revisions."""

    def __init__(self, hass: Any, entry: Any, client: Any, adapter: HomeAssistantProfileAdapter) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.adapter = adapter
        self.capability_map = CapabilityMap()
        self.profile_revision: str | None = None
        entry_data = getattr(entry, "data", {})
        self._refresh_override = (
            isinstance(entry_data, Mapping) and CONF_PROFILE_REFRESH_MINUTES in entry_data
        )
        self.refresh_minutes = _bounded_refresh(
            entry_data.get(CONF_PROFILE_REFRESH_MINUTES, DEFAULT_PROFILE_REFRESH_MINUTES)
            if isinstance(entry_data, Mapping)
            else DEFAULT_PROFILE_REFRESH_MINUTES
        )
        self._build: ProfileBuild | None = None
        self._state_by_capability: dict[str, dict[str, Any]] = {}
        self._unsubscribers: list[Any] = []
        self._refresh_cancel: Any = None
        self._recovery_cancel: Any = None
        self._refresh_task: asyncio.Task[Any] | None = None
        self._recovery_task: asyncio.Task[Any] | None = None
        self._flush_task: asyncio.Task[Any] | None = None
        self._scan_task: asyncio.Task[Any] | None = None
        self._scan_request_lock = asyncio.Lock()
        self._reconcile_lock = asyncio.Lock()
        self._pending_events: set[str] = set()
        self._profile_generation = 0
        self._started = False
        self._stale = True
        self.last_error: str | None = None
        self._scan_state = "idle"
        self._scan_generation: int | None = None
        self._last_scan_result: str | None = None
        self._last_scan_at: str | None = None
        self._last_scan_error: str | None = None
        self._scan_trigger: str | None = None
        self._last_reconcile_at: str | None = None
        self._reconcile_count = 0
        self._app_generation: str | None = None

    async def async_start(self) -> None:
        if self._started:
            return
        await self.client.health()
        await self._refresh_app_options()
        await self.async_reconcile()
        self._register_event_listeners()
        self._start_periodic_refresh()
        self._start_recovery_watch()
        self._started = True

    async def async_reconcile(self) -> dict[str, Any]:
        async with self._reconcile_lock:
            result: dict[str, Any] = {}
            try:
                for _attempt in range(3):
                    result = await self._async_reconcile_unlocked()
                    if not self._stale:
                        return result
                raise GatewayClientError("profile changed during reconciliation")
            except Exception as exc:
                self.last_error = type(exc).__name__
                self._scan_state = "failed"
                self._last_scan_result = "failed"
                raise

    async def async_scan(self) -> dict[str, Any]:
        """Run or join the single in-flight manual scan.

        A second UI request joins the first task, so it cannot create parallel
        replacement candidates or report a false success.
        """

        async with self._scan_request_lock:
            if self._scan_task is not None and not self._scan_task.done():
                task = self._scan_task
            else:
                task = self._create_task(self._run_scan())
                self._scan_task = task
        return await task

    async def _run_scan(self) -> dict[str, Any]:
        """Run exactly one manual scan, including its bounded outcome state."""

        self._scan_state = "running"
        self._scan_generation = self._profile_generation
        self._scan_trigger = "manual"
        self._last_scan_error = None
        try:
            request_scan = getattr(self.client, "scan", None)
            if callable(request_scan):
                await request_scan()
            result = await self.async_reconcile()
            self._scan_state = "completed"
            self._last_scan_result = "completed"
            self._last_scan_at = _utc_now()
            return result
        except _SCAN_ERRORS as exc:
            self._scan_state = "failed"
            self._last_scan_result = "failed"
            self._last_scan_at = _utc_now()
            self._last_scan_error = type(exc).__name__
            raise
        finally:
            current = asyncio.current_task()
            if self._scan_task is current:
                self._scan_task = None

    async def _async_reconcile_unlocked(self) -> dict[str, Any]:
        """Scan Core and replace the gateway profile as one serialized update."""

        generation = self._profile_generation
        build = await self.adapter.async_build()
        result = await self.client.reconcile(build.snapshot)
        revision = str(result.get("profile_revision") or "") if isinstance(result, Mapping) else ""
        if not revision:
            status = await self.client.status()
            revision = str(status.get("profile_revision") or "")
            result = dict(status)
        if not revision:
            raise GatewayClientError("gateway did not return a profile revision")

        # A registry event may arrive while the App is processing the prior
        # snapshot. Never publish that older build over the newer invalidation.
        if generation != self._profile_generation:
            self._stale = True
            return dict(result)

        # The gateway accepted the complete snapshot. Only now replace the
        # local map and request context used by the Conversation entity.
        self.capability_map.replace(revision, build.targets)
        self._build = build
        self.profile_revision = revision
        self._refresh_state_cache()
        self._stale = False
        self._scan_state = "completed"
        self._last_scan_result = "completed"
        self._last_reconcile_at = _utc_now()
        self._reconcile_count += 1
        self.last_error = None
        if isinstance(result, Mapping) and result.get("generation") is not None:
            self._app_generation = str(result["generation"])
        return dict(result)

    async def async_handle_event(self, event_type: str) -> None:
        kind = str(event_type).strip()
        if not kind or kind == STATE_CHANGED_EVENT:
            return
        self._stale = True
        self._profile_generation += 1
        try:
            await self.client.invalidate(kind)
            await self.async_reconcile()
        except Exception as exc:  # retain the last map but fail closed for writes
            self.last_error = type(exc).__name__

    def request_context(self) -> dict[str, Any]:
        """Return bounded, sanitized data for one gateway decision."""

        build = self._build
        if build is None or not self.profile_revision:
            return {"profile_revision": "", "candidates": [], "bounded_context": [], "sanitized_state": {}}

        entity_by_ref = {
            str(entity.get("adapter_ref")): entity
            for entity in build.snapshot.get("entities", ())
            if isinstance(entity, Mapping) and entity.get("adapter_ref")
        }
        candidates: list[dict[str, Any]] = []
        for target in self.capability_map.values():
            entity = entity_by_ref.get(target.adapter_ref, {})
            candidates.append(
                {
                    "capability_id": target.capability_id,
                    "domain": target.domain,
                    "operation": target.operation,
                    "display_name": f"{entity.get('name', target.domain)}: {target.operation.replace('_', ' ')}",
                    "area": entity.get("area"),
                    "floor": entity.get("floor"),
                    "labels": list(entity.get("labels", ()))[:32],
                    "aliases": list(entity.get("aliases", ()))[:32],
                    "available": bool(entity.get("available", True)),
                    "risk_class": target.risk_class,
                    "parameter_schema": dict(target.parameter_schema),
                }
            )

        organization = build.snapshot.get("organization", {})
        context = [{"organization": organization}] if isinstance(organization, Mapping) else []
        return {
            "profile_revision": self.profile_revision,
            "candidates": candidates[:64],
            "bounded_context": context,
            "sanitized_state": {key: dict(value) for key, value in self._state_by_capability.items()},
        }

    @property
    def snapshot(self) -> Mapping[str, Any]:
        """Current sanitized profile rows for Core-local read-only answers."""

        return self._build.snapshot if self._build is not None else {}

    @property
    def read_targets(self) -> Mapping[str, str]:
        return self._build.read_targets if self._build is not None else {}

    def writes_allowed(self, expected_revision: str | None = None) -> bool:
        return bool(
            self._started
            and not self._stale
            and self.profile_revision
            and self.capability_map.revision == self.profile_revision
            and (expected_revision is None or expected_revision == self.profile_revision)
        )

    def status(self) -> dict[str, Any]:
        return {
            "profile_revision": self.profile_revision,
            "stale": self._stale,
            "pending_events": sorted(self._pending_events),
            "last_error": self.last_error,
            "capability_count": len(self.capability_map),
            "refresh_minutes": self.refresh_minutes,
            "scan_state": self._scan_state,
            "last_scan_result": self._last_scan_result,
            "last_scan_at": self._last_scan_at,
            "last_scan_error": self._last_scan_error,
            "scan_generation": self._scan_generation,
            "scan_trigger": self._scan_trigger,
            "last_reconcile_at": self._last_reconcile_at,
            "reconcile_count": self._reconcile_count,
            "warning_count": len(self._build.snapshot.get("warnings", ())) if self._build else 0,
            "entity_count": len(self._build.snapshot.get("entities", ())) if self._build else 0,
            "routine_count": len(self._build.snapshot.get("routines", ())) if self._build else 0,
            "service_count": len(self._build.snapshot.get("services", ())) if self._build else 0,
            "generation": self._profile_generation,
            "app_generation": self._app_generation,
        }

    async def async_shutdown(self) -> None:
        for unsubscribe in self._unsubscribers:
            try:
                unsubscribe()
            except (RuntimeError, TypeError):
                pass
        self._unsubscribers.clear()
        if self._refresh_cancel:
            self._refresh_cancel()
            self._refresh_cancel = None
        if self._recovery_cancel:
            self._recovery_cancel()
            self._recovery_cancel = None
        for task in (self._refresh_task, self._recovery_task, self._flush_task, self._scan_task):
            if task and not task.done():
                task.cancel()
        self._refresh_task = self._recovery_task = self._flush_task = self._scan_task = None
        self._started = False

    def _register_event_listeners(self) -> None:
        bus = getattr(self.hass, "bus", None)
        listen = getattr(bus, "async_listen", None)
        if not callable(listen):
            return
        for event_type in (*PROFILE_EVENT_TYPES, STATE_CHANGED_EVENT):
            try:
                unsubscribe = listen(event_type, self._on_event)
                if callable(unsubscribe):
                    self._unsubscribers.append(unsubscribe)
            except (RuntimeError, TypeError):
                continue

    @callback
    def _on_event(self, event: Any) -> None:
        event_type = getattr(event, "event_type", None)
        data = getattr(event, "data", None)
        if isinstance(event, Mapping):
            event_type = event_type or event.get("event_type", event.get("type"))
            data = event.get("data", event)
        if not event_type:
            return
        event_type = str(event_type)
        if event_type == STATE_CHANGED_EVENT:
            self._update_state_from_event(data if isinstance(data, Mapping) else {})
            return
        self._pending_events.add(event_type)
        self._stale = True
        self._profile_generation += 1
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = self._create_task(self._flush_events())

    async def _flush_events(self) -> None:
        # Drain repeatedly: registry events can arrive while invalidation or
        # reconciliation is awaiting the gateway. A single-shot flush would
        # leave those events pending without scheduling another flush.
        for _batch in range(8):
            await asyncio.sleep(0)
            pending = set(self._pending_events)
            self._pending_events.clear()
            if not pending:
                return
            for event_type in sorted(pending):
                try:
                    await self.client.invalidate(event_type)
                except Exception as exc:
                    self.last_error = type(exc).__name__
            try:
                await self.async_reconcile()
            except Exception as exc:
                self.last_error = type(exc).__name__

        # Keep event processing bounded even if an integration continuously
        # emits registry changes. A new task drains any events that arrived
        # while this batch was running, without allowing one task to loop
        # forever and starve the Home Assistant event loop.
        await asyncio.sleep(0)
        if self._pending_events:
            self._flush_task = self._create_task(self._flush_events())

    def _refresh_state_cache(self) -> None:
        self._state_by_capability.clear()
        if self._build is None:
            return
        states = getattr(self.hass, "states", None)
        getter = getattr(states, "get", None)
        if not callable(getter):
            return
        for target in self._build.targets.values():
            self._set_state(target, getter(target.entity_id))

    def _update_state_from_event(self, data: Mapping[str, Any]) -> None:
        entity_id = data.get("entity_id")
        if not isinstance(entity_id, str) or self._build is None:
            return
        new_state = data.get("new_state")
        if new_state is None:
            states = getattr(self.hass, "states", None)
            getter = getattr(states, "get", None)
            new_state = getter(entity_id) if callable(getter) else None
        for target in self._build.targets.values():
            if target.entity_id == entity_id:
                self._set_state(target, new_state)

    def _set_state(self, target: CapabilityTarget, state: Any) -> None:
        if state is None:
            self._state_by_capability[target.capability_id] = {"state": "unavailable", "attributes": {}}
            return
        raw_attributes = state.get("attributes", {}) if isinstance(state, Mapping) else getattr(state, "attributes", {})
        if not isinstance(raw_attributes, Mapping):
            raw_attributes = {}
        self._state_by_capability[target.capability_id] = {
            "state": str(state.get("state", "unknown") if isinstance(state, Mapping) else getattr(state, "state", "unknown")),
            "attributes": {
                key: safe
                for key in _STATE_ATTRIBUTES
                if key in raw_attributes
                for safe in (_safe_state_attribute(raw_attributes[key]),)
                if safe is not None
            },
        }

    def _start_periodic_refresh(self) -> None:
        interval = timedelta(minutes=self.refresh_minutes)
        try:
            from homeassistant.helpers.event import async_track_time_interval

            self._refresh_cancel = async_track_time_interval(self.hass, self._periodic_refresh, interval)
            return
        except ImportError:  # pragma: no cover - contract-test fallback
            pass
        self._refresh_task = self._create_task(self._periodic_loop())

    async def _refresh_app_options(self) -> None:
        """Apply App-owned scheduling options without displacing Core overrides."""

        app_status = getattr(self.client, "app_status", None)
        if not callable(app_status):
            return
        try:
            payload = await app_status()
            if self._refresh_override or not isinstance(payload, Mapping):
                return
            requested = payload.get(CONF_PROFILE_REFRESH_MINUTES)
            if requested is None:
                return
            refresh_minutes = _bounded_refresh(requested)
            if refresh_minutes == self.refresh_minutes:
                return
            self.refresh_minutes = refresh_minutes
            if self._started:
                self._reschedule_periodic_refresh()
        except Exception as exc:
            self.last_error = type(exc).__name__

    def _reschedule_periodic_refresh(self) -> None:
        if self._refresh_cancel:
            self._refresh_cancel()
            self._refresh_cancel = None
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None
        self._start_periodic_refresh()

    def _start_recovery_watch(self) -> None:
        """Detect App restarts and manual scan requests before the long timer."""

        interval = timedelta(seconds=10)
        try:
            from homeassistant.helpers.event import async_track_time_interval

            self._recovery_cancel = async_track_time_interval(self.hass, self._recovery_tick, interval)
            return
        except ImportError:  # pragma: no cover - contract-test fallback
            pass
        self._recovery_task = self._create_task(self._recovery_loop())

    async def _recovery_tick(self, _now: Any = None) -> None:
        try:
            await self._refresh_app_options()
            status = await self.client.status()
            monitor = status.get("monitor", {}) if isinstance(status, Mapping) else {}
            pending = monitor.get("pending_sections", ()) if isinstance(monitor, Mapping) else ()
            generation = status.get("generation") if isinstance(status, Mapping) else None
            generation_changed = generation is not None and str(generation) != self._app_generation
            if status.get("status") != "active" or pending or generation_changed or status.get("profile_revision") != self.profile_revision:
                await self.async_reconcile()
        except Exception as exc:
            self.last_error = type(exc).__name__

    async def _recovery_loop(self) -> None:  # pragma: no cover
        while True:
            await asyncio.sleep(10)
            await self._recovery_tick()

    async def _periodic_refresh(self, _now: Any = None) -> None:
        try:
            await self.async_reconcile()
        except Exception as exc:
            self.last_error = type(exc).__name__

    async def _periodic_loop(self) -> None:  # pragma: no cover
        while True:
            await asyncio.sleep(self.refresh_minutes * 60)
            await self._periodic_refresh()

    def _create_task(self, coroutine: Any) -> asyncio.Task[Any]:
        creator = getattr(self.hass, "async_create_task", None)
        return creator(coroutine) if callable(creator) else asyncio.create_task(coroutine)
