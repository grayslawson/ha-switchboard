from __future__ import annotations

from custom_components.ha_switchboard.diagnostics import CoreDiagnosticLog, safe_exception_code


def test_core_diagnostics_are_bounded_and_redact_sensitive_or_raw_values() -> None:
    log = CoreDiagnosticLog(retention=2)
    event = log.record(
        "conversation_failed",
        correlation_id="request-one",
        entity_id="light.secret",
        gateway_token="do-not-store",
        summary="safe summary",
        nested={"authorization": "bearer secret", "count": 1},
    )

    payload = event.to_dict()
    assert payload["correlation_id"] == "request-one"
    assert payload["fields"]["entity_id"] == "[core-local]"
    assert payload["fields"]["gateway_token"] == "[redacted]"
    assert payload["fields"]["nested"]["authorization"] == "[redacted]"
    assert "light.secret" not in repr(payload)
    assert "do-not-store" not in repr(payload)


def test_core_exception_mapping_never_uses_exception_text() -> None:
    gateway_error = type("GatewayClientError", (RuntimeError,), {})
    assert safe_exception_code(gateway_error("https://secret.example/token")) == "gateway_unavailable"
    assert safe_exception_code(TimeoutError("provider response")) == "gateway_timeout"
    assert safe_exception_code(ValueError("entity_id=light.private")) == "invalid_request"
    assert safe_exception_code(RuntimeError("private response body")) == "core_error"


def test_core_diagnostics_retain_only_the_bounded_tail() -> None:
    log = CoreDiagnosticLog(retention=2)
    log.record("first")
    log.record("second")
    log.record_exception(RuntimeError("ignored"), correlation_id="third")

    events = log.list(limit=100)
    assert len(events) == 2
    assert [event["code"] for event in events] == ["second", "core_error"]
