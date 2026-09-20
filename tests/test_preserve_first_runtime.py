from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tools" / "local-fixtures"


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, FIXTURE / "local_api.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lifecycle_report() -> dict:
    return {
        "config_entry": {
            "domain": "ha_switchboard",
            "source": "hassio",
            "version": 1,
            "has_gateway_token": True,
        },
        "core": {
            "fixture_entity_count": 28,
            "conversation_agent_present": True,
        },
        "gateway": {
            "status": "active",
            "capability_count": 28,
            "has_revision": True,
            "pending_section_count": 0,
            "pending_invalidation_count": 0,
        },
    }


def test_startup_inspection_is_read_only_and_returns_only_safe_evidence(monkeypatch) -> None:
    api = load_module("local_fixture_api_startup_read_only")

    def fail_if_host_command_is_called(*args, **kwargs):
        raise AssertionError("startup inspection must not issue a host command")

    monkeypatch.setattr(api, "run_host_command", fail_if_host_command_is_called)
    monkeypatch.setattr(
        api,
        "inspect_local_supervisor",
        lambda: {
            "container": "busy_cohen",
            "supervisor_port": 7123,
            "supervisor_volume_verified": True,
            "volume_identity_verified": True,
            "volume_identity_fingerprint": "0123456789abcdef",
        },
    )
    monkeypatch.setattr(
        api,
        "read_local_app_options",
        lambda: (
            {"options_present": True, "app_started": True, "configured_fields": {"gateway_token": True}},
            {"gateway_token": "opaque-in-memory-test-value"},
        ),
    )
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: lifecycle_report())

    result = api.startup_check()

    assert result["command"] == "startup"
    assert result["mode"] == "read_only"
    assert result["ready"] is True
    assert result["lifecycle"] == lifecycle_report()
    assert result["options"]["options_present"] is True
    assert "opaque-in-memory-test-value" not in repr(result)


def test_startup_readiness_requires_started_app_and_verified_volume(monkeypatch) -> None:
    api = load_module("local_fixture_api_startup_guard")
    monkeypatch.setattr(api, "inspect_local_supervisor", lambda: {
        "container": "busy_cohen",
        "supervisor_port": 7123,
        "supervisor_volume_verified": True,
        "volume_identity_verified": True,
        "volume_identity_fingerprint": "0123456789abcdef",
    })
    monkeypatch.setattr(api, "read_local_app_options", lambda: (
        {"options_present": True, "app_started": False, "configured_fields": {}},
        {},
    ))
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: lifecycle_report())

    with pytest.raises(RuntimeError, match="startup evidence is incomplete"):
        api.startup_check()


class _FakeSession:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeAiohttp:
    ClientSession = _FakeSession

    @staticmethod
    def ClientTimeout(**kwargs):
        return kwargs


def test_scan_inspection_is_bounded_profile_only_and_never_runs_host_lifecycle_commands(
    monkeypatch, capsys
) -> None:
    api = load_module("local_fixture_api_scan_read_only")
    requests: list[tuple[str, str, dict | None]] = []
    statuses = iter(
        [
            (
                200,
                {
                    "status": "active",
                    "profile_revision": "safe",
                    "capability_count": 1,
                    "monitor": {"pending_sections": [], "pending_invalidations": []},
                },
            ),
            (202, {}),
            (
                200,
                {
                    "status": "active",
                    "profile_revision": "safe",
                    "capability_count": 1,
                    "monitor": {"pending_sections": [], "pending_invalidations": []},
                },
            ),
        ]
    )

    async def fake_gateway_request(session, url, token, method, path, payload=None, **kwargs):
        requests.append((method, path, payload))
        return next(statuses)

    def fail_if_host_command_is_called(*args, **kwargs):
        raise AssertionError("scan inspection must not issue a host command")

    class _ConfigPath:
        def __init__(self, path: str) -> None:
            self.path = path

        def read_text(self, encoding: str) -> str:
            return json.dumps(
                {
                    "data": {
                        "entries": [
                            {
                                "domain": "ha_switchboard",
                                "source": "hassio",
                                "version": 1,
                                "data": {
                                    "gateway_url": "http://127.0.0.1:8099",
                                    "gateway_token": "opaque-token",
                                },
                            }
                        ]
                    }
                }
            )

    monkeypatch.setitem(sys.modules, "aiohttp", _FakeAiohttp)
    monkeypatch.setattr(api, "Path", _ConfigPath)
    monkeypatch.setattr(api, "temporary_token", lambda: "opaque-core-token")
    monkeypatch.setattr(api, "gateway_config", lambda entries: ("http://127.0.0.1:8099", "opaque-token"))
    monkeypatch.setattr(api, "gateway_request", fake_gateway_request)
    monkeypatch.setattr(api, "run_host_command", fail_if_host_command_is_called)
    original_sleep = asyncio.sleep
    monkeypatch.setattr(api.asyncio, "sleep", lambda delay: original_sleep(0))

    asyncio.run(api.main("scan"))

    assert requests == [
        ("GET", "/v1/profile/status", None),
        ("POST", "/v1/profile/scan", {}),
        ("GET", "/v1/profile/status", None),
    ]
    output = capsys.readouterr().out
    assert '"completion": "settled"' in output
    assert "opaque-token" not in output
    assert "127.0.0.1" not in output
