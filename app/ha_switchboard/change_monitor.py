"""Event-hint invalidation and fingerprint reconciliation state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from .profile import ProfileCompiler
from .protocol import HomeProfile, LifecycleStatus, SectionId


EVENT_SECTIONS: dict[str, frozenset[SectionId]] = {
    "homeassistant_started": frozenset(SectionId),
    "state_changed": frozenset({SectionId.ENTITIES}),
    "entity_registry_updated": frozenset({SectionId.ENTITIES, SectionId.EXPOSURE, SectionId.SERVICES}),
    "device_registry_updated": frozenset({SectionId.DEVICES, SectionId.ORGANIZATION}),
    "area_registry_updated": frozenset({SectionId.ORGANIZATION, SectionId.ENTITIES}),
    "floor_registry_updated": frozenset({SectionId.ORGANIZATION, SectionId.ENTITIES}),
    "label_registry_updated": frozenset({SectionId.ORGANIZATION, SectionId.ENTITIES}),
    "exposure_updated": frozenset({SectionId.EXPOSURE, SectionId.ENTITIES, SectionId.ROUTINES}),
    "service_schema_updated": frozenset({SectionId.SERVICES, SectionId.ENTITIES, SectionId.ROUTINES}),
    "assist_surface_updated": frozenset({SectionId.ASSIST_SURFACES}),
    "routine_updated": frozenset({SectionId.ROUTINES}),
    "reconnect": frozenset(SectionId),
    "restart": frozenset(SectionId),
    "manual_reconcile": frozenset(SectionId),
}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class ChangeMonitor:
    compiler: ProfileCompiler = field(default_factory=ProfileCompiler)
    periodic_minutes: int = 15
    connected: bool = False
    last_event_at: str | None = None
    last_reconcile_at: str | None = None
    pending_sections: set[SectionId] = field(default_factory=set)
    pending_reasons: set[str] = field(default_factory=set)
    active_profile: HomeProfile | None = None
    generation: int = 0

    def ingest(self, event: Mapping[str, Any]) -> set[SectionId]:
        kind = str(event.get("event_type", event.get("kind", "")))
        sections = EVENT_SECTIONS.get(kind, frozenset(SectionId))
        self.pending_sections.update(sections)
        self.pending_reasons.add(kind or "unknown_event")
        self.generation += 1
        self.last_event_at = now()
        if kind in {"reconnect", "restart"}:
            self.connected = True
        return set(sections)

    def mark_connected(self) -> None:
        self.connected = True
        self.ingest({"kind": "reconnect"})

    def mark_disconnected(self) -> None:
        self.connected = False
        self.pending_reasons.add("monitor_disconnected")

    def periodic_due(self) -> bool:
        if self.last_reconcile_at is None:
            return True
        try:
            last = datetime.fromisoformat(self.last_reconcile_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        age = (datetime.now(UTC) - last).total_seconds()
        return age >= max(1, self.periodic_minutes) * 60

    def reconcile(self, snapshot: Mapping[str, Any], *, revision: str | None = None) -> HomeProfile:
        """Build one complete candidate and activate it atomically."""

        generation_at_start = self.generation
        candidate = self.compiler.compile(snapshot, revision=revision)
        if generation_at_start != self.generation:
            self.pending_sections.update(SectionId)
            self.pending_reasons.add("source_changed_during_reconcile")
            if self.active_profile is not None:
                return self.active_profile
            raise RuntimeError("profile candidate was superseded during reconciliation")
        # A profile is activated only as a complete snapshot. The adapter has
        # already read all required sections after the invalidation cursor.
        self.active_profile = candidate
        self.pending_sections.clear()
        self.pending_reasons.clear()
        self.last_reconcile_at = candidate.last_reconciled_at or now()
        self.connected = True
        return candidate

    def status(self) -> dict[str, Any]:
        profile = self.active_profile
        sections = {}
        if profile:
            sections = {
                key: {
                    "status": section.status.value,
                    "fingerprint": section.source_fingerprint,
                    "observed_at": section.observed_at,
                }
                for key, section in profile.section_status.items()
            }
        return {
            "connected": self.connected,
            "last_event_at": self.last_event_at,
            "last_reconcile_at": self.last_reconcile_at,
            "pending_invalidations": sorted(self.pending_reasons),
            "pending_sections": sorted(section.value for section in self.pending_sections),
            "sections": sections,
        }

    def reconcile_if_due(self, snapshot_factory: Callable[[], Mapping[str, Any]]) -> HomeProfile | None:
        if self.pending_sections or self.periodic_due() or self.active_profile is None:
            return self.reconcile(snapshot_factory())
        return None
