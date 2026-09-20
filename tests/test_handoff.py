from __future__ import annotations

from dataclasses import replace

import pytest

from ha_switchboard.handoff import HandoffBroker, HandoffInvalidResponse, validate_response
from ha_switchboard.protocol import Complexity, HandoffRequest, ModelRoute, PrivacyMode, ResponseKind
from ha_switchboard.route_policy import RouteRegistry


def _request() -> HandoffRequest:
    return HandoffRequest(
        handoff_id="handoff-fixture",
        request_id="request-fixture",
        conversation_id="conversation-fixture",
        utterance="What should I do?",
        bounded_context=(),
        relevant_facts=(),
        route_id="local-reasoner",
        complexity=Complexity.REASONING,
        reason="open ended",
        allowed_response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
        handoff_depth=1,
        route_policy_revision="routes-fixture-1",
    )


def test_bounded_prose_is_accepted() -> None:
    result = validate_response(
        {"kind": "prose_response", "handoff_id": "handoff-fixture", "text": "A bounded answer."},
        _request(),
    )
    assert result.text == "A bounded answer."


def test_raw_service_json_is_rejected() -> None:
    with pytest.raises(HandoffInvalidResponse):
        validate_response(
            {
                "kind": "tool_proposal",
                "handoff_id": "handoff-fixture",
                "service": "light.turn_on",
                "service_data": {"entity_id": "light.secret"},
            },
            _request(),
        )


def test_typed_proposal_is_bounded() -> None:
    result = validate_response(
        {
            "kind": "tool_proposal",
            "handoff_id": "handoff-fixture",
            "proposals": [{"capability_id": "cap-opaque", "parameter_refs": [], "reason": "routine"}],
        },
        _request(),
    )
    assert result.proposals[0]["capability_id"] == "cap-opaque"


def test_typed_parameters_are_checked_against_offered_capability() -> None:
    request = replace(
        _request(),
        relevant_facts=({"capability_id": "cap-opaque", "parameter_schema": {"properties": {"brightness": {"type": "number"}}}},),
    )
    result = validate_response(
        {"kind": "tool_proposal", "handoff_id": request.handoff_id,
         "proposals": [{"capability_id": "cap-opaque", "parameter_refs": [], "parameters": {"brightness": 50}}]}, request,
    )
    assert result.proposals[0]["parameters"] == {"brightness": 50}
    with pytest.raises(HandoffInvalidResponse):
        validate_response(
            {"kind": "tool_proposal", "handoff_id": request.handoff_id,
             "proposals": [{"capability_id": "cap-opaque", "parameter_refs": [], "parameters": {"entity_id": "light.secret"}}]}, request,
        )


def test_route_identity_and_depth_are_fail_closed() -> None:
    with pytest.raises(HandoffInvalidResponse):
        validate_response({"kind": "prose_response", "handoff_id": "handoff-fixture", "route_id": "other", "text": "x"}, _request())
    with pytest.raises(HandoffInvalidResponse):
        validate_response({"kind": "prose_response", "handoff_id": "handoff-fixture", "handoff_depth": 2, "text": "x"}, _request())


def test_invalid_primary_response_fails_over_in_declared_order() -> None:
    registry = RouteRegistry((
        ModelRoute("primary", "typed", (ResponseKind.PROSE_RESPONSE,), Complexity.REASONING, (PrivacyMode.LOCAL_ONLY,), 100, 0, fallback_route_ids=("secondary",)),
        ModelRoute("secondary", "typed", (ResponseKind.PROSE_RESPONSE,), Complexity.REASONING, (PrivacyMode.LOCAL_ONLY,), 100, 0),
    ))

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def invoke(self, route, request):
            self.calls.append(route.route_id)
            if route.route_id == "primary":
                return {"handoff_id": request.handoff_id, "kind": "prose_response", "text": ""}
            return {"handoff_id": request.handoff_id, "kind": "prose_response", "text": "secondary answer"}

    adapter = Adapter()
    request = replace(_request(), route_id="primary", privacy_mode=PrivacyMode.LOCAL_ONLY)
    response = HandoffBroker(registry, adapter).dispatch(request)
    assert response.text == "secondary answer"
    assert adapter.calls == ["primary", "secondary"]
