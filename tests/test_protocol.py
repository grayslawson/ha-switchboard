from __future__ import annotations

import pytest

from ha_switchboard.protocol import (
    Complexity,
    DecisionRequest,
    HandoffRequest,
    ProfileChangeEvent,
    ResponseKind,
    SectionId,
)


def test_decision_request_rejects_oversized_utterance() -> None:
    with pytest.raises(ValueError):
        DecisionRequest("r", "c", "x" * 2_001, "en", "profile", "policy")


def test_handoff_must_have_one_logical_depth() -> None:
    with pytest.raises(ValueError):
        HandoffRequest(
            "h",
            "r",
            "c",
            "question",
            (),
            (),
            "route",
            Complexity.SIMPLE,
            "reason",
            (ResponseKind.PROSE_RESPONSE,),
            2,
            "routes",
        )


def test_change_event_is_bounded_and_typed() -> None:
    event = ProfileChangeEvent(
        "event-one",
        "entity_registry_updated",
        (),
        "2026-09-19T00:00:00Z",
        None,
        (SectionId.ENTITIES,),
        "coalesce-one",
    )
    assert event.sections == (SectionId.ENTITIES,)
