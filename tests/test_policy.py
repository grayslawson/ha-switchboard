from __future__ import annotations

from ha_switchboard.policy import evaluate_capability, validate_parameters
from ha_switchboard.profile import ProfileCompiler
from ha_switchboard.protocol import RiskClass


def _capability(discovery: dict, domain: str, operation: str):
    profile = ProfileCompiler().compile(discovery)
    return profile, next(item for item in profile.capabilities if item.domain == domain and item.operation == operation)


def test_unique_routine_is_allowed(discovery: dict) -> None:
    profile, capability = _capability(discovery, "light", "turn_on")
    result = evaluate_capability(profile, capability.capability_id, confidence=0.99, ambiguity=0.01, confirmed=False)
    assert result.allowed


def test_high_risk_action_requires_confirmation(discovery: dict) -> None:
    profile, capability = _capability(discovery, "lock", "unlock")
    assert capability.risk_class is RiskClass.CONFIRM
    result = evaluate_capability(profile, capability.capability_id, confidence=0.99, ambiguity=0.01, confirmed=False)
    assert result.needs_confirmation
    assert result.response_key == "confirmation_required"


def test_ambiguous_candidate_is_not_executed(discovery: dict) -> None:
    profile, capability = _capability(discovery, "light", "turn_on")
    result = evaluate_capability(profile, capability.capability_id, confidence=0.99, ambiguity=0.9, confirmed=False)
    assert not result.allowed
    assert result.response_key == "ambiguous_request"


def test_free_form_values_are_bounded(discovery: dict) -> None:
    profile, capability = _capability(discovery, "climate", "set_temperature")
    assert validate_parameters(capability, {"temperature": 21}) == {"temperature": 21.0}
