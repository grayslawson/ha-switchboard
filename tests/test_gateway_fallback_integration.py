from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from ha_switchboard.gateway import Gateway, GatewayConfig
from ha_switchboard.handoff import HandoffBroker
from ha_switchboard.jev_client import StaticJevClient
from ha_switchboard.openrouter_fallback import OpenAICompatibleFallbackAdapter
from ha_switchboard.protocol import (
    Complexity,
    JevDecision,
    ModelRoute,
    PrivacyMode,
    ResponseKind,
    ResultKind,
    RouteKind,
)
from ha_switchboard.route_policy import RouteRegistry
from ha_switchboard.store import ProfileStore
from ha_switchboard.typed_http_fallback import TypedHttpFallbackAdapter


RAW_ENTITY_ID = "light.living_room"
PROVIDER_SECRET = "provider-secret-fixture"
MappingLike = dict[str, Any]
ResponseFactory = Callable[[MappingLike], MappingLike]


class _Response:
    def __init__(self, value: MappingLike) -> None:
        self.value = value

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.value).encode("utf-8")

def _route(*, privacy_modes: tuple[PrivacyMode, ...]) -> ModelRoute:
    return ModelRoute(
        route_id="typed-local",
        kind="typed_http",
        response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
        complexity_ceiling=Complexity.REASONING,
        privacy_modes=privacy_modes,
        latency_budget_ms=1_000,
        cost_ceiling=0,
    )


def _candidate(gateway: Gateway, *, domain: str = "light", operation: str = "set_brightness") -> dict[str, Any]:
    capability = next(
        item for item in gateway.active_profile.capabilities
        if item.domain == domain and item.operation == operation
    )
    return {
        "capability_id": capability.capability_id,
        "display_name": capability.display_name,
        "domain": capability.domain,
        "operation": capability.operation,
        "parameter_schema": capability.parameter_schema,
    }


def _request(
    gateway: Gateway,
    candidate: MappingLike,
    *,
    request_id: str = "gateway-fallback",
    utterance: str = "Set the living room lights brightness to 42 percent",
) -> MappingLike:
    return {
        "request_id": request_id,
        "conversation_id": "conversation-fallback",
        "utterance": utterance,
        "language": "en",
        "profile_revision": gateway.active_profile.revision,
        "policy_revision": "policy-1",
        "candidates": [candidate],
        "bounded_context": [],
        "sanitized_state": {},
    }


def _gateway(
    tmp_path,
    sanitized_discovery: dict[str, Any],
    *,
    privacy_modes: tuple[PrivacyMode, ...] = (PrivacyMode.LOCAL_ONLY,),
    gateway_privacy: PrivacyMode = PrivacyMode.LOCAL_ONLY,
) -> Gateway:
    routes = RouteRegistry((_route(privacy_modes=privacy_modes),))
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.CLARIFY, Complexity.REASONING, reason="bounded delegation")),
        routes=routes,
        handoff=HandoffBroker(
            routes,
            TypedHttpFallbackAdapter("http://local-reasoner:8090/decide"),
        ),
        config=GatewayConfig(privacy_mode=gateway_privacy),
    )
    gateway.reconcile(sanitized_discovery)
    return gateway


def _openai_gateway(tmp_path, sanitized_discovery: dict[str, Any]) -> Gateway:
    routes = RouteRegistry((_route(privacy_modes=(PrivacyMode.LOCAL_ONLY,)),))
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.CLARIFY, Complexity.REASONING, reason="bounded delegation")),
        routes=routes,
        handoff=HandoffBroker(
            routes,
            OpenAICompatibleFallbackAdapter(
                endpoint="http://127.0.0.1:8090/chat/completions",
                model="fixture/fallback",
            ),
        ),
        config=GatewayConfig(privacy_mode=PrivacyMode.LOCAL_ONLY),
    )
    gateway.reconcile(sanitized_discovery)
    return gateway


def _mock_transport(monkeypatch: pytest.MonkeyPatch, response_factory: ResponseFactory) -> list[MappingLike]:
    requests: list[MappingLike] = []

    def urlopen(request, timeout: float) -> _Response:
        assert timeout == 5.0
        payload = json.loads(request.data.decode("utf-8"))
        requests.append(payload)
        return _Response(response_factory(payload))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return requests


def _proposal(payload: MappingLike, capability_id: str) -> MappingLike:
    return {
        "contract": "ha-switchboard-fallback/v1",
        "handoff_id": payload["handoff_id"],
        "route_id": payload["route_id"],
        "handoff_depth": 1,
        "kind": "tool_proposal",
        "proposals": [{
            "capability_id": capability_id,
            "parameter_refs": [],
            "parameters": {"brightness": 42},
            "reason": "bounded typed match",
        }],
    }


def _assert_safe(value: object) -> None:
    serialized = json.dumps(value, sort_keys=True)
    assert RAW_ENTITY_ID not in serialized
    assert "service_data" not in serialized
    assert "light.turn_on" not in serialized
    assert PROVIDER_SECRET not in serialized


def test_gateway_typed_fallback_round_trip_reenters_proposal_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    sanitized_discovery: dict[str, Any],
) -> None:
    gateway = _gateway(tmp_path, sanitized_discovery)
    candidate = _candidate(gateway)
    requests = _mock_transport(monkeypatch, lambda payload: _proposal(payload, candidate["capability_id"]))

    result = gateway.process(_request(gateway, candidate))

    assert len(requests) == 1
    assert requests[0]["contract"] == "ha-switchboard-fallback/v1"
    assert requests[0]["route_id"] == "typed-local"
    assert requests[0]["handoff_depth"] == 1
    assert requests[0]["relevant_facts"] == [candidate]
    assert result.kind is ResultKind.EXECUTE
    assert result.response_key == "execute"
    assert result.route_id == "typed-local"
    assert result.handoff_id
    assert result.capability_id == candidate["capability_id"]
    assert result.parameters == {"brightness": 42.0}
    _assert_safe(requests)
    _assert_safe(result.to_dict())


@pytest.mark.parametrize(
    ("domain", "operation", "utterance"),
    (
        ("lock", "lock", "Lock the front door"),
        ("lock", "unlock", "Unlock the front door"),
        ("cover", "open_cover", "Open the garage door"),
        ("cover", "close_cover", "Close the garage door"),
    ),
)
def test_openai_compatible_fallback_can_select_confirmation_required_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    sanitized_discovery: dict[str, Any],
    domain: str,
    operation: str,
    utterance: str,
) -> None:
    gateway = _openai_gateway(tmp_path, sanitized_discovery)
    candidate = _candidate(gateway, domain=domain, operation=operation)

    def urlopen(request, timeout):
        assert timeout == 8.0
        payload = json.loads(request.data.decode("utf-8"))
        bounded_request = json.loads(payload["messages"][1]["content"])
        offered = bounded_request["choices"]
        assert len(offered) == 1
        content = json.dumps({
            "kind": "tool_proposal",
            "choice": offered[0]["capability_id"],
            "text": "",
            "reason": "the offered unlock capability matches the request",
            "parameters": {},
        })
        return _Response({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = gateway.process(_request(
        gateway,
        candidate,
        request_id=f"gateway-fallback-confirmation-{domain}-{operation}",
        utterance=utterance,
    ))

    assert result.kind.value == "confirm"
    assert result.response_key == "confirmation_required"
    assert result.capability_id == candidate["capability_id"]
    assert result.route_id == "typed-local"
    _assert_safe(result.to_dict())


def test_jev_refusal_can_handoff_one_bounded_proposal_to_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    sanitized_discovery: dict[str, Any],
) -> None:
    gateway = _openai_gateway(tmp_path, sanitized_discovery)
    gateway.jev = StaticJevClient(
        JevDecision(RouteKind.REFUSE, Complexity.REASONING, reason="jev could not classify")
    )
    candidate = _candidate(gateway, domain="lock", operation="unlock")

    def urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        bounded_request = json.loads(payload["messages"][1]["content"])
        offered = bounded_request["choices"]
        assert len(offered) == 1
        content = json.dumps({
            "kind": "tool_proposal",
            "choice": offered[0]["capability_id"],
            "text": "",
            "reason": "the offered unlock capability matches the request",
            "parameters": {},
        })
        return _Response({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = gateway.process(_request(
        gateway,
        candidate,
        request_id="gateway-fallback-after-jev-refusal",
        utterance="Unlock the front door",
    ))

    assert result.kind is ResultKind.CONFIRM
    assert result.response_key == "confirmation_required"
    assert result.capability_id == candidate["capability_id"]
    assert result.route_id == "typed-local"
    _assert_safe(result.to_dict())


def test_fallback_shortlist_prioritizes_named_target_beyond_context_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    sanitized_discovery: dict[str, Any],
) -> None:
    gateway = _openai_gateway(tmp_path, sanitized_discovery)
    candidate = _candidate(gateway, domain="lock", operation="unlock")
    filler = [
        {
            "capability_id": f"opaque-filler-{index}",
            "display_name": f"Unrelated device {index}",
            "domain": "light",
            "operation": "turn_on",
            "parameter_schema": {"properties": {}, "required": []},
        }
        for index in range(16)
    ]

    def urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        bounded_request = json.loads(payload["messages"][1]["content"])
        offered = bounded_request["choices"]
        assert len(offered) == 16
        assert offered[0]["capability_id"] == candidate["capability_id"]
        content = json.dumps({
            "kind": "tool_proposal",
            "choice": offered[0]["capability_id"],
            "text": "The model may explain this, but Switchboard discards it.",
            "reason": "the named unlock capability matches",
            "parameters": {},
        })
        return _Response({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    utterance = f"Unlock {candidate['display_name'].split(':', 1)[0]}"
    result = gateway.process({
        **_request(
            gateway,
            candidate,
            request_id="gateway-fallback-shortlist",
            utterance=utterance,
        ),
        "candidates": [*filler, candidate],
    })

    assert result.kind is ResultKind.CONFIRM
    assert result.response_key == "confirmation_required"
    assert result.capability_id == candidate["capability_id"]


def test_privacy_blocked_fallback_never_reaches_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    sanitized_discovery: dict[str, Any],
) -> None:
    gateway = _gateway(
        tmp_path,
        sanitized_discovery,
        privacy_modes=(PrivacyMode.HOSTED_ALLOWED,),
        gateway_privacy=PrivacyMode.LOCAL_ONLY,
    )
    candidate = _candidate(gateway)
    requests = _mock_transport(monkeypatch, lambda _payload: pytest.fail("privacy-blocked route must not be called"))

    result = gateway.process({
        **_request(gateway, candidate, request_id="privacy-blocked"),
        "privacy_mode": PrivacyMode.HOSTED_ALLOWED.value,
    })

    assert requests == []
    assert result.kind is ResultKind.REFUSE
    assert result.response_key == "route_not_allowed"
    assert result.handoff_id is None
    _assert_safe(result.to_dict())


@pytest.mark.parametrize("malformed_kind", ["raw_service_json", "empty_proposal"])
def test_malformed_fallback_response_fails_closed_at_gateway_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    sanitized_discovery: dict[str, Any],
    malformed_kind: str,
) -> None:
    gateway = _gateway(tmp_path, sanitized_discovery)
    candidate = _candidate(gateway)

    def malformed(payload: MappingLike) -> MappingLike:
        identity = {
            "contract": "ha-switchboard-fallback/v1",
            "handoff_id": payload["handoff_id"],
            "route_id": payload["route_id"],
            "handoff_depth": 1,
            "kind": "tool_proposal",
        }
        if malformed_kind == "raw_service_json":
            return {
                **identity,
                "service": "light.turn_on",
                "service_data": {"entity_id": RAW_ENTITY_ID, "api_key": PROVIDER_SECRET},
            }
        return {**identity, "proposals": []}

    requests = _mock_transport(monkeypatch, malformed)
    result = gateway.process(_request(gateway, candidate, request_id=f"malformed-{malformed_kind}"))

    assert len(requests) == 1
    assert result.kind is ResultKind.REFUSE
    assert result.response_key == "handoff_unavailable"
    assert result.route_id == "typed-local"
    assert result.handoff_id
    assert result.capability_id is None
    _assert_safe(result.to_dict())
