"""Discover Home Assistant capabilities while keeping raw IDs Core-local."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from .capabilities import (
    CapabilityMap,
    CapabilityTarget,
    OperationSpec,
    operation_spec,
    operations_for_domain,
)
from .opaque import adapter_ref, capability_id, opaque_id, routine_capability_id


_RAW_REFERENCE_KEYS = frozenset({"entity_id", "device_id", "area_id", "unique_id", "config_entry_id"})
_MAX_ENTITIES = 2_000
_MAX_ALIASES = 32
_MAX_WARNINGS = 128
_MAX_SERVICE_FIELDS = 64
_MAX_DEVICE_DOMAINS = 32


@dataclass(frozen=True, slots=True)
class ProfileBuild:
    snapshot: dict[str, Any]
    targets: Mapping[str, CapabilityTarget]
    read_targets: Mapping[str, str]


def _text(value: Any, fallback: str = "") -> str:
    return str(value).strip() if value is not None else fallback


def _state_value(state: Any, key: str, default: Any = None) -> Any:
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _attributes(state: Any) -> Mapping[str, Any]:
    value = _state_value(state, "attributes", {})
    return value if isinstance(value, Mapping) else {}


def _registry_entry(registry: Any, entity_id: str) -> Any:
    if registry is None:
        return None
    getter = getattr(registry, "async_get", None)
    if callable(getter):
        try:
            return getter(entity_id)
        except (KeyError, TypeError, ValueError):
            return None
    entities = registry.get("entities") if isinstance(registry, Mapping) else getattr(registry, "entities", None)
    return entities.get(entity_id) if isinstance(entities, Mapping) else None


def _registry_names(registry: Any, attr: str) -> dict[str, str]:
    if isinstance(registry, Mapping):
        values = registry.get(attr, {})
    else:
        values = getattr(registry, attr, {}) if registry is not None else {}
    if not isinstance(values, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, item in values.items():
        name = _text(getattr(item, "name", None))
        if not name and isinstance(item, Mapping):
            name = _text(item.get("name"))
        if name:
            result[str(key)] = name
    return result


def _safe_aliases(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple, set)):
        return []
    return list(dict.fromkeys(_text(item) for item in values if _text(item)))[:_MAX_ALIASES]


def _available(state: Any) -> bool:
    return _text(_state_value(state, "state", "unknown")) not in {"unknown", "unavailable"}


def _service_map(hass: Any) -> Mapping[str, Any]:
    services = getattr(getattr(hass, "services", None), "async_services", None)
    if callable(services):
        try:
            value = services()
            return value if isinstance(value, Mapping) else {}
        except (RuntimeError, TypeError):
            return {}
    return {}


def _service_available(services: Mapping[str, Any], domain: str, service: str) -> bool:
    if not services:
        return True
    domain_services = services.get(domain)
    return isinstance(domain_services, Mapping) and service in domain_services


def _service_fields(item: Any) -> tuple[list[str], bool]:
    """Return bounded field names across live and fixture service shapes."""

    fields = _mapping_value(item, "fields", None)
    if fields is None:
        return [], True
    if not isinstance(fields, Mapping):
        return [], False
    names = [_text(key)[:64] for key in fields if _text(key)]
    return list(dict.fromkeys(names))[:_MAX_SERVICE_FIELDS], True


def _service_shape_warnings(services: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    for domain, domain_services in services.items():
        if not isinstance(domain_services, Mapping):
            warnings.append(f"service_domain_shape:{str(domain)[:64]}")
            continue
        for service, descriptor in domain_services.items():
            _fields, valid = _service_fields(descriptor)
            if not valid:
                warnings.append(f"service_shape_unrecognized:{str(domain)[:32]}:{str(service)[:32]}")
    return warnings[:_MAX_WARNINGS]


def _mapping_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _parameter_schema(domain: str, operation: str, state: Any) -> dict[str, Any]:
    spec = operation_spec(domain, operation)
    schema = copy.deepcopy(dict(spec.parameter_schema if spec else {"properties": {}}))
    props = schema.setdefault("properties", {})
    attrs = _attributes(state)
    if operation == "set_temperature":
        lower = attrs.get("min_temp", props["temperature"].get("minimum", 5))
        upper = attrs.get("max_temp", props["temperature"].get("maximum", 35))
        try:
            lower = max(5.0, float(lower))
            upper = min(35.0, float(upper))
            if isfinite(lower) and isfinite(upper) and lower <= upper:
                props["temperature"] = {"type": "number", "minimum": lower, "maximum": upper}
        except (TypeError, ValueError):
            pass
    if operation == "set_hvac_mode":
        modes = attrs.get("hvac_modes", ())
        if isinstance(modes, (list, tuple)):
            modes = [str(mode) for mode in modes if str(mode)][:32]
            if modes:
                props["hvac_mode"]["enum"] = modes
    return schema


def _attribute_shape_warnings(domain: str, state: Any) -> list[str]:
    """Report malformed integration attributes without rejecting the profile."""

    attrs = _attributes(state)
    warnings: list[str] = []
    if domain == "climate":
        modes = attrs.get("hvac_modes")
        if modes is not None and not isinstance(modes, (list, tuple)):
            warnings.append("attribute_shape:climate:hvac_modes")
        for key in ("min_temp", "max_temp"):
            value = attrs.get(key)
            if value is not None:
                try:
                    float(value)
                except (TypeError, ValueError):
                    warnings.append(f"attribute_shape:climate:{key}")
    if domain == "media_player" and attrs.get("volume_level") is not None:
        try:
            value = float(attrs["volume_level"])
            if not 0 <= value <= 1:
                warnings.append("attribute_range:media_player:volume_level")
        except (TypeError, ValueError):
            warnings.append("attribute_shape:media_player:volume_level")
    return warnings


def _assert_sanitized(value: Any, *, key: str | None = None) -> None:
    if key and key.lower() in _RAW_REFERENCE_KEYS:
        raise ValueError(f"raw Home Assistant reference {key!r} crossed the gateway boundary")
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("sanitized profile object is too large")
        for item_key, item in value.items():
            _assert_sanitized(item, key=str(item_key))
    elif isinstance(value, (list, tuple)):
        if len(value) > 2_000:
            raise ValueError("sanitized profile list is too large")
        for item in value:
            _assert_sanitized(item)
    elif isinstance(value, str) and len(value) > 4_000:
        raise ValueError("sanitized profile text is too large")
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise ValueError("sanitized profile contains an unsupported value")


class HomeAssistantProfileAdapter:
    """Build a complete sanitized profile and the matching Core target map."""

    def __init__(self, hass: Any, installation_key: str = "ha-switchboard") -> None:
        self.hass = hass
        self.installation_key = opaque_id("installation", installation_key)

    async def async_build(self) -> ProfileBuild:
        try:
            from homeassistant.helpers import area_registry, device_registry, entity_registry, floor_registry, label_registry

            entity_reg = entity_registry.async_get(self.hass)
            device_reg = device_registry.async_get(self.hass)
            area_reg = area_registry.async_get(self.hass)
            floor_reg = floor_registry.async_get(self.hass)
            label_reg = label_registry.async_get(self.hass)
        except ImportError:  # pragma: no cover - contract-test fallback
            entity_reg = device_reg = area_reg = floor_reg = label_reg = None

        area_names = _registry_names(area_reg, "areas")
        floor_names = _registry_names(floor_reg, "floors")
        label_names = _registry_names(label_reg, "labels")
        states = getattr(getattr(self.hass, "states", None), "async_all", lambda: ())()
        states = list(states or ())
        if len(states) > _MAX_ENTITIES:
            raise ValueError("Home Assistant entity count exceeds bound")

        services = _service_map(self.hass)
        entity_rows: list[dict[str, Any]] = []
        exposure: list[str] = []
        targets: dict[str, CapabilityTarget] = {}
        routines: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        warnings: list[str] = _service_shape_warnings(services)
        # Scripts and scenes are routine surfaces even though activation is
        # represented separately from the typed entity operation matrix.
        supported_domains = {domain for domain, _ in OPERATION_KEYS()} | {
            "sensor", "binary_sensor", "script", "scene"
        }
        read_targets: dict[str, str] = {}

        for state in states:
            entity_id = _text(_state_value(state, "entity_id"))
            if "." not in entity_id:
                warnings.append("unsupported_entity_shape")
                continue
            domain = entity_id.split(".", 1)[0]
            if domain == "group":
                attrs = _attributes(state)
                members = attrs.get("entity_id", ())
                if isinstance(members, str):
                    members = [members]
                if not isinstance(members, (list, tuple, set)):
                    warnings.append("unsupported_group_shape")
                    continue
                groups.append({
                    "adapter_ref": adapter_ref(entity_id),
                    "name": _text(attrs.get("friendly_name"), entity_id.split(".", 1)[-1].replace("_", " ")),
                    "members": [adapter_ref(str(member)) for member in members if "." in str(member)][:512],
                })
                continue
            if domain not in supported_domains:
                continue
            entry = _registry_entry(entity_reg, entity_id)
            disabled = bool(_mapping_value(entry, "disabled_by") or _mapping_value(entry, "hidden_by"))
            reference = adapter_ref(entity_id)
            attrs = _attributes(state)
            area_id = _text(_mapping_value(entry, "area_id"))
            area = area_names.get(area_id) or _text(attrs.get("area_name")) or None
            aliases = _safe_aliases(_mapping_value(entry, "aliases") or attrs.get("aliases", ()))
            name = _text(_mapping_value(entry, "name")) or _text(_mapping_value(entry, "original_name"))
            name = name or _text(attrs.get("friendly_name"), entity_id.split(".", 1)[-1].replace("_", " "))
            exposed = False if disabled else self._is_exposed(entity_id, state)
            available = _available(state)
            if exposed:
                exposure.append(reference)
                read_targets[reference] = entity_id

            if domain in {"script", "scene"}:
                if exposed:
                    routines.append({"adapter_ref": reference, "name": name, "kind": domain, "exposed": True})
                    spec = operation_spec(domain, "activate")
                    if spec:
                        routine_id = routine_capability_id(reference)
                        targets[routine_id] = CapabilityTarget(routine_id, reference, entity_id, domain, "activate", spec)
                continue

            operations: list[str] = []
            parameter_schemas: dict[str, dict[str, Any]] = {}
            warnings.extend(_attribute_shape_warnings(domain, state))
            for operation in operations_for_domain(domain):
                spec = operation_spec(domain, operation)
                if spec and not disabled and _service_available(services, spec.service_domain, spec.service):
                    operations.append(operation)
                    parameter_schemas[operation] = _parameter_schema(domain, operation, state)
                    if exposed:
                        cap_id = capability_id(reference, operation)
                        targets[cap_id] = CapabilityTarget(
                            cap_id,
                            reference,
                            entity_id,
                            domain,
                            operation,
                            OperationSpec(
                                spec.service_domain,
                                spec.service,
                                parameter_schemas[operation],
                                spec.risk_class,
                            ),
                        )
                elif spec and not disabled:
                    warnings.append(f"service_unavailable:{domain}:{operation}")
            service_shapes: dict[str, list[str]] = {}
            for operation in operations:
                spec = operation_spec(domain, operation)
                if spec:
                    descriptor = services.get(spec.service_domain, {})
                    descriptor = descriptor.get(spec.service, {}) if isinstance(descriptor, Mapping) else {}
                    fields, _valid = _service_fields(descriptor)
                    if fields:
                        service_shapes[operation] = fields
            entity_rows.append(
                {
                    "adapter_ref": reference,
                    "domain": domain,
                    "name": name,
                    "area": area,
                    "floor": floor_names.get(_text(_mapping_value(entry, "floor_id"))) or None,
                    "labels": [label_names.get(str(label), str(label)) for label in (_mapping_value(entry, "labels", ()) or ())][:32],
                    "aliases": aliases,
                    "exposed": exposed,
                    "available": available,
                    "operations": operations,
                    "parameter_schemas": parameter_schemas,
                    "service_fields": service_shapes,
                    "risk_class": self._risk(domain),
                }
            )

        snapshot = {
            "installation_key": self.installation_key,
            "entities": entity_rows,
            "devices": self._sanitized_devices(device_reg, entity_reg, area_names, floor_names),
            "organization": {
                "areas": sorted(set(area_names.values()))[:256],
                "floors": sorted(set(floor_names.values()))[:128],
                "labels": sorted(set(label_names.values()))[:128],
                "groups": groups[:256],
            },
            "exposure": list(dict.fromkeys(exposure)),
            "services": self._sanitized_services(services),
            "routines": routines,
            "assist_surfaces": self._assist_surfaces(),
            "compatibility": [],
            "warnings": list(dict.fromkeys(warnings))[:_MAX_WARNINGS],
        }
        _assert_sanitized(snapshot)
        return ProfileBuild(snapshot, targets, read_targets)

    def _assist_surfaces(self) -> list[dict[str, Any]]:
        """Expose only descriptive Assist surfaces, never pipeline internals."""

        surfaces: list[dict[str, Any]] = []
        data = getattr(self.hass, "data", {})
        candidates: Any = data.get("assist_surfaces") if isinstance(data, Mapping) else None
        if candidates is None:
            config = getattr(self.hass, "config", None)
            candidates = getattr(config, "assist_surfaces", None)
        if isinstance(candidates, Mapping):
            candidates = list(candidates.values())
        if not isinstance(candidates, (list, tuple, set)):
            return surfaces
        for item in candidates:
            kind = _text(_mapping_value(item, "kind"), "assist_surface")
            name = _text(_mapping_value(item, "name"), kind)
            capabilities = _mapping_value(item, "capabilities", ())
            if isinstance(capabilities, str):
                capabilities = [capabilities]
            if not isinstance(capabilities, (list, tuple, set)):
                capabilities = []
            surfaces.append({
                "kind": kind[:64],
                "name": name[:128],
                "capabilities": [_text(value)[:64] for value in capabilities if _text(value)][:32],
            })
        return surfaces[:128]

    def _is_exposed(self, entity_id: str, state: Any) -> bool:
        try:
            from homeassistant.components.homeassistant.exposed_entities import async_should_expose

            return bool(async_should_expose(self.hass, "conversation", entity_id))
        except (ImportError, AttributeError, RuntimeError, TypeError):
            return bool(_attributes(state).get("exposed", False))

    @staticmethod
    def _risk(domain: str) -> str:
        return "confirm" if domain in {"lock", "cover", "garage"} else "routine"

    @staticmethod
    def _sanitized_devices(
        registry: Any,
        entity_registry: Any = None,
        area_names: Mapping[str, str] | None = None,
        floor_names: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        # Device IDs are intentionally not exported.  Names and manufacturer
        # metadata are useful context but remain bounded and non-addressable.
        values = registry.get("devices", {}) if isinstance(registry, Mapping) else (getattr(registry, "devices", {}) if registry is not None else {})
        result: list[dict[str, Any]] = []
        if isinstance(values, Mapping):
            entity_counts: dict[str, int] = {}
            domains: dict[str, set[str]] = {}
            entity_values = (
                entity_registry.get("entities", {})
                if isinstance(entity_registry, Mapping)
                else (getattr(entity_registry, "entities", {}) if entity_registry is not None else {})
            )
            if isinstance(entity_values, Mapping):
                for entity in entity_values.values():
                    device_id = _text(_mapping_value(entity, "device_id"))
                    entity_id = _text(_mapping_value(entity, "entity_id"))
                    if not device_id:
                        continue
                    entity_counts[device_id] = entity_counts.get(device_id, 0) + 1
                    if "." in entity_id:
                        domains.setdefault(device_id, set()).add(entity_id.split(".", 1)[0])
            for device_id, item in values.items():
                name = _text(_mapping_value(item, "name"))
                manufacturer = _text(_mapping_value(item, "manufacturer"))
                model = _text(_mapping_value(item, "model"))
                if name or manufacturer or model:
                    area_id = _text(_mapping_value(item, "area_id"))
                    floor_id = _text(_mapping_value(item, "floor_id"))
                    row: dict[str, Any] = {
                        "name": name[:128],
                        "manufacturer": manufacturer[:128],
                        "model": model[:128],
                        "entity_count": entity_counts.get(str(device_id), 0),
                        "domains": sorted(domains.get(str(device_id), set()))[:_MAX_DEVICE_DOMAINS],
                    }
                    if area_names and area_id in area_names:
                        row["area"] = area_names[area_id]
                    if floor_names and floor_id in floor_names:
                        row["floor"] = floor_names[floor_id]
                    result.append(row)
        return result[:512]

    @staticmethod
    def _sanitized_services(services: Mapping[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for domain in sorted(services):
            if not isinstance(services[domain], Mapping):
                continue
            operations: list[str] = []
            fields: dict[str, list[str]] = {}
            for candidate_domain, operation in OPERATION_KEYS():
                if candidate_domain != domain:
                    continue
                spec = operation_spec(candidate_domain, operation)
                if not spec or spec.service not in services[domain]:
                    continue
                service_name = spec.service
                if service_name not in operations:
                    operations.append(service_name)
                service_fields, _valid = _service_fields(services[domain][service_name])
                if service_fields:
                    fields[service_name] = service_fields
            if operations:
                row: dict[str, Any] = {"domain": str(domain), "operations": sorted(operations)[:64]}
                if fields:
                    row["fields"] = fields
                result.append(row)
        return result[:128]


def OPERATION_KEYS() -> tuple[tuple[str, str], ...]:
    from .capabilities import OPERATION_SPECS

    return tuple(OPERATION_SPECS)
