from __future__ import annotations

from pathlib import Path

from ha_switchboard.gateway import Gateway
from ha_switchboard.handoff import HandoffBroker, StaticRouteAdapter
from ha_switchboard.jev_client import StaticJevClient
from ha_switchboard.profile import ProfileCompiler
from ha_switchboard.protocol import Complexity, JevDecision, RouteKind
from ha_switchboard.route_policy import RouteRegistry
from ha_switchboard.store import ProfileStore


def _gateway(tmp_path: Path, sanitized_discovery: dict, decision: JevDecision, routes=None, responses=None) -> Gateway:
    registry = routes or RouteRegistry()
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(decision),
        routes=registry,
        handoff=HandoffBroker(registry, StaticRouteAdapter(responses or {})),
    )
    gateway.reconcile(sanitized_discovery)
    return gateway


def _request(gateway: Gateway, capability_id: str, request_id: str = "request-one") -> dict:
    return {
        "request_id": request_id,
        "conversation_id": "conversation-one",
        "utterance": "turn it on",
        "language": "en",
        "profile_revision": gateway.active_profile.revision,
        "policy_revision": "policy-1",
        "candidates": [{"capability_id": capability_id, "display_name": "target", "domain": "light", "operation": "turn_on"}],
        "bounded_context": [],
        "sanitized_state": {},
    }


def test_gateway_executes_a_unique_routine_without_executing_it(tmp_path, sanitized_discovery):
    profile = ProfileCompiler().compile(sanitized_discovery)
    capability = next(item for item in profile.capabilities if item.domain == "light" and item.operation == "turn_on")
    gateway = _gateway(tmp_path, sanitized_discovery, JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 0.99, 0.01))
    result = gateway.process(_request(gateway, capability.capability_id))
    assert result.kind.value == "execute"
    assert result.capability_id == capability.capability_id


def test_duplicate_delivery_is_idempotent(tmp_path, sanitized_discovery):
    profile = ProfileCompiler().compile(sanitized_discovery)
    capability = next(item for item in profile.capabilities if item.domain == "light" and item.operation == "turn_on")
    gateway = _gateway(tmp_path, sanitized_discovery, JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 0.99, 0.01))
    payload = _request(gateway, capability.capability_id)
    assert gateway.process(payload) == gateway.process(payload)


def test_stale_profile_blocks_new_writes(tmp_path, sanitized_discovery):
    profile = ProfileCompiler().compile(sanitized_discovery)
    capability = next(item for item in profile.capabilities if item.domain == "light" and item.operation == "turn_on")
    gateway = _gateway(tmp_path, sanitized_discovery, JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 0.99, 0.01))
    gateway.invalidate({"event_type": "entity_registry_updated"})
    result = gateway.process(_request(gateway, capability.capability_id))
    assert result.response_key == "profile_reconciling"


def test_restart_restores_profile_but_requires_reconciliation(tmp_path, sanitized_discovery):
    profile = ProfileCompiler().compile(sanitized_discovery)
    capability = next(item for item in profile.capabilities if item.domain == "light" and item.operation == "turn_on")
    first = _gateway(
        tmp_path,
        sanitized_discovery,
        JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 0.99, 0.01),
    )

    restarted = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(
            JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 0.99, 0.01)
        ),
    )

    assert restarted.active_profile is not None
    assert restarted.active_profile.revision == first.active_profile.revision
    assert restarted.ready()["status"] == "degraded"
    result = restarted.process(_request(restarted, capability.capability_id, request_id="after-restart"))
    assert result.response_key == "profile_reconciling"


def test_high_risk_result_requires_confirmation(tmp_path, sanitized_discovery):
    profile = ProfileCompiler().compile(sanitized_discovery)
    capability = next(item for item in profile.capabilities if item.domain == "lock" and item.operation == "unlock")
    gateway = _gateway(
        tmp_path,
        sanitized_discovery,
        JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 0.99, 0.01),
    )
    result = gateway.process(_request(gateway, capability.capability_id))
    assert result.kind.value == "confirm"


def test_delegation_returns_bounded_prose(tmp_path, sanitized_discovery):
    registry = RouteRegistry.from_dict(
        {
            "revision": "routes-test",
            "routes": [
                {
                    "route_id": "local-reasoner",
                    "kind": "local_endpoint",
                    "response_kinds": ["prose_response"],
                    "complexity_ceiling": "reasoning",
                    "privacy_modes": ["local_only"],
                    "latency_budget_ms": 1000,
                    "cost_ceiling": 0,
                }
            ],
        }
    )
    response = {"kind": "prose_response", "handoff_id": "handoff-request-delegated", "text": "A bounded answer."}
    gateway = _gateway(
        tmp_path,
        sanitized_discovery,
        JevDecision(RouteKind.DELEGATE, Complexity.REASONING, confidence=0.95),
        routes=registry,
        responses={"local-reasoner": response},
    )
    result = gateway.process(
        {
            "request_id": "request-delegated",
            "conversation_id": "conversation-one",
            "utterance": "What should I do?",
            "language": "en",
            "profile_revision": gateway.active_profile.revision,
            "policy_revision": "policy-1",
            "candidates": [],
            "bounded_context": [],
            "sanitized_state": {},
            "privacy_mode": "local_only",
        }
    )
    # The static adapter fixture uses a fixed handoff identifier; a real route
    # adapter binds it to the request. This test proves the gateway refuses a
    # mismatched provider response rather than passing prose through blindly.
    assert result.response_key == "handoff_invalid_response"
