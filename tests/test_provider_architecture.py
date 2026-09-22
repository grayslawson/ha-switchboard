from __future__ import annotations

import json
from dataclasses import replace

import pytest

from ha_switchboard.jev_client import (
    HttpJevClient,
    JevInvalidResponse,
    OpenRouterDecisionsClient,
    TypeSafeJevClient,
)
from ha_switchboard.protocol import Complexity, DecisionRequest, PrivacyMode, RouteKind
from ha_switchboard.server import _migrate_options, build_gateway


def _request() -> DecisionRequest:
    return DecisionRequest(
        request_id="provider-request",
        conversation_id="provider-conversation",
        utterance="turn on the study light",
        language="en",
        profile_revision="profile-1",
        policy_revision="policy-1",
        candidates=(
            {
                "capability_id": "cap-light-on",
                "display_name": "Study light: turn on",
                "domain": "light",
                "operation": "turn_on",
                "parameter_schema": {"properties": {}, "required": []},
            },
        ),
    )


class _Response:
    def __init__(self, value: object) -> None:
        self.value = value

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.value).encode("utf-8")


def _typesafe_answers() -> dict[str, object]:
    choice = lambda value, confidence=0.96: {
        "type": "choice",
        "choice": value,
        "confidence": confidence,
        "probabilities": {value: confidence},
    }
    return {
        "route": choice(RouteKind.ROUTINE_CONTROL.value),
        "complexity": choice(Complexity.SIMPLE.value),
        "capability": choice("cap-light-on"),
        "ambiguity": {"type": "score", "score": 0.02},
        "risk": choice("routine"),
        "requires_confirmation": {"type": "noul", "noul": 0.01},
    }


def test_direct_typesafe_adapter_uses_systemone_and_typed_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["payload"] = json.loads(request.data)
        observed["timeout"] = timeout
        return _Response({"answers": _typesafe_answers()})

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", urlopen)
    decision = TypeSafeJevClient("http://127.0.0.1/v1", model="fixture-model").decide(_request())

    assert observed["url"] == "http://127.0.0.1/v1/systemone"
    assert observed["payload"]["model"] == "fixture-model"
    assert set(observed["payload"]) == {"model", "state", "questions"}
    assert decision.route is RouteKind.ROUTINE_CONTROL
    assert decision.capability_id == "cap-light-on"
    assert decision.parameters == {}


def test_typesafe_contract_rejects_extra_answer_fields_without_transport_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = _typesafe_answers()
    answers["route"]["provider_selection"] = "openrouter"
    monkeypatch.setattr(
        "ha_switchboard.jev_client.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({"answers": answers}),
    )

    with pytest.raises(JevInvalidResponse, match="typed contract"):
        TypeSafeJevClient("http://127.0.0.1/v1").decide(_request())


def test_jev_transport_retries_timeout_without_retrying_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError()
        return _Response({"decision": {
            "route": "routine_control", "capability_id": "cap-light-on",
            "confidence": 0.99, "ambiguity": 0.01,
        }})

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("ha_switchboard.jev_client.time.sleep", lambda _delay: None)
    decision = HttpJevClient("http://127.0.0.1:8090/decide").decide(_request())
    assert decision.capability_id == "cap-light-on"
    assert calls == 3


def test_jev_timeout_and_query_endpoint_bounds_are_rejected() -> None:
    with pytest.raises(ValueError, match="timeout"):
        HttpJevClient("http://127.0.0.1:8090/decide", timeout=0.1)
    with pytest.raises(ValueError, match="query"):
        HttpJevClient("http://127.0.0.1:8090/decide?token=secret")


def test_typesafe_extracts_bounded_numeric_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    request = replace(
        _request(),
        utterance="set the study light to 50 percent",
        candidates=(
            {
                "capability_id": "cap-light-on",
                "display_name": "Study light: set brightness",
                "domain": "light",
                "operation": "set_brightness",
                "parameter_schema": {
                    "properties": {"brightness": {"type": "number", "minimum": 0, "maximum": 100}},
                    "required": ["brightness"],
                },
            },
        ),
    )
    answers = _typesafe_answers()
    answers["route"] = {**answers["route"], "choice": "routine_control"}
    answers["parameter_0_0"] = {
        "type": "score", "score": 50, "confidence": 0.98,
    }

    def urlopen(request_obj, timeout):
        payload = json.loads(request_obj.data)
        assert payload["questions"]["parameter_0_0"]["type"] == "score"
        return _Response({"answers": answers})

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", urlopen)
    decision = TypeSafeJevClient("http://127.0.0.1/v1").decide(request)
    assert decision.parameters == {"brightness": 50.0}


def test_provider_selection_is_explicit_and_openrouter_decisions_stays_distinct(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "ha_switchboard.server._load_options",
        lambda _path: {
            "jev_provider": "typesafe",
            "jev_endpoint": "https://openrouter.ai/api/alpha/decisions",
            "jev_model": "fixture-model",
            "privacy_mode": "local_only",
        },
    )
    gateway = build_gateway(str(tmp_path))
    assert not isinstance(gateway.jev, TypeSafeJevClient)
    assert gateway.jev.__class__.__name__ == "StaticJevClient"
    assert "invalid_jev_configuration" in gateway.configuration_warnings

    migrated = _migrate_options(
        {"jev_endpoint": "https://openrouter.ai/api/alpha/decisions", "fallback_endpoint": "http://127.0.0.1:8090/v1"}
    )
    assert migrated["jev_provider"] == "openrouter"
    assert migrated["fallback_base_url"] == "http://127.0.0.1:8090/v1"
    assert isinstance(OpenRouterDecisionsClient("https://openrouter.ai/api/alpha/decisions"), OpenRouterDecisionsClient)


def test_generic_fallback_accepts_base_url_and_keeps_local_privacy(monkeypatch, tmp_path) -> None:
    from ha_switchboard.openrouter_fallback import OpenAICompatibleFallbackAdapter

    monkeypatch.setattr(
        "ha_switchboard.server._load_options",
        lambda _path: {
            "jev_provider": "disabled",
            "fallback_provider": "openai_compatible",
            "fallback_base_url": "http://127.0.0.1:8090/v1",
            "fallback_model": "fixture-model",
            "privacy_mode": "local_only",
        },
    )
    gateway = build_gateway(str(tmp_path))

    assert isinstance(gateway.handoff.adapter, OpenAICompatibleFallbackAdapter)
    assert gateway.handoff.adapter.endpoint == "http://127.0.0.1:8090/v1/chat/completions"
    assert PrivacyMode.LOCAL_ONLY in gateway.routes.routes[0].privacy_modes
    assert gateway.routes.routes[0].privacy_modes != (PrivacyMode.HOSTED_ALLOWED,)


def test_generic_jev_parameter_questions_and_values_are_schema_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    request = request.__class__(
        **{
            **request.to_dict(),
            "candidates": ({
                "capability_id": "cap-light-on",
                "display_name": "Study light: set brightness",
                "domain": "light",
                "operation": "set_brightness",
                "parameter_schema": {
                    "required": ["brightness"],
                    "properties": {"brightness": {"type": "number", "minimum": 0, "maximum": 100}},
                },
            },),
        }
    )

    observed: dict[str, object] = {}

    def urlopen(url_request, timeout):
        observed["payload"] = json.loads(url_request.data)
        observed["timeout"] = timeout
        return _Response({
            "decision": {
                "route": "routine_control",
                "complexity": "simple",
                "capability_id": "cap-light-on",
                "confidence": 0.99,
                "ambiguity": 0.01,
                "parameters": {"brightness": 42},
            },
        })

    monkeypatch.setattr("ha_switchboard.jev_client.urllib.request.urlopen", urlopen)
    decision = HttpJevClient("http://127.0.0.1:8090/decide").decide(request)

    assert decision.parameters == {"brightness": 42.0}
    payload = observed["payload"]
    assert isinstance(payload, dict)
    assert payload["questions"][-1]["kind"] == "typed_object"
    assert payload["questions"][-1]["questions"][0]["range"] == [0, 100]


def test_compatibility_status_is_secret_safe_and_probe_is_opt_in(tmp_path) -> None:
    gateway = build_gateway(str(tmp_path))
    status = gateway.provider_compatibility()
    assert status["status"] == "not_checked"
    assert status["providers"]["jev"]["status"] == "not_configured"
    assert "endpoint" not in json.dumps(status)
    assert "api_key" not in json.dumps(status)
