from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from ha_switchboard.gateway import Gateway
from ha_switchboard.handoff import HandoffBroker, StaticRouteAdapter
from ha_switchboard.jev_client import JevError, StaticJevClient
from ha_switchboard.protocol import Complexity, JevDecision, RouteKind
from ha_switchboard.route_policy import RouteRegistry
from ha_switchboard.server import GatewayHandler, RequestError, build_gateway, safe_app_status
from ha_switchboard.store import ProfileStore


class FlakyJev:
    hosted = False

    def __init__(self) -> None:
        self.available = False

    def decide(self, _request):
        if not self.available:
            raise JevError("provider unavailable")
        return JevDecision(RouteKind.REFUSE, Complexity.SIMPLE, reason="recovered")


def _request(gateway: Gateway, request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "conversation_id": "resilience-test",
        "utterance": "what can you do",
        "language": "en",
        "profile_revision": gateway.active_profile.revision,
        "policy_revision": "policy-1",
        "candidates": [],
        "bounded_context": [],
        "sanitized_state": {},
    }


def test_provider_outage_is_degraded_and_recovery_is_observable(tmp_path, sanitized_discovery) -> None:
    jev = FlakyJev()
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=jev,
        handoff=HandoffBroker(RouteRegistry(), StaticRouteAdapter({})),
    )
    gateway.reconcile(sanitized_discovery)

    failed = gateway.process(_request(gateway, "outage"))
    assert failed.response_key == "jev_unavailable"
    assert gateway.ready()["status"] == "degraded"
    assert gateway.provider_status()["providers"]["jev"]["status"] == "unavailable"
    assert gateway.diagnostics_page(event_type="provider_failed")["total"] == 1

    jev.available = True
    recovered = gateway.process(_request(gateway, "recovery"))
    assert recovered.response_key == "request_refused"
    assert gateway.provider_status()["providers"]["jev"]["status"] == "healthy"
    assert gateway.diagnostics_page(event_type="provider_recovered")["total"] == 1


def test_restart_corrupt_profile_fails_closed_without_crashing(tmp_path) -> None:
    store = ProfileStore(tmp_path)
    store.profile_path.write_text("{not-json", encoding="utf-8")

    gateway = Gateway(store=store, jev=StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE)))

    assert gateway.active_profile is None
    assert gateway.ready()["status"] == "degraded"
    assert gateway.diagnostics_page(event_type="profile_restore_failed")["total"] == 1


def test_token_rotation_preserves_last_valid_profile(tmp_path, sanitized_discovery) -> None:
    first = Gateway(store=ProfileStore(tmp_path), jev=StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE)))
    first.reconcile(sanitized_discovery)
    revision = first.active_profile.revision

    restarted = Gateway(store=ProfileStore(tmp_path), jev=StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE)))
    restarted.gateway_token = "rotated-token"

    assert restarted.active_profile is not None
    assert restarted.active_profile.revision == revision
    assert restarted.gateway_token == "rotated-token"
    assert restarted.process(_request(restarted, "after-rotation")).response_key == "profile_reconciling"


def test_empty_and_invalid_provider_options_degrade_without_provider_contact(monkeypatch, tmp_path) -> None:
    for name in ("JEV_ENDPOINT", "JEV_API_KEY", "FALLBACK_PROVIDER", "FALLBACK_ENDPOINT", "FALLBACK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("ha_switchboard.server._load_options", lambda _path: {
        "fallback_provider": "unsupported-provider",
        "jev_endpoint": "https://user:password@example.invalid/decide",
        "privacy_mode": "not-a-mode",
    })

    gateway = build_gateway(str(tmp_path))
    status = gateway.provider_status()
    assert status["configured_count"] == 0
    assert gateway.ready()["status"] == "degraded"
    assert set(gateway.configuration_warnings) == {
        "invalid_fallback_provider", "invalid_jev_endpoint", "invalid_privacy_mode",
    }
    assert gateway.diagnostics_page(event_type="configuration_warning")["total"] == 3
    assert gateway.diagnostics_page(event_type="provider_not_configured")["total"] == 1
    assert "password" not in repr(status)


def test_legacy_supervisor_mode_is_migrated_and_warned(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("ha_switchboard.server._load_options", lambda _path: {
        "gateway_mode": "supervisor_read_only",
    })
    gateway = build_gateway(str(tmp_path))
    assert gateway.configuration_warnings == ("supervisor_read_only_migrated_to_adapter_only",)
    status = safe_app_status(
        {"gateway_mode": "adapter_only", "migration_warning": "supervisor_read_only_migrated_to_adapter_only"},
        ingress_only=True,
        gateway=gateway,
    )
    assert status["configuration_warnings"] == ["supervisor_read_only_migrated_to_adapter_only"]


def test_request_limits_and_media_type_have_stable_safe_errors() -> None:
    oversized = object.__new__(GatewayHandler)
    oversized.headers = {"Content-Length": "64001", "Content-Type": "application/json"}
    oversized.rfile = BytesIO()
    with pytest.raises(RequestError, match="request_too_large"):
        oversized._read_json()

    wrong_type = object.__new__(GatewayHandler)
    wrong_type.command = "POST"
    wrong_type.headers = {"Content-Length": "2", "Content-Type": "text/plain"}
    wrong_type.rfile = BytesIO(b"{}")
    with pytest.raises(RequestError, match="unsupported_media_type"):
        wrong_type._read_json()


def test_safe_status_tolerates_empty_and_malformed_refresh_option() -> None:
    status = safe_app_status(
        {"profile_refresh_minutes": "not-a-number", "gateway_mode": None, "privacy_mode": None},
        ingress_only=True,
        gateway=SimpleNamespace(gateway_token=""),
    )
    assert status["profile_refresh_minutes"] == 15
    assert status["gateway_mode"] == "adapter_only"
    assert status["privacy_mode"] == "local_only"
