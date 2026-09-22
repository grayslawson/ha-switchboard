from __future__ import annotations

import json
from dataclasses import replace
import urllib.error

import pytest

from ha_switchboard.openrouter_fallback import (
    OpenRouterFallbackAdapter,
    OpenRouterFallbackInvalidResponse,
    OpenRouterFallbackUnavailable,
)
from ha_switchboard.protocol import Complexity, HandoffRequest, ResponseKind


def _request(*, handoff_id: str = "handoff-1", depth: int = 1) -> HandoffRequest:
    return HandoffRequest(
        handoff_id=handoff_id,
        request_id="request-1",
        conversation_id="conversation-1",
        utterance="Turn on the downstairs lights",
        bounded_context=(),
        relevant_facts=(
            {"capability_id": "cap-light-a", "display_name": "Downstairs lights", "kind": "group_action"},
            {"capability_id": "cap-light-b", "display_name": "Bedroom light"},
        ),
        route_id="traditional",
        complexity=Complexity.COMPLEX,
        reason="Jev could not complete the request",
        allowed_response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
        handoff_depth=depth,
        route_policy_revision="routes-1",
    )


class _Response:
    def __init__(self, value: dict) -> None:
        self.value = value

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.value).encode()


def test_sends_offered_choices_with_strict_no_tools_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({"choices": [{"message": {"content": '{"kind":"tool_proposal","choice":"cap-light-a","text":"","reason":"matched"}'}}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = OpenRouterFallbackAdapter(endpoint="https://openrouter.ai/api/v1/chat/completions").invoke(None, _request())
    assert result["proposals"][0]["capability_id"] == "cap-light-a"
    assert captured["body"]["stream"] is False
    assert "tools" not in captured["body"]
    assert captured["body"]["max_tokens"] <= 512


def test_openai_compatible_fallback_can_return_bounded_typed_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    request = replace(
        _request(),
        relevant_facts=({
            "capability_id": "cap-light-a",
            "display_name": "Downstairs lights",
            "parameter_schema": {
                "required": ["brightness"],
                "properties": {"brightness": {"type": "number", "minimum": 0, "maximum": 100}},
            },
        },),
    )

    def urlopen(request_obj, timeout):
        body = json.loads(request_obj.data)
        choice = body["messages"][1]["content"]
        assert "brightness" in choice
        return _Response({"choices": [{"message": {"content": (
            '{"kind":"tool_proposal","choice":"cap-light-a","text":"",'
            '"reason":"matched","parameters":{"brightness":42}}'
        )}}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = OpenRouterFallbackAdapter().invoke(None, request)

    assert result["proposals"][0]["parameters"] == {"brightness": 42}


def test_openai_compatible_fallback_retries_without_optional_schema_on_http_400(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def urlopen(request_obj, timeout):
        payload = json.loads(request_obj.data)
        calls.append(payload)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request_obj.full_url, 400, "unsupported response format", {}, None)
        assert "response_format" not in payload
        return _Response({"choices": [{"message": {"content": (
            "```json\n"
            '{"kind":"tool_proposal","choice":"cap-light-a","text":"",'
            '"reason":"matched","parameters":{}}\n'
            "```"
        )}}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = OpenRouterFallbackAdapter().invoke(None, _request())

    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert result["proposals"][0]["capability_id"] == "cap-light-a"


def test_openai_compatible_fallback_normalizes_echoed_choice_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({"choices": [{"message": {"content": json.dumps({
            "kind": "tool_proposal",
            "choice": {"capability_id": "cap-light-a", "name": "echoed metadata"},
            "text": None,
            "reason": "matched",
            "parameters": {},
        })}}]}),
    )

    result = OpenRouterFallbackAdapter().invoke(None, _request())

    assert result["proposals"][0]["capability_id"] == "cap-light-a"


def test_openai_compatible_fallback_discards_bounded_proposal_explanation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({"choices": [{"message": {"content": json.dumps({
            "kind": "tool_proposal",
            "choice": "cap-light-a",
            "text": "I found the offered light capability.",
            "reason": "matched",
            "parameters": {},
        })}}]}),
    )

    result = OpenRouterFallbackAdapter().invoke(None, _request())

    assert result["proposals"][0]["capability_id"] == "cap-light-a"
    assert "text" not in result["proposals"][0]


def test_prose_response_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({"choices": [{"message": {"content": '{"kind":"prose_response","choice":null,"text":"Please specify a room.","reason":"ambiguous"}'}}]}),
    )
    result = OpenRouterFallbackAdapter().invoke(None, _request())
    assert result["text"] == "Please specify a room."


def test_unknown_choice_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({"choices": [{"message": {"content": '{"kind":"tool_proposal","choice":"light.secret","text":"","reason":"bad"}'}}]}),
    )
    with pytest.raises(OpenRouterFallbackInvalidResponse):
        OpenRouterFallbackAdapter().invoke(None, _request())


def test_raw_reference_is_rejected_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: pytest.fail("must not call provider"))
    request = replace(
        _request(),
        relevant_facts=({"capability_id": "cap-light-a", "entity_id": "fixture.light"},),
    )
    with pytest.raises(OpenRouterFallbackInvalidResponse, match="not sanitized"):
        OpenRouterFallbackAdapter().invoke(None, request)


def test_transient_failures_are_bounded_and_non_retryable_http_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def timeout(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError()

    monkeypatch.setattr("urllib.request.urlopen", timeout)
    monkeypatch.setattr("ha_switchboard.openrouter_fallback.time.sleep", lambda _delay: None)
    with pytest.raises(OpenRouterFallbackUnavailable):
        OpenRouterFallbackAdapter().invoke(None, _request())
    assert calls == 3

    calls = 0

    def unauthorized(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError("https://provider.invalid", 401, "unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", unauthorized)
    with pytest.raises(OpenRouterFallbackUnavailable):
        OpenRouterFallbackAdapter().invoke(None, _request(handoff_id="handoff-unauthorized"))
    assert calls == 1


def test_repeated_handoff_and_non_https_are_rejected() -> None:
    with pytest.raises(ValueError):
        OpenRouterFallbackAdapter(endpoint="http://openrouter.ai/api/v1/chat/completions")
    adapter = OpenRouterFallbackAdapter()
    with pytest.raises(ValueError):
        adapter.invoke(None, _request(depth=2))


def test_provider_error_log_contains_only_structured_safe_fields(monkeypatch, caplog) -> None:
    def fail(*_args, **_kwargs):
        raise TimeoutError("utterance and secret must not be logged")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    caplog.set_level("WARNING", logger="ha_switchboard.openrouter")

    with pytest.raises(OpenRouterFallbackUnavailable):
        OpenRouterFallbackAdapter().invoke(None, _request())

    assert "event=provider_transport_error" in caplog.text
    assert "utterance" not in caplog.text
    assert "secret" not in caplog.text
