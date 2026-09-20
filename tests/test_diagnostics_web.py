from __future__ import annotations

from ha_switchboard.web import dashboard_html


def test_diagnostics_has_safe_filters_and_pagination_contract() -> None:
    page = dashboard_html().decode("utf-8")

    assert 'id="diagnostic-level"' in page
    assert 'id="diagnostic-kind"' in page
    assert 'aria-label="Filter diagnostics by severity"' in page
    assert 'aria-label="Filter diagnostics by event type"' in page
    assert 'id="diagnostic-route-class"' in page
    assert 'id="diagnostic-outcome"' in page
    assert 'aria-label="Filter diagnostics by route class"' in page
    assert 'aria-label="Filter diagnostics by outcome"' in page
    assert "v1/diagnostics?" in page
    assert "page:String(diagnosticPage)" in page
    assert "limit:String(PAGE_SIZE)" in page
    assert "diagnostic-prev" in page
    assert "diagnostic-next" in page


def test_diagnostics_render_redacted_summary_fields_without_markup() -> None:
    page = dashboard_html().decode("utf-8")

    assert "summary.textContent=item.summary?safeText(item.summary):humanize(item.message||item.event_type||'Diagnostic event')" in page
    assert "item.correlation_id" in page
    assert "Correlation ${safeText(item.correlation_id" in page
    assert "item.trace_id" not in page
    assert "document.createElement('article')" in page
    assert "row.append(timeNode,strong,summary,meta)" in page
    assert "No diagnostics match these filters." in page
    assert "Endpoint URLs, model credentials" in page
