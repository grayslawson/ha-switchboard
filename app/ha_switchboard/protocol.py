"""Bounded, JSON-friendly protocol types for the portable gateway."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any, Mapping


MAX_UTTERANCE = 2_000
MAX_CONTEXT_ITEMS = 16
MAX_CANDIDATES = 64
MAX_PROFILE_CAPABILITIES = 2_000
MAX_WARNINGS = 128
MAX_TEXT = 4_000
MAX_PARAMETERS = 8
MAX_PARAMETER_QUESTIONS = 8
MAX_PARAMETER_ENUM = 32
MAX_PARAMETER_TEXT = 128


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    RECONCILING = "reconciling"
    CANDIDATE = "candidate"
    FAILED = "failed"
    DISABLED = "disabled"


class SectionId(StrEnum):
    ENTITIES = "entities"
    DEVICES = "devices"
    ORGANIZATION = "organization"
    EXPOSURE = "exposure"
    SERVICES = "services"
    ROUTINES = "routines"
    ASSIST_SURFACES = "assist_surfaces"
    COMPATIBILITY = "compatibility"
    ROUTE_POLICY = "route_policy"


class CapabilityKind(StrEnum):
    ENTITY_ACTION = "entity_action"
    ENTITY_QUERY = "entity_query"
    SCRIPT = "script"
    SCENE = "scene"
    GROUP_ACTION = "group_action"
    CONVERSATION_DELEGATE = "conversation_delegate"


class RiskClass(StrEnum):
    READ_ONLY = "read_only"
    ROUTINE = "routine"
    CONFIRM = "confirm"
    BLOCKED = "blocked"


class RouteKind(StrEnum):
    ROUTINE_CONTROL = "routine_control"
    READ_ONLY = "read_only"
    DELEGATE = "delegate"
    CLARIFY = "clarify"
    REFUSE = "refuse"


class Complexity(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    REASONING = "reasoning"


class PrivacyMode(StrEnum):
    LOCAL_ONLY = "local_only"
    JEV_HOSTED_ALLOWED = "jev_hosted_allowed"
    HOSTED_ALLOWED = "hosted_allowed"


class ResponseKind(StrEnum):
    PROSE_RESPONSE = "prose_response"
    TOOL_PROPOSAL = "tool_proposal"


@dataclass(frozen=True, slots=True)
class ProfileChangeEvent:
    event_id: str
    kind: str
    affected_refs: tuple[str, ...]
    observed_at: str
    source_cursor: str | None
    sections: tuple[SectionId, ...]
    coalescing_key: str

    def __post_init__(self) -> None:
        _bounded_text(self.event_id, "event_id", 128)
        _bounded_text(self.kind, "kind", 64)
        _bounded_text(self.observed_at, "observed_at", 64)
        _bounded_text(self.coalescing_key, "coalescing_key", 128)
        _bounded_list(list(self.affected_refs), "affected_refs", 64)
        _bounded_list(list(self.sections), "sections", len(SectionId))


@dataclass(frozen=True, slots=True)
class SurfaceAdapter:
    surface_id: str
    kind: str
    capabilities: tuple[str, ...]
    trust: str
    portability: str
    conversation_agent: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.surface_id, "surface_id", 128)
        _bounded_text(self.kind, "kind", 64)
        _bounded_text(self.trust, "trust", 32)
        _bounded_text(self.portability, "portability", 32)
        _bounded_list(list(self.capabilities), "capabilities", 32)


class ResultKind(StrEnum):
    EXECUTE = "execute"
    CLARIFY = "clarify"
    CONFIRM = "confirm"
    ANSWER = "answer"
    DELEGATE = "delegate"
    REFUSE = "refuse"


def _bounded_text(value: str, name: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return value


def _bounded_list(value: list[Any] | tuple[Any, ...], name: str, limit: int) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} items")
    return list(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return value


def parameter_questions(candidates: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return a bounded, provider-neutral contract for typed parameters.

    The provider may answer these questions, but it never supplies a service
    name or entity reference.  Invalid schemas are omitted so they cannot
    widen the provider contract accidentally.
    """

    questions: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        capability_id = candidate.get("capability_id")
        schema = candidate.get("parameter_schema")
        if not isinstance(capability_id, str) or not capability_id or not isinstance(schema, Mapping):
            continue
        try:
            properties, required = _parameter_schema(schema)
        except ValueError:
            continue
        for name, spec in properties.items():
            if len(questions) >= MAX_PARAMETER_QUESTIONS:
                return questions
            if not isinstance(name, str) or not name or len(name) > 64 or not isinstance(spec, Mapping):
                continue
            kind = spec["type"]
            question: dict[str, Any] = {
                "name": name,
                "kind": kind,
                "capability_id": capability_id,
                "required": name in required,
            }
            if kind == "number":
                minimum, maximum = spec["minimum"], spec["maximum"]
                question["range"] = [minimum, maximum]
            else:
                enum = spec.get("enum")
                if enum is not None:
                    question["options"] = list(enum)
            questions.append(question)
    return questions


def normalize_typed_parameters(
    parameters: Mapping[str, Any],
    capability: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize a provider answer against one advertised capability schema."""

    if not isinstance(parameters, Mapping) or len(parameters) > MAX_PARAMETERS:
        raise ValueError("parameters must be a bounded object")
    schema = capability.get("parameter_schema", {})
    if not isinstance(schema, Mapping):
        raise ValueError("parameter schema is invalid")
    properties, required = _parameter_schema(schema)
    if set(parameters) - set(properties):
        raise ValueError("parameter is outside the advertised schema")
    missing = set(required) - set(parameters)
    if missing:
        raise ValueError("required parameter is missing")
    normalized: dict[str, Any] = {}
    for name, value in parameters.items():
        spec = properties.get(name)
        if not isinstance(name, str) or not isinstance(spec, Mapping):
            raise ValueError("parameter declaration is invalid")
        kind = spec.get("type")
        if kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError("parameter must be numeric")
            minimum, maximum = spec["minimum"], spec["maximum"]
            if not math.isfinite(value):
                raise ValueError("numeric parameter is not finite")
            if not minimum <= value <= maximum:
                raise ValueError("numeric parameter is outside its range")
            normalized[name] = float(value)
        elif kind == "string":
            if not isinstance(value, str) or not value or len(value) > MAX_PARAMETER_TEXT:
                raise ValueError("string parameter is invalid")
            enum = spec.get("enum")
            if enum is not None and (not isinstance(enum, (list, tuple)) or value not in enum):
                raise ValueError("string parameter is not an allowed value")
            normalized[name] = value
        else:
            raise ValueError("parameter type is unsupported")
    return normalized


def _parameter_schema(schema: Mapping[str, Any]) -> tuple[Mapping[str, Mapping[str, Any]], tuple[str, ...]]:
    """Validate the small schema language exposed to typed providers."""

    properties = schema.get("properties", {})
    required = schema.get("required", ())
    if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
        raise ValueError("parameter schema is invalid")
    if len(properties) > MAX_PARAMETERS or len(required) > MAX_PARAMETERS:
        raise ValueError("parameter schema exceeds its bound")
    if any(not isinstance(name, str) or not name or len(name) > 64 for name in required):
        raise ValueError("parameter schema has invalid required names")
    if len(set(required)) != len(required) or not set(required) <= set(properties):
        raise ValueError("parameter schema has conflicting required fields")
    checked: dict[str, Mapping[str, Any]] = {}
    for name, spec in properties.items():
        if not isinstance(name, str) or not name or len(name) > 64 or not isinstance(spec, Mapping):
            raise ValueError("parameter schema has an invalid property")
        kind = spec.get("type")
        if kind == "number":
            minimum, maximum = spec.get("minimum"), spec.get("maximum")
            if (
                not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
                or not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
                or not math.isfinite(minimum) or not math.isfinite(maximum) or minimum > maximum
            ):
                raise ValueError("parameter schema has an invalid numeric range")
        elif kind == "string":
            enum = spec.get("enum")
            if enum is not None and (
                not isinstance(enum, (list, tuple))
                or len(enum) > MAX_PARAMETER_ENUM
                or any(not isinstance(item, str) or not item or len(item) > MAX_PARAMETER_TEXT for item in enum)
                or len(set(enum)) != len(enum)
            ):
                raise ValueError("parameter schema has an invalid enum")
        else:
            raise ValueError("parameter schema has an unsupported type")
        checked[name] = spec
    return checked, tuple(required)


@dataclass(frozen=True, slots=True)
class ProfileSection:
    section_id: SectionId
    status: LifecycleStatus
    source_fingerprint: str
    observed_at: str
    profile_revision: str
    depends_on: tuple[SectionId, ...] = ()
    invalidation_reason: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.source_fingerprint, "source_fingerprint", 128)
        _bounded_text(self.observed_at, "observed_at", 64)
        _bounded_text(self.profile_revision, "profile_revision", 128)


@dataclass(frozen=True, slots=True)
class Capability:
    capability_id: str
    kind: CapabilityKind
    display_name: str
    domain: str
    operation: str
    adapter_ref: str
    area: str | None = None
    floor: str | None = None
    labels: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    exposed: bool = False
    available: bool = True
    risk_class: RiskClass = RiskClass.ROUTINE
    parameter_schema: Mapping[str, Any] = field(default_factory=dict)
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("capability_id", self.capability_id, 128),
            ("display_name", self.display_name, 256),
            ("domain", self.domain, 64),
            ("operation", self.operation, 128),
            ("adapter_ref", self.adapter_ref, 128),
        ):
            _bounded_text(value, name, limit)
        _bounded_list(list(self.aliases), "aliases", 32)
        _bounded_list(list(self.provenance), "provenance", 16)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Capability":
        return cls(
            capability_id=str(payload["capability_id"]),
            kind=CapabilityKind(payload["kind"]),
            display_name=str(payload["display_name"]),
            domain=str(payload["domain"]),
            operation=str(payload["operation"]),
            adapter_ref=str(payload["adapter_ref"]),
            area=payload.get("area"),
            floor=payload.get("floor"),
            labels=tuple(payload.get("labels", ())),
            aliases=tuple(payload.get("aliases", ())),
            exposed=bool(payload.get("exposed", False)),
            available=bool(payload.get("available", True)),
            risk_class=RiskClass(payload.get("risk_class", RiskClass.ROUTINE)),
            parameter_schema=dict(payload.get("parameter_schema", {})),
            provenance=tuple(payload.get("provenance", ())),
        )


@dataclass(frozen=True, slots=True)
class HomeProfile:
    profile_id: str
    revision: str
    status: LifecycleStatus
    created_at: str
    source_fingerprints: Mapping[str, str]
    section_status: Mapping[str, ProfileSection]
    capabilities: tuple[Capability, ...]
    surfaces: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    pending_invalidations: tuple[str, ...] = ()
    monitor_cursor: str | None = None
    last_reconciled_at: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.profile_id, "profile_id", 128)
        _bounded_text(self.revision, "revision", 128)
        _bounded_text(self.created_at, "created_at", 64)
        _bounded_list(list(self.capabilities), "capabilities", MAX_PROFILE_CAPABILITIES)
        _bounded_list(list(self.warnings), "warnings", MAX_WARNINGS)
        _bounded_list(list(self.surfaces), "surfaces", 128)

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HomeProfile":
        sections: dict[str, ProfileSection] = {}
        for key, value in dict(payload.get("section_status", {})).items():
            sections[str(key)] = ProfileSection(
                section_id=SectionId(value.get("section_id", key)),
                status=LifecycleStatus(value.get("status", LifecycleStatus.ACTIVE)),
                source_fingerprint=str(value.get("source_fingerprint", "unknown")),
                observed_at=str(value.get("observed_at", "unknown")),
                profile_revision=str(value.get("profile_revision", payload.get("revision", "unknown"))),
                depends_on=tuple(SectionId(item) for item in value.get("depends_on", ())),
                invalidation_reason=value.get("invalidation_reason"),
            )
        return cls(
            profile_id=str(payload["profile_id"]),
            revision=str(payload["revision"]),
            status=LifecycleStatus(payload.get("status", LifecycleStatus.ACTIVE)),
            created_at=str(payload["created_at"]),
            source_fingerprints=dict(payload.get("source_fingerprints", {})),
            section_status=sections,
            capabilities=tuple(Capability.from_dict(item) for item in payload.get("capabilities", ())),
            surfaces=tuple(payload.get("surfaces", ())),
            warnings=tuple(payload.get("warnings", ())),
            pending_invalidations=tuple(payload.get("pending_invalidations", ())),
            monitor_cursor=payload.get("monitor_cursor"),
            last_reconciled_at=payload.get("last_reconciled_at"),
        )


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    request_id: str
    conversation_id: str
    utterance: str
    language: str
    profile_revision: str
    policy_revision: str
    candidates: tuple[Mapping[str, Any], ...] = ()
    bounded_context: tuple[Mapping[str, Any], ...] = ()
    sanitized_state: Mapping[str, Any] = field(default_factory=dict)
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_ONLY
    decision_only: bool = False
    handoff_depth: int = 0

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("request_id", self.request_id, 128),
            ("conversation_id", self.conversation_id, 128),
            ("language", self.language, 32),
            ("profile_revision", self.profile_revision, 128),
            ("policy_revision", self.policy_revision, 128),
        ):
            _bounded_text(value, name, limit)
        _bounded_text(self.utterance, "utterance", MAX_UTTERANCE)
        _bounded_list(list(self.candidates), "candidates", MAX_CANDIDATES)
        _bounded_list(list(self.bounded_context), "bounded_context", MAX_CONTEXT_ITEMS)
        if self.handoff_depth not in (0, 1):
            raise ValueError("handoff_depth must be 0 or 1")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DecisionRequest":
        required = ("request_id", "conversation_id", "utterance", "language")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"missing request fields: {', '.join(missing)}")
        return cls(
            request_id=str(payload["request_id"]),
            conversation_id=str(payload["conversation_id"]),
            utterance=str(payload["utterance"]),
            language=str(payload.get("language", "en")),
            profile_revision=str(payload.get("profile_revision", "")),
            policy_revision=str(payload.get("policy_revision", "policy-unknown")),
            candidates=tuple(payload.get("candidates", ())),
            bounded_context=tuple(payload.get("bounded_context", ())),
            sanitized_state=dict(payload.get("sanitized_state", {})),
            privacy_mode=PrivacyMode(payload.get("privacy_mode", PrivacyMode.LOCAL_ONLY)),
            decision_only=bool(payload.get("decision_only", False)),
            handoff_depth=int(payload.get("handoff_depth", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True, slots=True)
class JevDecision:
    route: RouteKind
    complexity: Complexity
    capability_id: str | None = None
    confidence: float = 0.0
    ambiguity: float = 0.0
    risk: RiskClass = RiskClass.ROUTINE
    requires_confirmation: bool = False
    reason: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1 or not 0 <= self.ambiguity <= 1:
            raise ValueError("confidence and ambiguity must be between 0 and 1")
        if self.capability_id is not None:
            _bounded_text(self.capability_id, "capability_id", 128)
        if self.reason:
            _bounded_text(self.reason, "reason", 256)
        _bounded_list(list(self.parameters), "parameters", 8)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "JevDecision":
        return cls(
            route=RouteKind(payload["route"]),
            complexity=Complexity(payload.get("complexity", Complexity.SIMPLE)),
            capability_id=payload.get("capability_id"),
            confidence=float(payload.get("confidence", 0.0)),
            ambiguity=float(payload.get("ambiguity", 0.0)),
            risk=RiskClass(payload.get("risk", RiskClass.ROUTINE)),
            requires_confirmation=bool(payload.get("requires_confirmation", False)),
            reason=str(payload.get("reason", "")),
            parameters=dict(payload.get("parameters", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    kind: ResultKind
    request_id: str
    profile_revision: str
    policy_revision: str
    response_key: str
    capability_id: str | None = None
    capability_ids: tuple[str, ...] = ()
    route_id: str | None = None
    complexity: Complexity | None = None
    confidence: float | None = None
    handoff_id: str | None = None
    error_code: str | None = None
    text: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _bounded_list(list(self.capability_ids), "capability_ids", 32)
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("capability_ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True, slots=True)
class ModelRoute:
    route_id: str
    kind: str
    response_kinds: tuple[ResponseKind, ...]
    complexity_ceiling: Complexity
    privacy_modes: tuple[PrivacyMode, ...]
    latency_budget_ms: int
    cost_ceiling: float
    availability: str = "ready"
    fallback_route_ids: tuple[str, ...] = ()
    revision: str = "routes-1"
    schema_version: int = 1

    def supports(self, complexity: Complexity, privacy: PrivacyMode) -> bool:
        order = {
            Complexity.SIMPLE: 0,
            Complexity.MEDIUM: 1,
            Complexity.COMPLEX: 2,
            Complexity.REASONING: 3,
        }
        return (
            self.availability in {"ready", "degraded"}
            and order[self.complexity_ceiling] >= order[complexity]
            and privacy in self.privacy_modes
        )


@dataclass(frozen=True, slots=True)
class HandoffRequest:
    handoff_id: str
    request_id: str
    conversation_id: str
    utterance: str
    bounded_context: tuple[Mapping[str, Any], ...]
    relevant_facts: tuple[Mapping[str, Any], ...]
    route_id: str
    complexity: Complexity
    reason: str
    allowed_response_kinds: tuple[ResponseKind, ...]
    handoff_depth: int
    route_policy_revision: str
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_ONLY

    def __post_init__(self) -> None:
        if self.handoff_depth != 1:
            raise ValueError("a dispatched handoff must have depth 1")
        _bounded_text(self.utterance, "utterance", MAX_UTTERANCE)
        _bounded_list(list(self.bounded_context), "bounded_context", MAX_CONTEXT_ITEMS)
        _bounded_list(list(self.relevant_facts), "relevant_facts", MAX_CONTEXT_ITEMS)


@dataclass(frozen=True, slots=True)
class HandoffResponse:
    kind: ResponseKind
    handoff_id: str
    text: str | None = None
    proposals: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.text is not None:
            _bounded_text(self.text, "text", MAX_TEXT)
        _bounded_list(list(self.proposals), "proposals", 1)
        if self.kind is ResponseKind.PROSE_RESPONSE and not self.text:
            raise ValueError("prose_response requires text")
        if self.kind is ResponseKind.TOOL_PROPOSAL and not self.proposals:
            raise ValueError("tool_proposal requires one proposal")


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    receipt_id: str
    request_id: str
    profile_revision: str
    capability_id: str
    action: Mapping[str, Any]
    ha_result: Mapping[str, Any]
    verified: bool
    response_key: str
    handoff_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)
