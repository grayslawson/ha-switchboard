from __future__ import annotations

from pathlib import Path
import math

import pytest

from ha_switchboard.gateway import Gateway
from ha_switchboard.jev_client import StaticJevClient
from ha_switchboard.profile import ProfileCompiler
from ha_switchboard.protocol import Complexity, JevDecision, RouteKind, normalize_typed_parameters, parameter_questions
from ha_switchboard.store import ProfileStore


def _request(gateway: Gateway, capability_id: str) -> dict[str, object]:
    return {
        "request_id": "parameter-request",
        "conversation_id": "parameter-conversation",
        "utterance": "set the temperature",
        "language": "en",
        "profile_revision": gateway.active_profile.revision,
        "policy_revision": "policy-1",
        "candidates": [{"capability_id": capability_id}],
        "bounded_context": [],
        "sanitized_state": {},
    }


def _gateway(tmp_path: Path, snapshot: dict, decision: JevDecision) -> Gateway:
    gateway = Gateway(store=ProfileStore(tmp_path), jev=StaticJevClient(decision))
    gateway.reconcile(snapshot)
    return gateway


def test_gateway_validates_and_returns_typed_parameters(tmp_path: Path, sanitized_discovery: dict) -> None:
    profile = ProfileCompiler().compile(sanitized_discovery)
    capability = next(
        item for item in profile.capabilities if item.domain == "climate" and item.operation == "set_temperature"
    )
    gateway = _gateway(
        tmp_path,
        sanitized_discovery,
        JevDecision(
            RouteKind.ROUTINE_CONTROL,
            Complexity.SIMPLE,
            capability.capability_id,
            0.99,
            0.01,
            parameters={"temperature": 21},
        ),
    )

    result = gateway.process(_request(gateway, capability.capability_id))

    assert result.response_key == "execute"
    assert result.parameters == {"temperature": 21.0}


def test_gateway_rejects_missing_required_parameter(tmp_path: Path, sanitized_discovery: dict) -> None:
    profile = ProfileCompiler().compile(sanitized_discovery)
    capability = next(
        item for item in profile.capabilities if item.domain == "climate" and item.operation == "set_temperature"
    )
    gateway = _gateway(
        tmp_path,
        sanitized_discovery,
        JevDecision(
            RouteKind.ROUTINE_CONTROL,
            Complexity.SIMPLE,
            capability.capability_id,
            0.99,
            0.01,
        ),
    )

    result = gateway.process(_request(gateway, capability.capability_id))

    assert result.response_key == "invalid_parameters"
    assert result.kind.value == "refuse"


def _parameterized_capability() -> dict[str, object]:
    return {
        "capability_id": "climate-mode",
        "parameter_schema": {
            "required": ["mode", "temperature"],
            "properties": {
                "mode": {"type": "string", "enum": ["heat", "cool", "off"]},
                "temperature": {"type": "number", "minimum": 5, "maximum": 35},
            },
        },
    }


def test_typed_parameter_questions_are_bounded_and_schema_derived() -> None:
    questions = parameter_questions([_parameterized_capability()])

    assert questions == [
        {"name": "mode", "kind": "string", "capability_id": "climate-mode", "required": True, "options": ["heat", "cool", "off"]},
        {"name": "temperature", "kind": "number", "capability_id": "climate-mode", "required": True, "range": [5, 35]},
    ]


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"temperature": 20}, "required parameter is missing"),
        ({"mode": "dry", "temperature": 20}, "not an allowed value"),
        ({"mode": "heat", "temperature": 36}, "outside its range"),
        ({"mode": "heat", "temperature": "20"}, "must be numeric"),
        ({"mode": "heat", "temperature": math.inf}, "not finite"),
        ({"mode": "heat", "temperature": 20, "unexpected": 1}, "outside the advertised schema"),
    ],
)
def test_typed_parameter_answers_reject_invalid_missing_overflow_and_enum_values(
    parameters: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_typed_parameters(parameters, _parameterized_capability())


def test_typed_parameter_answers_normalize_safe_values() -> None:
    assert normalize_typed_parameters(
        {"mode": "heat", "temperature": 21}, _parameterized_capability()
    ) == {"mode": "heat", "temperature": 21.0}


@pytest.mark.parametrize(
    "schema",
    [
        {"required": ["missing"], "properties": {}},
        {"required": ["mode", "mode"], "properties": {"mode": {"type": "string"}}},
        {"required": [], "properties": {"temperature": {"type": "number", "minimum": 35, "maximum": 5}}},
        {"required": [], "properties": {"mode": {"type": "string", "enum": ["heat", "heat"]}}},
    ],
)
def test_conflicting_parameter_schema_is_rejected(schema: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="parameter schema"):
        normalize_typed_parameters({}, {"parameter_schema": schema})
