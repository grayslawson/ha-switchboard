from __future__ import annotations

import json
import logging
from io import BytesIO
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest

from ha_switchboard.gateway import Gateway
from ha_switchboard.jev_client import JevError
from ha_switchboard.limits import REQUEST_READ_TIMEOUT
from ha_switchboard.server import (
    GatewayHandler,
    _prepare_data_dir_and_drop_privileges,
    _load_options,
    _retry_supervisor_discovery,
    build_gateway,
    safe_app_status,
)
from ha_switchboard.store import ProfileStore
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


def _post_handler(*, gateway, path: str, payload: dict[str, object], source: str = "172.30.32.2"):
    raw = json.dumps(payload).encode("utf-8")
    handler = object.__new__(GatewayHandler)
    handler.client_address = (source, 12345)
    handler.command = "POST"
    handler.path = path
    handler.headers = {
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
    }
    handler.rfile = BytesIO(raw)
    handler.gateway = gateway
    handler.ingress_only = True
    handler.rate_limiter = SimpleNamespace(allow=lambda _source: True)
    writes: list[tuple[int, object]] = []
    handler._write = lambda status, response: writes.append((status, response))
    return handler, writes


def _clear_runtime_options(monkeypatch) -> None:
    for name in (
        "FALLBACK_API_KEY",
        "FALLBACK_BASE_URL",
        "FALLBACK_ENDPOINT",
        "FALLBACK_MODEL",
        "FALLBACK_PROVIDER",
        "GATEWAY_TOKEN",
        "JEV_API_KEY",
        "JEV_BASE_URL",
        "JEV_ENDPOINT",
        "JEV_MODEL",
        "JEV_PROVIDER",
        "JEV_ROUTE_REGISTRY",
        "PRIVACY_MODE",
        "SUPERVISOR",
        "SUPERVISOR_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


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


def test_missing_options_falls_back_to_empty_standalone_options(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    assert _load_options(str(tmp_path)) == {}


def test_empty_options_builds_safe_degraded_gateway(monkeypatch, tmp_path) -> None:
    _clear_runtime_options(monkeypatch)
    (tmp_path / "options.json").write_text("{}", encoding="utf-8")

    gateway = build_gateway(str(tmp_path))

    provider = gateway.provider_status()
    assert provider["configured_count"] == 0
    assert provider["providers"]["jev"]["status"] == "disabled"
    assert gateway.ready()["degraded_reasons"] == ["profile_not_current", "provider_not_configured"]
    status = safe_app_status({}, ingress_only=True, gateway=gateway)
    assert status["gateway_mode"] == "adapter_only"
    assert status["privacy_mode"] == "local_only"
    assert status["auth_configured"] is False
    assert gateway.diagnostics_page(event_type="provider_not_configured")["total"] == 1


def test_provider_outage_endpoint_returns_bounded_redacted_status(tmp_path) -> None:
    class UnavailableJev:
        hosted = False

        def decide(self, _request):
            raise JevError("fixture-provider-secret https://provider.example.invalid/response")

    gateway = Gateway(store=ProfileStore(tmp_path), jev=UnavailableJev())
    handler, writes = _post_handler(
        gateway=gateway,
        path="/v1/provider/compatibility",
        payload={"probe": True},
    )

    handler.do_POST()

    assert writes == [
        (
            200,
            {
                "status": "incompatible",
                "providers": {
                    "jev": {"status": "unavailable", "error_code": "jev_unavailable"},
                    "fallback": {"status": "not_configured", "routes": []},
                },
            },
        )
    ]
    assert "fixture-provider-secret" not in repr(writes)
    assert "provider.example.invalid" not in repr(writes)


def test_provider_handler_errors_return_safe_response_and_redacted_log(caplog) -> None:
    def fail_provider(**_kwargs):
        raise RuntimeError("fixture-provider-secret https://provider.example.invalid/details")

    handler, writes = _post_handler(
        gateway=SimpleNamespace(provider_compatibility=fail_provider),
        path="/v1/provider/compatibility",
        payload={"probe": True},
    )

    with caplog.at_level(logging.ERROR, logger="ha_switchboard"):
        handler.do_POST()

    assert writes == [(500, {"error": {"code": "internal_error"}})]
    assert "event=internal_error" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "fixture-provider-secret" not in caplog.text
    assert "provider.example.invalid" not in caplog.text


def test_gateway_token_rotation_invalidates_old_token_and_accepts_new_token() -> None:
    handler, writes = _handler(
        source="10.0.0.20",
        ingress_only=False,
        token="old-gateway-token",
        supplied="Bearer old-gateway-token",
    )

    assert handler._authorized() is True
    handler.gateway.gateway_token = "new-gateway-token"
    handler.headers = {"Authorization": "Bearer old-gateway-token"}
    assert handler._authorized() is False
    assert writes == [(401, {"error": {"code": "unauthorized"}})]

    writes.clear()
    handler.headers = {"Authorization": "Bearer new-gateway-token"}
    assert handler._authorized() is True
    assert writes == []


def test_server_restart_migrates_legacy_profile_and_restores_it_stale(monkeypatch, tmp_path, sanitized_discovery) -> None:
    _clear_runtime_options(monkeypatch)
    (tmp_path / "options.json").write_text(
        json.dumps({"gateway_mode": "supervisor_read_only"}),
        encoding="utf-8",
    )
    initial = build_gateway(str(tmp_path))
    initial.reconcile(sanitized_discovery)
    profile = initial.store.load_profile()
    assert profile is not None
    initial.store.profile_path.write_text(json.dumps(profile), encoding="utf-8")

    restarted = build_gateway(str(tmp_path))

    assert restarted.active_profile is not None
    assert restarted.active_profile.revision == initial.active_profile.revision
    assert restarted.profile_status()["status"] == "stale"
    assert restarted.ready()["status"] == "degraded"
    assert "profile_not_current" in restarted.ready()["degraded_reasons"]
    assert restarted.configuration_warnings == ("supervisor_read_only_migrated_to_adapter_only",)
    assert json.loads(initial.store.profile_path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_supervisor_options_request_uses_bounded_timeout(monkeypatch) -> None:
    from ha_switchboard import server

    monkeypatch.setenv("SUPERVISOR", "http://supervisor")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "fixture-supervisor-token")
    seen: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"data":{"options":{"gateway_mode":"adapter_only"}}}'

    def fake_urlopen(request, *, timeout):
        seen.update(url=request.full_url, authorization=request.headers["Authorization"], timeout=timeout)
        return Response()

    monkeypatch.setattr(server, "urlopen", fake_urlopen)

    assert server._load_supervisor_options() == {"gateway_mode": "adapter_only"}
    assert seen == {
        "url": "http://supervisor/addons/self/info",
        "authorization": "Bearer fixture-supervisor-token",
        "timeout": 2.0,
    }


def test_handler_setup_applies_bounded_request_read_timeout(monkeypatch) -> None:
    calls: list[float] = []
    connection = SimpleNamespace(settimeout=calls.append)
    monkeypatch.setattr(
        BaseHTTPRequestHandler,
        "setup",
        lambda handler: setattr(handler, "connection", connection),
    )

    GatewayHandler.setup(object.__new__(GatewayHandler))

    assert calls == [REQUEST_READ_TIMEOUT]


def test_configuration_diagnostics_log_only_safe_warning_codes(monkeypatch, tmp_path, caplog) -> None:
    _clear_runtime_options(monkeypatch)
    (tmp_path / "options.json").write_text(
        json.dumps({"jev_endpoint": "https://user:fixture-password@provider.example.invalid/decide"}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="ha_switchboard"):
        gateway = build_gateway(str(tmp_path))

    assert gateway.configuration_warnings == ("invalid_jev_endpoint",)
    assert "configuration_degraded" in caplog.text
    assert "invalid_jev_endpoint" in caplog.text
    assert "fixture-password" not in caplog.text
    assert "provider.example.invalid" not in caplog.text
    diagnostics = gateway.diagnostics_page(event_type="configuration_warning")
    assert "fixture-password" not in repr(diagnostics)
    assert "provider.example.invalid" not in repr(diagnostics)


def test_supervisor_discovery_retry_is_bounded(monkeypatch, caplog) -> None:
    from ha_switchboard import server

    attempts: list[int] = []
    monkeypatch.setattr(
        server,
        "register_supervisor_discovery",
        lambda **_kwargs: attempts.append(1) or False,
    )

    caplog.set_level(logging.WARNING, logger="ha_switchboard")
    assert _retry_supervisor_discovery(
        8099,
        "gateway-secret",
        attempts=3,
        delay_seconds=0,
    ) is False

    assert len(attempts) == 3
    assert "event=supervisor_discovery_failed attempts=3" in caplog.text


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
        "version": __import__("ha_switchboard").__version__,
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


def test_provider_status_route_returns_redacted_provider_state() -> None:
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("172.30.32.2", 12345)
    handler.path = "/v1/provider/status"
    handler.headers = {}
    handler.gateway = SimpleNamespace(
        provider_status=lambda: {"providers": {"jev": {"status": "configured"}}}
    )
    writes: list[tuple[int, object]] = []
    handler._write = lambda status, payload: writes.append((status, payload))

    handler.do_GET()

    assert writes == [(200, {"providers": {"jev": {"status": "configured"}}})]


def test_diagnostics_route_passes_bounded_filters_to_gateway() -> None:
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("172.30.32.2", 12345)
    handler.path = "/v1/diagnostics?page=2&limit=10&level=error&event_type=provider_failed"
    handler.headers = {}
    received: dict[str, object] = {}

    def diagnostics_page(**filters):
        received.update(filters)
        return {"events": [], "page": 2, "limit": 10, "total": 0, "has_more": False}

    handler.gateway = SimpleNamespace(diagnostics_page=diagnostics_page)
    writes: list[tuple[int, object]] = []
    handler._write = lambda status, payload: writes.append((status, payload))

    handler.do_GET()

    assert received == {
        "page": 2,
        "limit": 10,
        "level": "error",
        "event_type": "provider_failed",
        "correlation_id": None,
        "route_class": None,
        "outcome": None,
    }
    assert writes[0][0] == 200


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


@pytest.mark.parametrize("writer_error", [BrokenPipeError, ConnectionAbortedError, ConnectionResetError])
def test_response_disconnects_are_bounded_and_not_internal_errors(writer_error, caplog) -> None:
    handler = object.__new__(GatewayHandler)
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None
    handler.wfile = SimpleNamespace(write=lambda _value: (_ for _ in ()).throw(writer_error()))

    with caplog.at_level(logging.DEBUG, logger="ha_switchboard"):
        handler._write(200, {"status": "ok"})

    assert "event=response_client_disconnected content_type=json" in caplog.text


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
