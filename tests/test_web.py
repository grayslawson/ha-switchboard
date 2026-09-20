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
        "Profile revision",
        "Pending reason",
        "Configuration status",
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
    assert "failureMessage(error,'Diagnostics')" in page
    assert "Dashboard updated; provider status is unavailable." in page


def test_dashboard_keeps_optional_provider_failure_independent_and_classifies_failures() -> None:
    page = html()

    assert "optionalJson('v1/provider/status')" in page
    assert "Promise.all" in page
    assert "Provider status" in page
    for kind in ("unauthorized", "unavailable", "server-error", "network"):
        assert f"'{kind}'" in page
    assert "Gateway status" in page


def test_scan_requires_active_profile_with_no_pending_work() -> None:
    page = html()

    assert "profileComplete" in page
    assert "state==='active'" in page
    assert "!waits.sections.length&&!waits.invalidations.length" in page
    assert "active profile with no pending sections or invalidations" in page


def test_dashboard_humanizes_and_bounds_api_text() -> None:
    page = html()

    assert "const safeText=" in page
    assert "const humanize=" in page
    assert "textContent=format(value)" in page
    assert "humanize(item.status" in page
    assert "profile_revision" in page
    assert "configuration_warnings" in page


def test_dashboard_exposes_keyboard_landmarks_and_dynamic_announcements() -> None:
    page = html()

    for phrase in (
        'class="skip-link"',
        "main.id='dashboard-content'",
        "main.setAttribute('aria-labelledby','dashboard-title')",
        "setAttribute('aria-atomic','true')",
        "aria-busy",
        "aria-disabled",
        "setAttribute('role','log')",
        "setAttribute('aria-label','Diagnostic events')",
        "Refreshing dashboard…",
        "Loading next diagnostics page…",
    ):
        assert phrase in page


def test_dashboard_keeps_reduced_motion_and_secret_safe_accessibility_script() -> None:
    page = html()

    assert "prefers-reduced-motion:reduce" in page
    assert "new MutationObserver" in page
    assert "innerHTML" not in page
    assert "textContent=value" in page
