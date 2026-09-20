from __future__ import annotations

import pytest

from ha_switchboard.handoff import HandoffInvalidResponse, validate_response
from ha_switchboard.protocol import Complexity, HandoffRequest, ResponseKind


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
