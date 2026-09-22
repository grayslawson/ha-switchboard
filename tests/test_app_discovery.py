from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ha_switchboard import discovery
from ha_switchboard import server


ROOT = Path(__file__).parents[1]


class FakeResponse:
    def __init__(self, body: bytes = b'{"result":"ok"}') -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, *_args: object) -> bytes:
        return self.body


def test_app_declares_switchboard_discovery_service() -> None:
    manifest = (ROOT / "app" / "config.yaml").read_text(encoding="utf-8")

    assert "discovery: [ha_switchboard]" in manifest
    assert "hassio_api: true" in manifest
    assert "homeassistant_api: false" in manifest


def test_runtime_hostname_is_normalized_for_app_dns() -> None:
    assert discovery.normalize_app_hostname("LOCAL_ha_switchboard.") == "local-ha-switchboard"
    assert discovery.normalize_app_hostname("repo_app.v1") == "repo-app.v1"


def test_registration_posts_documented_payload_without_logging_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[tuple[str, str, bytes | None]] = []

    def opener(request, *, timeout):
        requests.append((request.full_url, request.headers["Authorization"], request.data))
        assert timeout == 1.5
        if request.full_url.endswith("/addons/self/info"):
            return FakeResponse(b'{"data":{"hostname":"local_ha_switchboard"}}')
        return FakeResponse()

    monkeypatch.setenv("HOSTNAME", "local_ha_switchboard")
    assert discovery.register_supervisor_discovery(
        port=8123,
        gateway_token="gateway-secret",
        supervisor_token="supervisor-secret",
        opener=opener,
        timeout=1.5,
        retries=1,
    ) is True

    assert len(requests) == 2
    url, authorization, body = requests[-1]
    assert url == "http://supervisor/discovery"
    assert authorization == "Bearer supervisor-secret"
    assert json.loads(body or b"") == {
        "service": "ha_switchboard",
        "config": {
            "host": "local-ha-switchboard",
            "port": 8123,
            "token": "gateway-secret",
        },
    }
    captured = capsys.readouterr()
    assert "gateway-secret" not in captured.out + captured.err
    assert "supervisor-secret" not in captured.out + captured.err


def test_registration_retries_same_payload_and_is_safe_to_repeat() -> None:
    requests: list[bytes | None] = []
    attempts = 0

    def opener(request, *, timeout):
        nonlocal attempts
        attempts += 1
        requests.append(request.data)
        if request.full_url.endswith("/addons/self/info"):
            return FakeResponse(b'{"data":{"hostname":"local_ha_switchboard"}}')
        if attempts == 1:
            raise OSError("Supervisor unavailable")
        return FakeResponse()

    assert discovery.register_supervisor_discovery(
        hostname="local_ha_switchboard",
        gateway_token="gateway-secret",
        supervisor_token="supervisor-secret",
        opener=opener,
        retries=2,
        sleeper=lambda _: None,
    ) is True

    assert attempts == 2
    assert requests[-1] == requests[-2]
    assert json.loads(requests[-1] or b"")["service"] == "ha_switchboard"


def test_standalone_mode_skips_supervisor_when_token_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    def unexpected_opener(*args, **kwargs):
        raise AssertionError("standalone discovery must not contact Supervisor")

    assert discovery.register_supervisor_discovery(opener=unexpected_opener) is False


def test_unprivileged_app_reads_options_from_supervisor_self_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    monkeypatch.delenv("SUPERVISOR", raising=False)

    def opener(request, *, timeout):
        assert request.full_url == "http://supervisor/addons/self/info"
        assert request.headers["Authorization"] == "Bearer supervisor-secret"
        assert timeout == 2.0
        return FakeResponse(
            b'{"result":"ok","data":{"options":{"gateway_token":"from-supervisor","jev_endpoint":"https://jev.example/decide"}}}'
        )

    monkeypatch.setattr(server, "urlopen", opener)
    assert server._load_options(str(tmp_path)) == {
        "gateway_token": "from-supervisor",
        "jev_endpoint": "https://jev.example/decide",
    }


def test_server_startup_passes_runtime_port_and_gateway_token_to_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    class StopServer:
        def __init__(self, address, handler) -> None:
            assert address == ("127.0.0.1", 8123)
            assert handler.gateway.gateway_token == "gateway-secret"

        def serve_forever(self) -> None:
            raise RuntimeError("stop test server")

    monkeypatch.setattr(
        server,
        "build_gateway",
        lambda data_dir: SimpleNamespace(
            gateway_token="", data_dir=data_dir,
            jev=SimpleNamespace(),
            config=SimpleNamespace(privacy_mode=SimpleNamespace(value="local_only")),
            profile_status=lambda: {"status": "disabled"},
        ),
    )
    monkeypatch.setattr(
        server,
        "_load_options",
        lambda data_dir: {"gateway_token": "gateway-secret"},
    )
    monkeypatch.setattr(server, "ThreadingHTTPServer", StopServer)
    monkeypatch.setattr(
        server,
        "register_supervisor_discovery",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ha_switchboard.server", "--data-dir", str(tmp_path), "--port", "8123"],
    )

    with pytest.raises(RuntimeError, match="stop test server"):
        server.main()

    assert calls == [{"port": 8123, "gateway_token": "gateway-secret"}]
