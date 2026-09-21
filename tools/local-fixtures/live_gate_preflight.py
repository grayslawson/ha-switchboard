#!/usr/bin/env python3
"""Read-only prerequisite report for the T059/T084/T148 live gates.

This command is deliberately a preflight, not an acceptance runner.  It only
reads Docker metadata, existing Supervisor options, the Core lifecycle
snapshot, the optional token's presence, and the host AppArmor interfaces. It
does not create credentials, restart anything, scan a profile, contact a
provider, or change Home Assistant state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping


CONTAINER = "busy_cohen"
CORE_CONTAINER = "homeassistant"
APP_SLUG = "local_ha_switchboard"
LOCAL_PORT = 7123
SUPERVISOR_VOLUME = "/mnt/supervisor"
SECOND_USER_TOKEN_ENV = "HA_SWITCHBOARD_FOLLOW_UP_SECOND_USER_ACCESS_TOKEN"
APPARMOR_ENABLED = Path("/sys/module/apparmor/parameters/enabled")
APPARMOR_PROFILES = Path("/sys/kernel/security/apparmor/profiles")
APPARMOR_PROFILE = "ha_switchboard"
COMMAND_TIMEOUT = 20.0


CommandRunner = Callable[..., str]


def run_command(
    args: list[str], timeout: float = COMMAND_TIMEOUT, input_text: str | None = None,
) -> str:
    """Run one bounded local read command while suppressing command output."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"bounded read failed: {args[0]}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"bounded read failed: {args[0]}")
    return result.stdout


def _json_output(output: str, message: str) -> Any:
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        raise RuntimeError(message) from None


def _volume_identity(mount: Mapping[str, Any]) -> bool:
    name = mount.get("Name")
    source = mount.get("Source")
    return (
        mount.get("Type") == "volume"
        and mount.get("RW") is True
        and isinstance(name, str)
        and bool(name)
        and isinstance(source, str)
        and source.endswith(f"/volumes/{name}/_data")
    )


def inspect_disposable_target(run: CommandRunner = run_command) -> dict[str, Any]:
    """Verify the exact disposable container, port, and preserve-first volume."""
    raw = _json_output(
        run(["docker", "inspect", CONTAINER], COMMAND_TIMEOUT),
        "Docker returned invalid container metadata",
    )
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise RuntimeError("Docker returned incomplete container metadata")
    details = raw[0]
    # HostConfig retains the declared localhost binding without relying on
    # Docker's runtime-normalized 0.0.0.0/:: addresses.
    ports = details.get("HostConfig", {}).get("PortBindings", {})
    published = {
        str(item.get("HostPort"))
        for item in ports.get("80/tcp") or []
        if isinstance(item, dict) and item.get("HostIp", "") in {"", "127.0.0.1", "::1"}
    }
    mounts = [
        item for item in details.get("Mounts", [])
        if isinstance(item, dict) and item.get("Destination") == SUPERVISOR_VOLUME
    ]
    volume_ok = len(mounts) == 1 and _volume_identity(mounts[0])
    directory_ok = False
    if volume_ok:
        run(
            ["docker", "exec", CONTAINER, "sh", "-c",
             "test -d /mnt/supervisor && test -d /mnt/supervisor/homeassistant"],
            COMMAND_TIMEOUT,
        )
        directory_ok = True
    return {
        "container_name": details.get("Name") == f"/{CONTAINER}",
        "running": details.get("State", {}).get("Running") is True,
        "localhost_port": str(LOCAL_PORT) in published,
        "volume_mount": volume_ok,
        "supervisor_directories": directory_ok,
        "identity_verified": (
            details.get("Name") == f"/{CONTAINER}"
            and details.get("State", {}).get("Running") is True
            and str(LOCAL_PORT) in published
            and volume_ok
            and directory_ok
        ),
    }


def read_existing_options(run: CommandRunner = run_command) -> dict[str, Any]:
    """Read Supervisor options and retain only presence booleans."""
    output = run(
        ["docker", "exec", CONTAINER, "ha", "apps", "info", "--raw-json", APP_SLUG],
        COMMAND_TIMEOUT,
    )
    payload = _json_output(output, "Supervisor returned invalid App metadata")
    try:
        data = payload["data"]
        options = data["options"]
        state = data["state"]
    except (KeyError, TypeError):
        raise RuntimeError("Supervisor App options were unavailable") from None
    if not isinstance(options, dict):
        raise RuntimeError("Supervisor App options were not an object")
    fields = (
        "gateway_token", "jev_provider", "jev_endpoint", "jev_api_key",
        "fallback_provider", "fallback_endpoint", "fallback_model", "fallback_api_key",
    )
    return {
        "options_present": bool(options),
        "app_started": state == "started",
        "configured_fields": {field: bool(options.get(field)) for field in fields},
        "provider_configuration_present": any(
            bool(options.get(field))
            for field in ("jev_provider", "jev_endpoint", "jev_api_key",
                          "fallback_provider", "fallback_endpoint", "fallback_model",
                          "fallback_api_key")
        ),
    }


def read_lifecycle(run: CommandRunner = run_command) -> dict[str, Any]:
    """Read the existing Core lifecycle reducer; no Core command is mutated."""
    script = Path(__file__).with_name("local_api.py").read_text(encoding="utf-8")
    output = run(
        ["docker", "exec", "-i", CONTAINER, "docker", "exec", "-i", CORE_CONTAINER,
         "python3", "-", "lifecycle"],
        COMMAND_TIMEOUT,
        input_text=script,
    )
    report = _json_output(output, "Core lifecycle returned invalid evidence")
    if not isinstance(report, dict):
        raise RuntimeError("Core lifecycle evidence was not an object")
    return report


def apparmor_report(
    read_text: Callable[[Path], str] = lambda path: path.read_text(encoding="utf-8"),
) -> dict[str, Any]:
    """Report host AppArmor availability and the expected loaded profile only."""
    try:
        enabled = read_text(APPARMOR_ENABLED).strip() == "Y"
        profiles = read_text(APPARMOR_PROFILES).splitlines()
        loaded = any(line.split(maxsplit=1)[0] == APPARMOR_PROFILE for line in profiles if line)
    except (OSError, UnicodeError):
        enabled = False
        loaded = False
    return {
        "interface_available": enabled,
        "profile_loaded": enabled and loaded,
        "enforcement_available": enabled and loaded,
    }


def lifecycle_invariants(lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    config = lifecycle.get("config_entry", {})
    core = lifecycle.get("core", {})
    gateway = lifecycle.get("gateway", {})
    return {
        "config_entry_present": config.get("domain") == "ha_switchboard",
        "gateway_token_present": config.get("has_gateway_token") is True,
        "conversation_agent_present": core.get("conversation_agent_present") is True,
        "fixture_identity_present": isinstance(core.get("fixture_identity_fingerprint"), str),
        "profile_active": gateway.get("status") == "active",
        "profile_revision_present": gateway.get("has_revision") is True,
        "profile_has_no_pending_sections": gateway.get("pending_section_count") == 0,
        "profile_has_no_pending_invalidations": gateway.get("pending_invalidation_count") == 0,
    }


def preflight(
    *,
    allow_restart: bool = False,
    environ: Mapping[str, str] | None = None,
    target: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
    apparmor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a secret-free report from read-only observations."""
    source = os.environ if environ is None else environ
    token_present = bool(source.get(SECOND_USER_TOKEN_ENV, "").strip())
    target = target or inspect_disposable_target()
    options = options or read_existing_options()
    lifecycle = lifecycle or read_lifecycle()
    apparmor = apparmor or apparmor_report()
    invariants = lifecycle_invariants(lifecycle)
    report = {
        "command": "live-gate-preflight",
        "read_only": True,
        "restart_authorization": {
            "explicitly_authorized": allow_restart is True,
            "restart_performed": False,
        },
        "t059": {"optional_second_user_token_present": token_present},
        "t084": {
            "disposable_target": target,
            "existing_volume_and_profile_invariants": {
                **invariants,
                "target_identity_verified": target.get("identity_verified") is True,
            },
        },
        "t148": {
            "provider_configuration_present": options.get("provider_configuration_present") is True,
            "apparmor": apparmor,
        },
        "options": options,
    }
    report["ready_for_authorized_live_gate"] = (
        report["t084"]["disposable_target"].get("identity_verified") is True
        and all(invariants.values())
        and options.get("options_present") is True
        and options.get("app_started") is True
        and apparmor.get("enforcement_available") is True
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="live_gate_preflight.py")
    parser.add_argument(
        "--allow-restart", action="store_true",
        help="record explicit authorization; this preflight never restarts anything",
    )
    args = parser.parse_args(argv)
    try:
        report = preflight(allow_restart=args.allow_restart is True)
    except RuntimeError as exc:
        print(json.dumps({
            "command": "live-gate-preflight",
            "read_only": True,
            "ready_for_authorized_live_gate": False,
            "error": str(exc),
        }, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
