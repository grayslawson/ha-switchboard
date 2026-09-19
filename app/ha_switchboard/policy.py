"""Deterministic safety and route-envelope policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .protocol import Capability, Complexity, HomeProfile, LifecycleStatus, PrivacyMode, RiskClass


class PolicyError(ValueError):
    """A request cannot cross the policy boundary."""


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    revision: str = "policy-1"
    allowed_domains: frozenset[str] = frozenset(
        {"light", "switch", "fan", "media_player", "climate", "lock", "cover", "garage", "alarm_control_panel", "security"}
    )
    allowed_operations: frozenset[str] = frozenset(
        {
            "turn_on",
            "turn_off",
            "toggle",
            "set_brightness",
            "set_volume",
            "set_temperature",
            "set_hvac_mode",
            "play",
            "pause",
            "stop",
            "lock",
            "unlock",
            "open_cover",
            "close_cover",
        }
    )
    high_risk_domains: frozenset[str] = frozenset(
        {"lock", "cover", "garage", "alarm_control_panel", "security"}
    )
    confidence_threshold: float = 0.86
    ambiguity_threshold: float = 0.28
    max_latency_ms: int = 10_000
    max_cost: float = 1.0


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    needs_confirmation: bool = False
    reason: str = ""
    response_key: str = "policy_denied"


def find_capability(profile: HomeProfile, capability_id: str | None) -> Capability | None:
    if not capability_id:
        return None
    return next((item for item in profile.capabilities if item.capability_id == capability_id), None)


def evaluate_capability(
    profile: HomeProfile,
    capability_id: str | None,
    *,
    confidence: float,
    ambiguity: float,
    confirmed: bool,
    config: PolicyConfig = PolicyConfig(),
) -> PolicyDecision:
    """Apply deterministic gates after Jev proposes a capability."""

    if profile.status is not LifecycleStatus.ACTIVE:
        return PolicyDecision(False, reason="profile is not active", response_key="profile_stale")
    if not 0 <= confidence <= 1 or not 0 <= ambiguity <= 1:
        return PolicyDecision(False, reason="invalid confidence", response_key="jev_invalid_response")
    capability = find_capability(profile, capability_id)
    if capability is None:
        return PolicyDecision(False, reason="unknown capability", response_key="candidate_not_allowed")
    if not capability.exposed:
        return PolicyDecision(False, reason="capability is not exposed", response_key="candidate_not_allowed")
    if not capability.available:
        return PolicyDecision(False, reason="capability is unavailable", response_key="candidate_not_allowed")
    if capability.domain not in config.allowed_domains:
        return PolicyDecision(False, reason="domain is not allowlisted", response_key="policy_denied")
    if capability.operation not in config.allowed_operations:
        return PolicyDecision(False, reason="operation is not allowlisted", response_key="policy_denied")
    if confidence < config.confidence_threshold:
        return PolicyDecision(False, reason="confidence below threshold", response_key="confidence_too_low")
    if ambiguity > config.ambiguity_threshold:
        return PolicyDecision(False, reason="candidate is ambiguous", response_key="ambiguous_request")
    high_risk = capability.risk_class in {RiskClass.CONFIRM, RiskClass.BLOCKED}
    high_risk = high_risk or capability.domain in config.high_risk_domains
    if capability.risk_class is RiskClass.BLOCKED:
        return PolicyDecision(False, reason="capability is blocked", response_key="policy_denied")
    if high_risk and not confirmed:
        return PolicyDecision(False, needs_confirmation=True, reason="explicit confirmation required", response_key="confirmation_required")
    return PolicyDecision(True, reason="allowlisted and verified", response_key="execute")


def validate_parameters(capability: Capability, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only the bounded parameters declared by a capability."""

    if not isinstance(parameters, Mapping) or len(parameters) > 8:
        raise PolicyError("parameters must be a bounded object")
    schema = capability.parameter_schema
    allowed = set(schema.get("properties", {})) if isinstance(schema, Mapping) else set()
    unknown = set(parameters) - allowed
    if unknown:
        raise PolicyError(f"unknown parameters: {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {}
    for key, value in parameters.items():
        spec = schema.get("properties", {}).get(key, {}) if isinstance(schema, Mapping) else {}
        if spec.get("type") == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise PolicyError(f"{key} must be numeric")
            if "minimum" in spec and value < spec["minimum"]:
                raise PolicyError(f"{key} is below its minimum")
            if "maximum" in spec and value > spec["maximum"]:
                raise PolicyError(f"{key} is above its maximum")
            result[key] = float(value)
        elif spec.get("type") == "string":
            if not isinstance(value, str) or len(value) > 128:
                raise PolicyError(f"{key} must be bounded text")
            if spec.get("enum") and value not in spec["enum"]:
                raise PolicyError(f"{key} is not an allowed value")
            result[key] = value
        else:
            raise PolicyError(f"unsupported parameter schema for {key}")
    return result


def route_allowed(
    *,
    privacy_mode: PrivacyMode,
    complexity: Complexity,
    latency_ms: int,
    cost: float,
    route_privacy_modes: frozenset[PrivacyMode],
    route_complexity: Complexity,
    config: PolicyConfig = PolicyConfig(),
) -> bool:
    order = {
        Complexity.SIMPLE: 0,
        Complexity.MEDIUM: 1,
        Complexity.COMPLEX: 2,
        Complexity.REASONING: 3,
    }
    return (
        privacy_mode in route_privacy_modes
        and order[route_complexity] >= order[complexity]
        and 0 <= latency_ms <= config.max_latency_ms
        and 0 <= cost <= config.max_cost
    )
