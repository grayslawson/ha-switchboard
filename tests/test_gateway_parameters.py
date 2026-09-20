from __future__ import annotations

from pathlib import Path

from ha_switchboard.gateway import Gateway
from ha_switchboard.jev_client import StaticJevClient
from ha_switchboard.profile import ProfileCompiler
from ha_switchboard.protocol import Complexity, JevDecision, RouteKind
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
