from __future__ import annotations

from ha_switchboard.web import dashboard_html


def html() -> str:
    return dashboard_html().decode("utf-8")


def test_dashboard_covers_status_scan_provider_and_recovery_surfaces() -> None:
    page = html()

    for phrase in (
        "Liveness",
        "Readiness",
        "Profile state",
        "Scan Home Assistant now",
        "Provider state",
        "Configure Assist",
        "Configuration and recovery",
    ):
        assert phrase in page
    for endpoint in (
        "healthz",
        "readyz",
        "v1/profile/status",
        "v1/app/status",
        "v1/profile/scan",
        "v1/provider/status",
    ):
        assert endpoint in page


def test_dashboard_uses_bounded_scan_polling_and_accessible_states() -> None:
    page = html()

    assert "MAX_POLLS=20" in page
    assert "POLL_MS=1500" in page
    assert "aria-live=\"polite\"" in page
    assert 'type="button"' in page
    assert "prefers-reduced-motion:reduce" in page
    assert "scanPolls++>=MAX_POLLS" in page
    assert "Scan status polling timed out" in page


def test_browser_payload_is_secret_safe_and_dom_text_only() -> None:
    page = html()

    for secret in ("JEV_API_KEY", "FALLBACK_API_KEY", "gateway_token", "Authorization"):
        assert secret not in page
    assert "innerHTML" not in page
    assert "textContent" in page
    assert "raw utterances" in page
    assert "entity_id" not in page


def test_status_rendering_tolerates_missing_new_optional_endpoints() -> None:
    page = html()

    # Provider and diagnostics routes are optional during rollout. The page
    # must show a bounded unavailable message rather than throw raw JSON.
    assert "compatibility unverified" in page
    assert "Diagnostics are not available from this App version" in page
    assert "Some status endpoints are unavailable" in page
