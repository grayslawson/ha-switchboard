from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.ha_switchboard.client import GatewayClientError
from custom_components.ha_switchboard.coordinator import ProfileCoordinator
from custom_components.ha_switchboard.profile_adapter import HomeAssistantProfileAdapter
from ha_switchboard.server import GatewayHandler


class _State:
    def __init__(self, entity_id: str, state: str = "off") -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = {"friendly_name": "Fixture light", "exposed": True}


class _States:
    def __init__(self) -> None:
        self.values = {"light.fixture": _State("light.fixture")}

    def async_all(self):
        return list(self.values.values())

    def get(self, entity_id):
        return self.values.get(entity_id)


class _Services:
    def async_services(self):
        return {"light": {"turn_on": {}, "turn_off": {}, "toggle": {}}}


class _Hass:
    def __init__(self) -> None:
        self.states = _States()
        self.services = _Services()
        self.data = {}


class _ScanGateway:
    def __init__(self) -> None:
        self.scans = 0
        self.reconciles = 0
        self.revision = "fixture-profile"
        self.scan_started = asyncio.Event()
        self.release_scan = asyncio.Event()
        self.fail_scan = False

    async def health(self):
        return {"status": "ok"}

    async def app_status(self):
        return {"profile_refresh_minutes": 15}

    async def scan(self):
        self.scans += 1
        self.scan_started.set()
        if self.fail_scan:
            raise GatewayClientError("gateway unavailable")
        await self.release_scan.wait()
        return {"status": "scan_requested"}

    async def reconcile(self, _snapshot):
        self.reconciles += 1
        return {"profile_revision": self.revision}


def _scan_handler(*, supplied: str):
    invalidations = []
    handler = object.__new__(GatewayHandler)
    handler.client_address = ("192.0.2.44", 12345)
    handler.command = "POST"
    handler.path = "/v1/profile/scan"
    handler.headers = {"Authorization": supplied, "Content-Length": "2", "Content-Type": "application/json"}
    handler.gateway = SimpleNamespace(
        gateway_token="fixture-gateway-token",
        invalidate=lambda event: invalidations.append(event) or {"status": "stale"},
    )
    handler.ingress_only = False
    handler._read_json = lambda: {}
    writes = []
    handler._write = lambda status, payload: writes.append((status, payload))
    return handler, invalidations, writes


def test_manual_scan_authentication_fails_closed_and_success_is_bounded() -> None:
    denied, invalidations, writes = _scan_handler(supplied="Bearer wrong-token")
    denied.do_POST()
    assert invalidations == []
    assert writes == [(401, {"error": {"code": "unauthorized"}})]
    assert "wrong-token" not in repr(writes)

    accepted, invalidations, writes = _scan_handler(supplied="Bearer fixture-gateway-token")
    accepted.do_POST()
    assert invalidations == [{"kind": "manual_reconcile"}]
    assert writes == [(202, {"status": "scan_requested"})]
    assert "fixture-gateway-token" not in repr(writes)


def test_manual_scans_coalesce_and_expose_running_then_completed_progress() -> None:
    async def run() -> None:
        hass = _Hass()
        gateway = _ScanGateway()
        coordinator = ProfileCoordinator(
            hass, SimpleNamespace(data={}, entry_id="fixture"), gateway,
            HomeAssistantProfileAdapter(hass, "fixture"),
        )
        await coordinator.async_start()

        first = asyncio.create_task(coordinator.async_scan())
        await gateway.scan_started.wait()
        assert coordinator.status()["scan_state"] == "running"
        second = asyncio.create_task(coordinator.async_scan())
        gateway.release_scan.set()
        first_result, second_result = await asyncio.gather(first, second)

        assert gateway.scans == 1
        assert first_result["profile_revision"] == second_result["profile_revision"] == "fixture-profile"
        status = coordinator.status()
        assert status["scan_state"] == "completed"
        assert status["last_scan_result"] == "completed"
        assert status["last_scan_error"] is None
        assert coordinator.writes_allowed("fixture-profile")
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_manual_scan_failure_is_bounded_and_stale_profile_blocks_writes() -> None:
    async def run() -> None:
        hass = _Hass()
        gateway = _ScanGateway()
        gateway.release_scan.set()
        coordinator = ProfileCoordinator(
            hass, SimpleNamespace(data={}, entry_id="fixture"), gateway,
            HomeAssistantProfileAdapter(hass, "fixture"),
        )
        await coordinator.async_start()
        gateway.fail_scan = True
        with pytest.raises(GatewayClientError):
            await coordinator.async_scan()
        failed = coordinator.status()
        assert failed["scan_state"] == "failed"
        assert failed["last_scan_result"] == "failed"
        assert failed["last_scan_error"] == "GatewayClientError"
        assert coordinator.writes_allowed() is True

        coordinator._on_event({"event_type": "area_registry_updated"})
        stale = coordinator.status()
        assert stale["stale"] is True
        assert stale["generation"] > failed["generation"]
        assert coordinator.writes_allowed() is False
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_fixture_lifecycle_reports_are_secret_free() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "tools" / "local-fixtures" / "local_api.py"
    spec = importlib.util.spec_from_file_location("local_fixture_api_scan", path)
    assert spec and spec.loader
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)

    report = api.lifecycle_report(
        {"domain": "ha_switchboard", "source": "hassio", "version": 1, "has_gateway_token": True},
        {"conversation.ha_switchboard": {"state": "ready"}, "light.switchboard_fixture_light": {"state": "off"}},
        {"status": "active", "profile_revision": "sha256:fixture", "capability_count": 1, "monitor": {"pending_sections": [], "pending_invalidations": []}},
    )
    assert report["core"]["fixture_entity_count"] == 1
    assert report["core"]["conversation_agent_present"] is True
    assert api.valid_fixture_identity_fingerprint(report["core"]["fixture_identity_fingerprint"])
    assert report["gateway"]["has_revision"] is True
    assert "sha256:fixture" not in repr(report)
    assert "fixture-gateway-token" not in repr(report)
    with pytest.raises(RuntimeError, match="disposable local Switchboard host"):
        api.gateway_config([{
            "domain": "ha_switchboard",
            "data": {"gateway_url": "https://production.example.invalid", "gateway_token": "fixture-gateway-token"},
        }])
