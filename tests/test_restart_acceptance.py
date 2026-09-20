from __future__ import annotations

import importlib.util
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


def target_report(fingerprint: str = "0123456789abcdef") -> dict:
    return {
        "container": "busy_cohen",
        "supervisor_port": 7123,
        "supervisor_volume_verified": True,
        "volume_identity_verified": True,
        "volume_identity_fingerprint": fingerprint,
    }


def test_restart_cycle_is_read_only_without_explicit_opt_in(monkeypatch) -> None:
    api = load_module("local_fixture_api_restart_read_only")
    commands: list[list[str]] = []
    report = lifecycle_report()

    monkeypatch.setattr(api, "inspect_local_supervisor", target_report)
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: report)
    monkeypatch.setattr(api, "read_local_app_options", lambda: (
        {"options_present": True, "app_started": True, "configured_fields": {"gateway_token": True}},
        {"gateway_token": "secret-in-memory-only"},
    ))
    monkeypatch.setattr(
        api,
        "run_host_command",
        lambda args, **kwargs: commands.append(args) or "",
    )

    result = api.restart_cycle(allow_restart=False)

    assert result["restart_requested"] is False
    assert result["restart_performed"] is False
    assert commands == []
    assert "secret-in-memory-only" not in repr(result)


def test_restart_rejects_an_unverified_target_before_any_mutation(monkeypatch) -> None:
    api = load_module("local_fixture_api_restart_target_guard")
    commands: list[list[str]] = []
    monkeypatch.setattr(api, "inspect_local_supervisor", lambda: {
        "container": "busy_cohen",
        "supervisor_port": 7123,
        "supervisor_volume_verified": True,
        "volume_identity_verified": False,
    })
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: lifecycle_report())
    monkeypatch.setattr(api, "read_local_app_options", lambda: (
        {"options_present": True, "app_started": True, "configured_fields": {}},
        {},
    ))
    monkeypatch.setattr(api, "run_host_command", lambda args, **kwargs: commands.append(args) or "")

    with pytest.raises(RuntimeError, match="verified local Supervisor volume identity"):
        api.restart_cycle(allow_restart=True)

    assert commands == []


def test_restart_cycle_requires_the_existing_switchboard_state(monkeypatch) -> None:
    api = load_module("local_fixture_api_restart_guard")
    monkeypatch.setattr(api, "inspect_local_supervisor", target_report)
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: {
        "config_entry": {"domain": "other", "source": "hassio"},
        "core": {"conversation_agent_present": False},
        "gateway": {},
    })
    monkeypatch.setattr(api, "read_local_app_options", lambda: (
        {"options_present": True, "app_started": True, "configured_fields": {}},
        {"gateway_token": "secret-in-memory-only"},
    ))

    with pytest.raises(RuntimeError, match="existing Switchboard config entry"):
        api.restart_cycle(allow_restart=True)


@pytest.mark.parametrize(
    ("lifecycle", "options", "message"),
    [
        (
            {
                **lifecycle_report(),
                "core": {"fixture_entity_count": 28, "conversation_agent_present": False},
            },
            {"options_present": True, "app_started": True, "configured_fields": {}},
            "existing Switchboard conversation agent",
        ),
        (
            lifecycle_report(),
            {"options_present": False, "configured_fields": {}},
            "existing local App options",
        ),
    ],
)
def test_restart_preflight_blocks_mutation_when_a_preservation_anchor_is_missing(
    monkeypatch, lifecycle: dict, options: dict, message: str
) -> None:
    api = load_module("local_fixture_api_restart_preflight")
    commands: list[list[str]] = []

    monkeypatch.setattr(
        api,
        "inspect_local_supervisor",
        target_report,
    )
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: lifecycle)
    monkeypatch.setattr(api, "read_local_app_options", lambda: (options, {}))
    monkeypatch.setattr(
        api,
        "run_host_command",
        lambda args, **kwargs: commands.append(args) or "",
    )

    with pytest.raises(RuntimeError, match=message):
        api.restart_cycle(allow_restart=True)

    assert commands == []


def test_authorized_restart_reports_preservation_invariants_without_real_host_commands(monkeypatch) -> None:
    api = load_module("local_fixture_api_restart_preservation")
    commands: list[list[str]] = []
    waits: list[str] = []
    reports = [lifecycle_report(), lifecycle_report(), lifecycle_report()]
    options = {"options_present": True, "app_started": True, "configured_fields": {"gateway_token": True}}
    private_options = {"gateway_token": "opaque-in-memory-test-value"}

    monkeypatch.setattr(
        api,
        "inspect_local_supervisor",
        target_report,
    )
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: reports.pop(0))
    monkeypatch.setattr(
        api,
        "read_local_app_options",
        lambda: (options, dict(private_options)),
    )
    monkeypatch.setattr(
        api,
        "run_host_command",
        lambda args, **kwargs: commands.append(args) or "",
    )
    monkeypatch.setattr(api, "wait_for_local_component", lambda component, **kwargs: waits.append(component))

    result = api.restart_cycle(allow_restart=True)

    assert commands == [
        ["docker", "exec", api.LOCAL_SUPERVISOR_CONTAINER, "ha", "apps", "restart", api.LOCAL_APP_SLUG],
        ["docker", "exec", api.LOCAL_SUPERVISOR_CONTAINER, "ha", "core", "restart", "--raw-json"],
    ]
    assert waits == ["app", "core"]
    assert result["mode"] == "opt_in"
    assert result["restart_requested"] is True
    assert result["restart_performed"] is True
    assert result["preserved"] == {
        "options": True,
        "app_restart_preserved": True,
        "config_entry": True,
        "fixture_count": True,
        "conversation_agent": True,
        "profile_recovered": True,
        "volume_identity": True,
    }
    assert result["complete"] is True
    assert "opaque-in-memory-test-value" not in repr(result)


def test_restart_stops_before_core_when_app_restart_loses_anchors(monkeypatch) -> None:
    api = load_module("local_fixture_api_restart_anchor_guard")
    commands: list[list[str]] = []
    reports = [
        lifecycle_report(),
        {**lifecycle_report(), "config_entry": {"domain": "other"}},
    ]
    monkeypatch.setattr(api, "inspect_local_supervisor", target_report)
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: reports.pop(0))
    monkeypatch.setattr(api, "read_local_app_options", lambda: (
        {"options_present": True, "app_started": True, "configured_fields": {}},
        {},
    ))
    monkeypatch.setattr(api, "run_host_command", lambda args, **kwargs: commands.append(args) or "")
    monkeypatch.setattr(api, "wait_for_local_component", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="preserve config entry and fixture anchors"):
        api.restart_cycle(allow_restart=True)

    assert len(commands) == 1
    assert commands[0][-2:] == ["restart", api.LOCAL_APP_SLUG]


def test_cli_requires_explicit_restart_flag_and_rejects_it_elsewhere() -> None:
    api = load_module("local_fixture_api_restart_cli")

    assert api.parse_cli_args(["restart-cycle"]) == ("restart-cycle", False)
    assert api.parse_cli_args(["restart-cycle", "--allow-restart"]) == (
        "restart-cycle",
        True,
    )
    with pytest.raises(SystemExit):
        api.parse_cli_args(["lifecycle", "--allow-restart"])


def test_host_wrapper_feeds_the_current_fixture_script_to_core(monkeypatch) -> None:
    api = load_module("local_fixture_api_restart_stdin")
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return '{"config_entry": {}, "core": {}, "gateway": {}}'

    monkeypatch.setattr(api, "run_host_command", fake_run)

    api.run_core_fixture_command("lifecycle")

    assert captured["args"][-3:] == ["python3", "-", "lifecycle"]
    assert captured["input_text"] == (FIXTURE / "local_api.py").read_text(encoding="utf-8")


def test_volume_identity_requires_a_named_volume_with_matching_source() -> None:
    api = load_module("local_fixture_api_volume_identity")
    base = {
        "name": "/busy_cohen",
        "running": True,
        "port_bindings": {"80/tcp": [{"HostIp": "", "HostPort": "7123"}]},
    }
    valid = {
        **base,
        "mounts": [{
            "Type": "volume",
            "Name": "local-supervisor-data",
            "Source": "/var/lib/docker/volumes/local-supervisor-data/_data",
            "Destination": "/mnt/supervisor",
            "RW": True,
        }],
    }
    result = api.validate_local_supervisor_inspect(valid)
    assert result["volume_identity_verified"] is True
    assert len(result["volume_identity_fingerprint"]) == 16
    assert "/var/lib/docker" not in repr(result)

    for bad_mount in (
        {**valid["mounts"][0], "Name": "other-volume"},
        {**valid["mounts"][0], "Source": "/tmp/not-a-docker-volume"},
        {**valid["mounts"][0], "RW": False},
    ):
        with pytest.raises(RuntimeError, match="unverified local Supervisor volume"):
            api.validate_local_supervisor_inspect({**valid, "mounts": [bad_mount]})


def test_restart_rejects_volume_identity_change_before_reporting_success(monkeypatch) -> None:
    api = load_module("local_fixture_api_restart_volume_change")
    targets = iter((target_report("0123456789abcdef"), target_report("fedcba9876543210")))
    monkeypatch.setattr(api, "inspect_local_supervisor", lambda: next(targets))
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: lifecycle_report())
    monkeypatch.setattr(api, "read_local_app_options", lambda: (
        {"options_present": True, "app_started": True, "configured_fields": {"gateway_token": True}},
        {"gateway_token": "secret-in-memory-only"},
    ))
    monkeypatch.setattr(api, "run_host_command", lambda *args, **kwargs: "")
    monkeypatch.setattr(api, "wait_for_local_component", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="volume identity changed"):
        api.restart_cycle(allow_restart=True)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_bounded_timeout_rejects_non_positive_or_non_finite_values(timeout) -> None:
    api = load_module("local_fixture_api_timeout")
    with pytest.raises(RuntimeError, match="timeout"):
        api.bounded_timeout(timeout, 10)


def test_sanitized_invariant_reports_never_include_private_target_fields() -> None:
    api = load_module("local_fixture_api_sanitized_invariants")
    target = {
        **target_report(),
        "source": "/var/lib/docker/volumes/private/_data",
        "token": "do-not-print",
    }
    result = api.safe_target_evidence(target)
    assert result == {
        "container": "busy_cohen",
        "supervisor_port": 7123,
        "supervisor_volume_verified": True,
        "volume_identity_verified": True,
        "volume_identity_fingerprint": "0123456789abcdef",
    }
    assert "private" not in repr(result)
    assert "do-not-print" not in repr(result)


def test_scan_invariants_require_bounded_settled_before_and_after_profiles() -> None:
    api = load_module("local_fixture_api_scan_invariants")
    before = {
        "status": "active",
        "capability_count": 28,
        "profile_revision": "opaque-revision",
        "monitor": {"pending_sections": [], "pending_invalidations": []},
    }
    after = dict(before)
    result = api.scan_invariant_report(before, after, 202, True)
    assert result["complete"] is True
    assert result["capability_count_preserved"] is True

    unsettled = {**before, "status": "stale"}
    assert api.scan_invariant_report(unsettled, after, 202, True)["complete"] is False
    pending = {**before, "monitor": {"pending_sections": [], "pending_invalidations": ["entities"]}}
    assert api.scan_invariant_report(pending, after, 202, True)["complete"] is False
    changed = {**before, "capability_count": 2}
    assert api.scan_invariant_report(before, changed, 202, True)["complete"] is False


def test_component_wait_rejects_unknown_components() -> None:
    api = load_module("local_fixture_api_component_guard")
    with pytest.raises(RuntimeError, match="unsupported local component"):
        api.wait_for_local_component("supervisor")
