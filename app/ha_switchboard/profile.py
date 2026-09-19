"""Compile sanitized Home Assistant observations into a versioned profile."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Mapping

from .protocol import (
    Capability,
    CapabilityKind,
    HomeProfile,
    LifecycleStatus,
    ProfileSection,
    RiskClass,
    SectionId,
)
from .redaction import opaque_id, sanitized_json


SECTION_DEPENDENCIES: dict[SectionId, tuple[SectionId, ...]] = {
    SectionId.ENTITIES: (SectionId.ORGANIZATION, SectionId.EXPOSURE, SectionId.SERVICES),
    SectionId.DEVICES: (SectionId.ORGANIZATION,),
    SectionId.ORGANIZATION: (),
    SectionId.EXPOSURE: (SectionId.ENTITIES, SectionId.ROUTINES),
    SectionId.SERVICES: (SectionId.ENTITIES, SectionId.ROUTINES),
    SectionId.ROUTINES: (SectionId.ENTITIES, SectionId.EXPOSURE, SectionId.SERVICES),
    SectionId.ASSIST_SURFACES: (),
    SectionId.COMPATIBILITY: (),
    SectionId.ROUTE_POLICY: (),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _fingerprint(value: Any) -> str:
    digest = hashlib.sha256(sanitized_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _text(value: Any, fallback: str = "") -> str:
    return str(value).strip() if value is not None else fallback


def _aliases(entity: Mapping[str, Any]) -> tuple[str, ...]:
    raw = entity.get("aliases", ())
    if isinstance(raw, str):
        raw = [raw]
    return tuple(dict.fromkeys(_text(value) for value in raw if _text(value)))[:32]


def _risk(entity: Mapping[str, Any]) -> RiskClass:
    value = _text(entity.get("risk_class", entity.get("risk", "routine")))
    try:
        return RiskClass(value)
    except ValueError:
        return RiskClass.ROUTINE


def _parameter_schema(entity: Mapping[str, Any], operation: str) -> dict[str, Any]:
    provided = entity.get("parameter_schema")
    if isinstance(provided, Mapping):
        return dict(provided)
    if operation == "set_brightness":
        return {"properties": {"brightness": {"type": "number", "minimum": 0, "maximum": 100}}}
    if operation == "set_volume":
        return {"properties": {"volume": {"type": "number", "minimum": 0, "maximum": 1}}}
    if operation == "set_temperature":
        return {"properties": {"temperature": {"type": "number", "minimum": 5, "maximum": 35}}}
    return {"properties": {}}


def _safe_metadata(value: Any) -> Any:
    """Remove adapter-local references from non-capability profile sections."""

    if isinstance(value, Mapping):
        return {
            str(key): _safe_metadata(item)
            for key, item in value.items()
            if str(key).lower() not in {"entity_id", "device_id", "area_id", "unique_id", "config_entry_id"}
        }
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item) for item in value]
    return value


class ProfileCompiler:
    """Compile adapter-owned observations without retaining raw entity IDs."""

    def compile(
        self,
        snapshot: Mapping[str, Any],
        *,
        revision: str | None = None,
        profile_id: str | None = None,
        now: str | None = None,
    ) -> HomeProfile:
        if not isinstance(snapshot, Mapping):
            raise ValueError("discovery snapshot must be an object")
        timestamp = now or utc_now()
        entities = snapshot.get("entities", ())
        if not isinstance(entities, (list, tuple)):
            raise ValueError("entities must be a list")
        if len(entities) > 2_000:
            raise ValueError("entity count exceeds bound")

        revision = revision or opaque_id("profile", timestamp)
        profile_id = profile_id or opaque_id("installation", _text(snapshot.get("installation_key"), "default"))

        normalized_entities: list[dict[str, Any]] = []
        capabilities: list[Capability] = []
        warnings: list[str] = []
        for entity in entities:
            if not isinstance(entity, Mapping):
                warnings.append("unsupported_entity_shape")
                continue
            raw_ref = _text(entity.get("entity_id"), _text(entity.get("adapter_ref")))
            if not raw_ref:
                warnings.append("entity_missing_reference")
                continue
            domain = _text(entity.get("domain"), raw_ref.split(".", 1)[0])
            display_name = _text(entity.get("name"), raw_ref.split(".", 1)[-1].replace("_", " "))
            aliases = _aliases(entity)
            adapter_ref = _text(entity.get("adapter_ref"), opaque_id("adapter", raw_ref))
            operations = entity.get("operations", ())
            if isinstance(operations, str):
                operations = [operations]
            operations = tuple(dict.fromkeys(_text(item) for item in operations if _text(item)))
            normalized = {
                "adapter_ref": adapter_ref,
                "domain": domain,
                "name": display_name,
                "area": _text(entity.get("area")) or None,
                "floor": _text(entity.get("floor")) or None,
                "labels": sorted(_text(item) for item in entity.get("labels", ()) if _text(item)),
                "aliases": sorted(aliases),
                "exposed": bool(entity.get("exposed", False)),
                "available": bool(entity.get("available", True)),
                "operations": operations,
                "risk_class": _risk(entity).value,
            }
            normalized_entities.append(normalized)
            if not normalized["exposed"]:
                continue
            for operation in operations:
                if not operation:
                    continue
                kind = CapabilityKind.ENTITY_ACTION
                capability_id = opaque_id("capability", f"{raw_ref}:{operation}")
                capabilities.append(
                    Capability(
                        capability_id=capability_id,
                        kind=kind,
                        display_name=f"{display_name}: {operation.replace('_', ' ')}",
                        domain=domain,
                        operation=operation,
                        adapter_ref=adapter_ref,
                        area=normalized["area"],
                        floor=normalized["floor"],
                        labels=tuple(normalized["labels"]),
                        aliases=tuple(aliases),
                        exposed=True,
                        available=normalized["available"],
                        risk_class=_risk(entity),
                        parameter_schema=_parameter_schema(entity, operation),
                        provenance=("home_assistant.entity_registry",),
                    )
                )

        routines = snapshot.get("routines", ())
        normalized_routines: list[dict[str, Any]] = []
        if isinstance(routines, (list, tuple)):
            for routine in routines[:256]:
                if not isinstance(routine, Mapping):
                    warnings.append("unsupported_routine_shape")
                    continue
                if not routine.get("exposed", False):
                    continue
                raw_ref = _text(routine.get("entity_id"), _text(routine.get("adapter_ref")))
                if not raw_ref:
                    warnings.append("routine_missing_reference")
                    continue
                adapter_ref = _text(routine.get("adapter_ref"), opaque_id("adapter", raw_ref))
                name = _text(routine.get("name"), raw_ref.split(".", 1)[-1].replace("_", " "))
                normalized_routines.append({"adapter_ref": adapter_ref, "name": name, "kind": _text(routine.get("kind"), "script")})
                capabilities.append(
                    Capability(
                        capability_id=opaque_id("capability", f"routine:{raw_ref}"),
                        kind=CapabilityKind.SCRIPT if _text(routine.get("kind"), "script") == "script" else CapabilityKind.SCENE,
                        display_name=name,
                        domain=_text(routine.get("domain"), "script"),
                        operation="activate",
                        adapter_ref=adapter_ref,
                        exposed=True,
                        available=bool(routine.get("available", True)),
                        risk_class=_risk(routine),
                        provenance=("home_assistant.routine",),
                    )
                )

        sections_data: dict[SectionId, Any] = {
            SectionId.ENTITIES: normalized_entities,
            SectionId.DEVICES: _safe_metadata(snapshot.get("devices", [])),
            SectionId.ORGANIZATION: _safe_metadata(snapshot.get("organization", {})),
            SectionId.EXPOSURE: _safe_metadata(snapshot.get("exposure", [])),
            SectionId.SERVICES: _safe_metadata(snapshot.get("services", [])),
            SectionId.ROUTINES: normalized_routines,
            SectionId.ASSIST_SURFACES: _safe_metadata(snapshot.get("assist_surfaces", [])),
            SectionId.COMPATIBILITY: _safe_metadata(snapshot.get("compatibility", [])),
            SectionId.ROUTE_POLICY: _safe_metadata(snapshot.get("route_policy", {})),
        }
        section_status: dict[str, ProfileSection] = {}
        source_fingerprints: dict[str, str] = {}
        for section, value in sections_data.items():
            fingerprint = _fingerprint(value)
            source_fingerprints[section.value] = fingerprint
            section_status[section.value] = ProfileSection(
                section_id=section,
                status=LifecycleStatus.ACTIVE,
                source_fingerprint=fingerprint,
                observed_at=timestamp,
                profile_revision=revision,
                depends_on=SECTION_DEPENDENCIES[section],
            )

        surfaces = tuple(_safe_metadata(item) for item in snapshot.get("surfaces", ()) if isinstance(item, Mapping))
        return HomeProfile(
            profile_id=profile_id,
            revision=revision,
            status=LifecycleStatus.ACTIVE,
            created_at=timestamp,
            source_fingerprints=source_fingerprints,
            section_status=section_status,
            capabilities=tuple(capabilities),
            surfaces=surfaces,
            warnings=tuple(dict.fromkeys(warnings)),
            last_reconciled_at=timestamp,
        )


def profile_fingerprint(profile: HomeProfile) -> str:
    """Fingerprint only normalized profile metadata, never raw adapter data."""

    payload = {
        "source_fingerprints": profile.source_fingerprints,
        "capabilities": [
            {
                "id": item.capability_id,
                "kind": item.kind.value,
                "domain": item.domain,
                "operation": item.operation,
                "adapter_ref": item.adapter_ref,
                "exposed": item.exposed,
                "risk": item.risk_class.value,
            }
            for item in profile.capabilities
        ],
    }
    return _fingerprint(payload)


def mark_sections_stale(profile: HomeProfile, sections: set[SectionId], reason: str) -> HomeProfile:
    """Return a redacted profile view that cannot be used for writes."""

    updated: dict[str, ProfileSection] = {}
    for key, section in profile.section_status.items():
        if section.section_id in sections:
            updated[key] = ProfileSection(
                section_id=section.section_id,
                status=LifecycleStatus.STALE,
                source_fingerprint=section.source_fingerprint,
                observed_at=section.observed_at,
                profile_revision=section.profile_revision,
                depends_on=section.depends_on,
                invalidation_reason=reason[:128],
            )
        else:
            updated[key] = section
    return HomeProfile(
        profile_id=profile.profile_id,
        revision=profile.revision,
        status=LifecycleStatus.STALE,
        created_at=profile.created_at,
        source_fingerprints=profile.source_fingerprints,
        section_status=updated,
        capabilities=profile.capabilities,
        surfaces=profile.surfaces,
        warnings=profile.warnings,
        pending_invalidations=tuple(sorted(set(profile.pending_invalidations) | {reason[:128]})),
        monitor_cursor=profile.monitor_cursor,
        last_reconciled_at=profile.last_reconciled_at,
    )
