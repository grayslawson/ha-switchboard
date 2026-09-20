from __future__ import annotations

import json

import pytest

from ha_switchboard.protocol import Complexity, HandoffRequest, ModelRoute, PrivacyMode, ResponseKind
from ha_switchboard.typed_http_fallback import (
    TypedHttpFallbackAdapter,
    TypedHttpFallbackError,
    TypedHttpFallbackInvalidResponse,
    TypedHttpFallbackUnavailable,
)


def _route() -> ModelRoute:
    return ModelRoute(
        route_id="typed-local", kind="typed_http",
        response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
        complexity_ceiling=Complexity.REASONING, privacy_modes=(PrivacyMode.LOCAL_ONLY,),
        latency_budget_ms=1000, cost_ceiling=0,
    )


def _request(**overrides: object) -> HandoffRequest:
    values = dict(
        handoff_id="handoff-fixture", request_id="request-fixture",
        conversation_id="conversation-fixture", utterance="Set the light to 50 percent",
        bounded_context=(), relevant_facts=({
            "capability_id": "cap-opaque", "display_name": "Desk light",
            "parameter_schema": {"properties": {"brightness": {"type": "number"}}},
        },), route_id="typed-local", complexity=Complexity.REASONING,
        reason="open ended", allowed_response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
        handoff_depth=1, route_policy_revision="routes-fixture-1",
    )
    values.update(overrides)
    return HandoffRequest(**values)


class _Response:
    def __init__(self, value: object) -> None:
        self.value = value

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.value).encode()


def test_typed_contract_sends_only_sanitized_opaque_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({"route_id": "typed-local", "handoff_id": "handoff-fixture", "kind": "prose_response", "text": "Need a room."})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = TypedHttpFallbackAdapter("http://local-reasoner:8090/decide").invoke(_route(), _request())
    assert result["text"] == "Need a room."
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["contract"] == "ha-switchboard-fallback/v1"
    assert "entity_id" not in json.dumps(payload)


def test_raw_reference_is_rejected_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: pytest.fail("must not call provider"))
    request = _request(relevant_facts=({"capability_id": "cap-opaque", "entity_id": "light.secret"},))
    with pytest.raises(TypedHttpFallbackError, match="not sanitized"):
        TypedHttpFallbackAdapter("http://local-reasoner:8090/decide").invoke(_route(), request)


def test_transport_and_response_bounds_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(TypedHttpFallbackUnavailable):
        TypedHttpFallbackAdapter("http://local-reasoner:8090/decide").invoke(_route(), _request())

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response({"handoff_id": "wrong", "kind": "prose_response", "text": "x"}))
    with pytest.raises(TypedHttpFallbackInvalidResponse):
        TypedHttpFallbackAdapter("http://local-reasoner:8090/decide").invoke(_route(), _request(handoff_id="other"))


def test_typed_response_contract_rejects_unknown_fields_and_raw_references(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({
            "handoff_id": "handoff-fixture",
            "kind": "prose_response",
            "text": "ok",
            "entity_id": "light.secret",
        }),
    )
    with pytest.raises(TypedHttpFallbackInvalidResponse, match="sensitive"):
        TypedHttpFallbackAdapter("http://local-reasoner:8090/decide").invoke(_route(), _request())

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({
            "handoff_id": "handoff-fixture",
            "kind": "prose_response",
            "text": "ok",
            "provider": "other",
        }),
    )
    with pytest.raises(TypedHttpFallbackInvalidResponse, match="unsupported"):
        TypedHttpFallbackAdapter("http://local-reasoner:8090/decide").invoke(_route(), _request())


def test_typed_transport_retries_only_bounded_provider_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError()
        return _Response({
            "handoff_id": "handoff-fixture",
            "route_id": "typed-local",
            "kind": "prose_response",
            "text": "ok",
        })

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("ha_switchboard.typed_http_fallback.time.sleep", lambda _delay: None)
    result = TypedHttpFallbackAdapter("http://local-reasoner:8090/decide").invoke(_route(), _request())
    assert result["text"] == "ok"
    assert calls == 3
