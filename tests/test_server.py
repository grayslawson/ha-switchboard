from __future__ import annotations

import logging
from io import BytesIO
from types import SimpleNamespace

import pytest

from ha_switchboard.server import GatewayHandler, _prepare_data_dir_and_drop_privileges, safe_app_status
from ha_switchboard.web import dashboard_html


def _handler(*, source: str, ingress_only: bool, token: str, supplied: str = ""):
    handler = object.__new__(GatewayHandler)
    handler.client_address = (source, 12345)
    handler.path = "/v1/profile/status"
    handler.headers = {"Authorization": supplied}
    handler.gateway = SimpleNamespace(gateway_token=token)
    handler.ingress_only = ingress_only
    writes: list[tuple[int, dict[str, str]]] = []
    handler._write = lambda status, payload: writes.append((status, payload))
    return handler, writes


def test_ingress_only_allows_core_api_with_matching_gateway_token() -> None:
    handler, writes = _handler(
        source="10.0.0.20",
        ingress_only=True,
        token="gateway-secret",
        supplied="Bearer gateway-secret",
    )

    assert handler._authorized() is True
    assert writes == []


def test_health_endpoints_are_safe_for_direct_health_checks() -> None:
    handler, writes = _handler(source="10.0.0.20", ingress_only=True, token="")
    handler.path = "/healthz"

    assert handler._authorized() is True
    assert writes == []


def test_server_version_comes_from_package_version() -> None:
    from ha_switchboard import __version__

    assert GatewayHandler.server_version == f"ha-switchboard/{__version__}"


def test_ingress_only_rejects_direct_api_without_token() -> None:
    handler, writes = _handler(source="10.0.0.20", ingress_only=True, token="secret")

    assert handler._authorized() is False
    assert writes == [(401, {"error": {"code": "unauthorized"}})]


def test_direct_adapter_mode_requires_gateway_token() -> None:
    handler, writes = _handler(source="10.0.0.20", ingress_only=False, token="")

    assert handler._authorized() is False
    assert writes == [(401, {"error": {"code": "gateway_token_required"}})]


def test_direct_adapter_mode_accepts_matching_gateway_token() -> None:
    handler, writes = _handler(
        source="10.0.0.20",
        ingress_only=False,
        token="gateway-secret",
        supplied="Bearer gateway-secret",
    )

    assert handler._authorized() is True
    assert writes == []


def test_ingress_source_can_use_protected_endpoints_without_gateway_token() -> None:
    handler, writes = _handler(source="172.30.32.2", ingress_only=True, token="")

    assert handler._authorized() is True
    assert writes == []


def test_ingress_rejects_cross_site_browser_mutations() -> None:
    for site in ("cross-site", "same-site"):
        handler, writes = _handler(source="172.30.32.2", ingress_only=True, token="")
        handler.command = "POST"
        handler.path = "/v1/profile/scan"
        handler.headers = {"Origin": "https://attacker.example", "Sec-Fetch-Site": site}

        assert handler._authorized() is False
        assert writes == [(403, {"error": {"code": "cross_origin_request_forbidden"}})]


def test_ingress_allows_same_origin_and_legacy_supervisor_mutations() -> None:
    same_origin, same_origin_writes = _handler(source="172.30.32.2", ingress_only=True, token="")
    same_origin.command = "POST"
    same_origin.path = "/v1/profile/scan"
    same_origin.headers = {"Origin": "https://homeassistant.example", "Sec-Fetch-Site": "same-origin"}

    legacy, legacy_writes = _handler(source="172.30.32.2", ingress_only=True, token="")
    legacy.command = "POST"
    legacy.path = "/v1/profile/scan"
    legacy.headers = {}

    assert same_origin._authorized() is True
    assert same_origin_writes == []
    assert legacy._authorized() is True
    assert legacy_writes == []


def test_dashboard_is_static_and_contains_no_runtime_secrets() -> None:
    html = dashboard_html().decode("utf-8")

    assert "HA Switchboard" in html
    assert "healthz" in html
    assert "v1/profile/status" in html
    assert "JEV_API_KEY" not in html
    assert "gateway_token" not in html
    assert "entity_id" not in html
    assert "innerHTML" not in html
    assert "Manage integration" in html
    assert "Configure Assist" in html
    assert "Scan Home Assistant now" in html
    assert "v1/profile/scan" in html


def test_safe_app_status_exposes_only_non_secret_configuration() -> None:
    gateway = SimpleNamespace(gateway_token="gateway-secret")

    status = safe_app_status(
        {
            "gateway_mode": "adapter_only",
            "privacy_mode": "local_only",
            "profile_refresh_minutes": 30,
            "jev_endpoint": "https://jev.example.invalid/private",
            "jev_api_key": "jev-secret",
        },
        ingress_only=True,
        gateway=gateway,
    )

    assert status == {
        "gateway_mode": "adapter_only",
        "ingress_only": True,
        "privacy_mode": "local_only",
        "profile_refresh_minutes": 30,
        "auth_configured": True,
        "fallback_provider": "disabled",
        "fallback_configured": False,
    }


def test_app_status_route_is_read_only_and_returns_safe_payload() -> None:
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("172.30.32.2", 12345)
    handler.path = "/v1/app/status"
    handler.headers = {}
    handler.gateway = SimpleNamespace(gateway_token="secret")
    handler.ingress_only = True
    handler.app_status = {"gateway_mode": "adapter_only", "auth_configured": True}
    writes: list[tuple[int, object]] = []
    handler._write = lambda status, payload: writes.append((status, payload))

    handler.do_GET()

    assert writes == [(200, handler.app_status)]


def test_app_status_does_not_create_a_post_configuration_endpoint() -> None:
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("172.30.32.2", 12345)
    handler.path = "/v1/app/status"
    handler.headers = {"Content-Length": "2"}
    handler.gateway = SimpleNamespace(gateway_token="secret")
    handler.ingress_only = True
    writes: list[tuple[int, object]] = []
    handler._write = lambda status, payload: writes.append((status, payload))

    handler.do_POST()

    assert writes == [(404, {"error": {"code": "not_found"}})]


def test_scan_request_invalidates_profile_for_core_reconciliation(caplog) -> None:
    caplog.set_level(logging.INFO, logger="ha_switchboard")
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("172.30.32.2", 12345)
    handler.path = "/v1/profile/scan"
    handler.headers = {"Content-Length": "2"}
    invalidations = []
    handler.gateway = SimpleNamespace(invalidate=lambda event: (invalidations.append(event), {"status": "stale"})[1])
    handler._read_json = lambda: {}
    writes = []
    handler._write = lambda status, payload: writes.append((status, payload))

    handler.do_POST()

    assert invalidations == [{"kind": "manual_reconcile"}]
    assert writes == [(202, {"status": "scan_requested"})]
    assert "event=scan_requested status=stale" in caplog.text


def test_invalid_request_does_not_echo_validation_detail() -> None:
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("172.30.32.2", 12345)
    handler.command = "POST"
    handler.path = "/v1/profile/reconcile"
    handler.headers = {"Content-Length": "2"}
    handler.gateway = SimpleNamespace(gateway_token="")
    handler.ingress_only = True
    handler._read_json = lambda: {}
    writes = []
    handler._write = lambda status, payload: writes.append((status, payload))

    handler.do_POST()

    assert writes == [(400, {"error": {"code": "invalid_request", "message": "request was invalid"}})]


def test_dashboard_route_accepts_query_string() -> None:
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("172.30.32.2", 12345)
    handler.path = "/?ingress_token=opaque"
    handler.headers = {}
    handler.gateway = SimpleNamespace(gateway_token="secret")
    handler.ingress_only = True
    writes: list[tuple[str, object]] = []
    handler.send_response = lambda status: writes.append(("status", status))
    handler.send_header = lambda name, value: writes.append((name, value))
    handler.end_headers = lambda: writes.append(("end", None))
    handler.wfile = SimpleNamespace(write=lambda value: writes.append(("body", value)))

    handler.do_GET()

    assert ("status", 200) in writes
    assert ("Cache-Control", "no-store") in writes
    body = next(value for name, value in writes if name == "body")
    assert b"Profile sections" in body


def test_default_request_log_omits_query_string(capsys) -> None:
    handler = object.__new__(GatewayHandler)
    handler.command = "GET"
    handler.path = "/?ingress_token=do-not-log"

    handler.log_message("ignored", "GET /", 200)

    captured = capsys.readouterr().out
    assert captured == ""
    assert "do-not-log" not in captured


def test_request_body_is_read_fully_in_bounded_chunks() -> None:
    handler = object.__new__(GatewayHandler)
    handler.headers = {"Content-Length": "14"}
    handler.rfile = BytesIO(b'{"value":true}')

    assert handler._read_json() == {"value": True}


def test_request_body_rejects_invalid_content_length() -> None:
    handler = object.__new__(GatewayHandler)
    handler.headers = {"Content-Length": "not-a-number"}
    handler.rfile = BytesIO()

    with pytest.raises(ValueError, match="length is invalid"):
        handler._read_json()


def test_root_startup_prepares_data_before_dropping_privileges(monkeypatch, tmp_path) -> None:
    from ha_switchboard import server

    calls = []
    monkeypatch.setattr(server.os, "geteuid", lambda: 0)
    monkeypatch.setattr(server.os, "chown", lambda *args: calls.append(("chown", args)))
    monkeypatch.setattr(server.os, "setgroups", lambda value: calls.append(("setgroups", value)))
    monkeypatch.setattr(server.os, "setgid", lambda value: calls.append(("setgid", value)))
    monkeypatch.setattr(server.os, "setuid", lambda value: calls.append(("setuid", value)))

    _prepare_data_dir_and_drop_privileges(str(tmp_path))

    assert calls == [
        ("chown", (str(tmp_path), 65532, 65532)),
        ("setgroups", []),
        ("setgid", 65532),
        ("setuid", 65532),
    ]
