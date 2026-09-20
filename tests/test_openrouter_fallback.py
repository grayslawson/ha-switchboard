from __future__ import annotations

import json

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
