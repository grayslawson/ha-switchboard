from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools" / "local-fixtures" / "live_gate_preflight.py"


def load_module():
    spec = importlib.util.spec_from_file_location("live_gate_preflight", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target(identity=True):
    return {
        "container_name": True,
        "running": True,
        "localhost_port": True,
        "volume_mount": True,
        "supervisor_directories": True,
        "identity_verified": identity,
    }


def options(provider=True):
    return {
        "options_present": True,
        "app_started": True,
        "configured_fields": {"gateway_token": True},
        "provider_configuration_present": provider,
    }


def lifecycle():
    return {
        "config_entry": {"domain": "ha_switchboard", "has_gateway_token": True},
        "core": {
            "conversation_agent_present": True,
            "fixture_identity_fingerprint": "0123456789abcdef",
        },
        "gateway": {
            "status": "active",
            "has_revision": True,
            "pending_section_count": 0,
            "pending_invalidation_count": 0,
        },
    }


def test_preflight_reports_all_prerequisites_without_exposing_optional_token():
    api = load_module()
    secret = "second-user-token-never-in-report"

    report = api.preflight(
        environ={api.SECOND_USER_TOKEN_ENV: secret},
        target=target(),
        options=options(),
        lifecycle=lifecycle(),
        apparmor={"interface_available": True, "profile_loaded": True, "enforcement_available": True},
    )

    assert report["read_only"] is True
    assert report["t059"] == {"optional_second_user_token_present": True}
    assert report["restart_authorization"] == {
        "explicitly_authorized": False,
        "restart_performed": False,
    }
    assert report["ready_for_authorized_live_gate"] is True
    assert secret not in repr(report)


def test_restart_authorization_is_only_a_reported_boolean_and_never_performed():
    api = load_module()

    report = api.preflight(
        allow_restart=True,
        target=target(),
        options=options(),
        lifecycle=lifecycle(),
        apparmor={"interface_available": False, "profile_loaded": False, "enforcement_available": False},
    )

    assert report["restart_authorization"] == {
        "explicitly_authorized": True,
        "restart_performed": False,
    }
    assert report["ready_for_authorized_live_gate"] is False


def test_provider_configuration_and_profile_invariants_fail_closed():
    api = load_module()
    broken = lifecycle()
    broken["gateway"]["pending_section_count"] = 1

    report = api.preflight(
        target=target(),
        options=options(provider=False),
        lifecycle=broken,
        apparmor={"interface_available": True, "profile_loaded": False, "enforcement_available": False},
    )

    assert report["t148"]["provider_configuration_present"] is False
    assert report["t148"]["apparmor"]["enforcement_available"] is False
    assert report["t084"]["existing_volume_and_profile_invariants"]["profile_has_no_pending_sections"] is False
    assert report["ready_for_authorized_live_gate"] is False


def test_apparmor_report_requires_both_host_interface_and_named_profile():
    api = load_module()

    def read(path):
        if path == api.APPARMOR_ENABLED:
            return "Y\n"
        return "other_profile (enforce)\n"

    assert api.apparmor_report(read)["enforcement_available"] is False


def test_disposable_target_uses_declared_local_host_binding_and_volume(monkeypatch):
    api = load_module()
    details = [{
        "Name": "/busy_cohen",
        "State": {"Running": True},
        "HostConfig": {"PortBindings": {"80/tcp": [{"HostIp": "", "HostPort": "7123"}]}},
        "Mounts": [{
            "Destination": "/mnt/supervisor", "Type": "volume", "RW": True,
            "Name": "fixture-volume", "Source": "/var/lib/docker/volumes/fixture-volume/_data",
        }],
    }]
    calls = []

    def run(args, timeout):
        calls.append(args)
        return __import__("json").dumps(details) if args[:2] == ["docker", "inspect"] else ""

    report = api.inspect_disposable_target(run)
    assert report["identity_verified"] is True
    assert calls[-1][:3] == ["docker", "exec", "busy_cohen"]


def test_source_contains_no_mutating_gate_commands():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "ha core restart" not in source
    assert "ha apps restart" not in source
    assert "profile/scan" not in source
    assert "requests." not in source
