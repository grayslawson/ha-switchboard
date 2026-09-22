from __future__ import annotations

import pytest

from ha_switchboard.contracts import error_envelope, validate_decision_payload
from ha_switchboard.diagnostics import DiagnosticLog


def test_decision_contract_rejects_unknown_and_oversized_fields() -> None:
    base = {
        "request_id": "r1", "conversation_id": "c1", "utterance": "hello",
        "language": "en", "profile_revision": "p1", "policy_revision": "policy-1",
    }
    with pytest.raises(ValueError):
        validate_decision_payload({**base, "unexpected": True})
    with pytest.raises(ValueError):
        validate_decision_payload({**base, "utterance": "x" * 2_001})


def test_error_envelope_has_no_exception_or_secret_detail() -> None:
    assert error_envelope("not-a-public-code") == {"error": {"code": "internal_error"}}


def test_diagnostics_are_bounded_and_reject_secrets() -> None:
    log = DiagnosticLog(retention=2)
    log.record("one", route="local")
    log.record("two", route="local")
    log.record("three", route="local")
    assert [item["code"] for item in log.list()] == ["two", "three"]
    with pytest.raises(ValueError):
        log.record("secret", api_key="never")


def test_diagnostics_query_filters_and_paginates_without_raw_references() -> None:
    log = DiagnosticLog(retention=8)
    log.record("profile_reconciled", level="info", route_class="jev", outcome="active", summary="Profile ready")
    log.record("provider_failed", level="error", route_class="fallback", outcome="unavailable", summary="Provider unavailable")
    log.record("conversation_result", level="warning", route_class="fallback", outcome="clarification_required")

    page = log.query(page=1, limit=1, level="error", route_class="fallback")

    assert page["total"] == 1
    assert page["has_more"] is False
    assert page["events"][0]["event_type"] == "provider_failed"
    assert page["events"][0]["summary"] == "Provider unavailable"
    with pytest.raises(ValueError):
        log.record("raw_reference", entity_id="light.secret")
