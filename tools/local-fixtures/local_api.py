"""Use Core's supported local APIs with an ephemeral token kept in memory.

Run only inside the named devcontainer's Home Assistant Core container.
No token or auth-store content is printed or written by this script.
"""

from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

BASE = "http://127.0.0.1:80"
PIPELINE_NAME = "HA Switchboard Fixture"
AGENT = "conversation.ha_switchboard"
FIXTURE_AREA = "Switchboard Fixture Lab"
FIXTURE_LABELS = ("Switchboard Fixture", "Switchboard Actuator")
FIXTURE_GROUP = "Switchboard Fixture Lights"
FIXTURE_GROUP_UTTERANCE = f"Turn on the {FIXTURE_GROUP} group"
GATEWAY_TIMEOUT_SECONDS = 10
SCAN_POLL_INTERVAL_SECONDS = 0.5
SCAN_POLL_ATTEMPTS = 24
SCAN_STATUS_WINDOW_SECONDS = 12
ASSIST_EVENT_TIMEOUT_SECONDS = 5
ASSIST_MAX_EVENTS = 24
ASSIST_FOLLOW_UP_TIMEOUT_SECONDS = 30
ASSIST_FOLLOW_UP_CONVERSATION = "fixture-follow-up"
FOLLOW_UP_SECOND_USER_ACCESS_TOKEN_ENV = "HA_SWITCHBOARD_FOLLOW_UP_SECOND_USER_ACCESS_TOKEN"
FOLLOW_UP_NATURAL_EXPIRY_ENV = "HA_SWITCHBOARD_RUN_FOLLOW_UP_NATURAL_EXPIRY"
FOLLOW_UP_RUN_OPT_IN_ENV = "HA_SWITCHBOARD_RUN_FOLLOW_UP"
# ConversationContextStore's production default is 120 seconds.  The small
# safety margin gives Core time to expire the entry without permitting an
# unbounded wait in this fixture probe.
FOLLOW_UP_CONTINUATION_TTL_SECONDS = 120
FOLLOW_UP_NATURAL_EXPIRY_SAFETY_SECONDS = 2
FOLLOW_UP_NATURAL_EXPIRY_MAX_WAIT_SECONDS = 150
NATIVE_FAST_PATH_CONVERSATION = "fixture-native-fast-path"
WEBSOCKET_CALL_TIMEOUT_SECONDS = 20
WEBSOCKET_CALL_MAX_EVENTS = 64

# The restart-cycle command is deliberately host-side.  The existing lifecycle
# and scan commands remain Core-side and are invoked by this wrapper through
# the disposable Supervisor devcontainer.
LOCAL_SUPERVISOR_CONTAINER = "busy_cohen"
LOCAL_CORE_CONTAINER = "homeassistant"
LOCAL_APP_SLUG = "local_ha_switchboard"
LOCAL_SUPERVISOR_PORT = 7123
LOCAL_SUPERVISOR_VOLUME_DESTINATION = "/mnt/supervisor"
HOST_COMMAND_TIMEOUT_SECONDS = 10
RESTART_ACTION_TIMEOUT_SECONDS = 30
RESTART_WAIT_SECONDS = 60
RESTART_CYCLE_TIMEOUT_SECONDS = 120

# Keep this copy deliberately independent of the integration package: this
# file is executed inside the Core container, where the worktree is absent.
# Each row is an executable Switchboard operation advertised by the fixture.
PUBLISHED_MATRIX = (
    ("light", "turn_on", "light.switchboard_fixture_light"),
    ("light", "turn_off", "light.switchboard_fixture_light"),
    ("light", "toggle", "light.switchboard_fixture_light"),
    ("light", "set_brightness", "light.switchboard_fixture_light"),
    ("switch", "turn_on", "switch.switchboard_fixture_switch"),
    ("switch", "turn_off", "switch.switchboard_fixture_switch"),
    ("switch", "toggle", "switch.switchboard_fixture_switch"),
    ("fan", "turn_on", "fan.switchboard_fixture_fan"),
    ("fan", "turn_off", "fan.switchboard_fixture_fan"),
    ("fan", "toggle", "fan.switchboard_fixture_fan"),
    ("media_player", "turn_on", "media_player.switchboard_fixture_player"),
    ("media_player", "turn_off", "media_player.switchboard_fixture_player"),
    ("media_player", "play", "media_player.switchboard_fixture_player"),
    ("media_player", "pause", "media_player.switchboard_fixture_player"),
    ("media_player", "stop", "media_player.switchboard_fixture_player"),
    ("media_player", "set_volume", "media_player.switchboard_fixture_player"),
    ("climate", "set_temperature", "climate.switchboard_fixture_thermostat"),
    ("climate", "set_hvac_mode", "climate.switchboard_fixture_thermostat"),
    ("cover", "open_cover", "cover.switchboard_fixture_cover"),
    ("cover", "close_cover", "cover.switchboard_fixture_cover"),
    ("garage", "open_cover", "cover.switchboard_fixture_garage"),
    ("garage", "close_cover", "cover.switchboard_fixture_garage"),
    ("lock", "lock", "lock.switchboard_fixture_lock"),
    ("lock", "unlock", "lock.switchboard_fixture_lock"),
)

# These remain useful native Core surfaces for fixture setup and direct-service
# tests, but they are intentionally outside the Switchboard operation matrix.
NATIVE_HASS_SURFACES = (
    ("script", "activate", "script.switchboard_fixture_evening"),
    ("scene", "activate", "scene.switchboard_fixture_calm"),
)
NATIVE_CORE_ONLY_ENTITY_IDS = frozenset(entity_id for _, _, entity_id in NATIVE_HASS_SURFACES)

# The semantic operation names are the contract exposed by the profile.  The
# service names and parameter shapes below are the Core-side implementation
# exercised by ``exercise``; keeping this map here makes the live fixture fail
# closed when a published row has no executable test case.
MATRIX_SERVICE_CASES = {
    ("light", "turn_on"): ("light", "turn_on", {}, "on"),
    ("light", "turn_off"): ("light", "turn_off", {}, "off"),
    ("light", "toggle"): ("light", "toggle", {}, None),
    ("light", "set_brightness"): ("light", "turn_on", {"brightness_pct": 40}, "on"),
    ("switch", "turn_on"): ("switch", "turn_on", {}, "on"),
    ("switch", "turn_off"): ("switch", "turn_off", {}, "off"),
    ("switch", "toggle"): ("switch", "toggle", {}, None),
    ("fan", "turn_on"): ("fan", "turn_on", {}, "on"),
    ("fan", "turn_off"): ("fan", "turn_off", {}, "off"),
    ("fan", "toggle"): ("fan", "toggle", {}, None),
    ("media_player", "turn_on"): ("media_player", "turn_on", {}, "idle"),
    ("media_player", "turn_off"): ("media_player", "turn_off", {}, "off"),
    ("media_player", "play"): ("media_player", "media_play", {}, "playing"),
    ("media_player", "pause"): ("media_player", "media_pause", {}, "paused"),
    ("media_player", "stop"): ("media_player", "media_stop", {}, "idle"),
    ("media_player", "set_volume"): ("media_player", "volume_set", {"volume_level": 0.25}, "idle"),
    ("climate", "set_temperature"): ("climate", "set_temperature", {"temperature": 21}, "off"),
    ("climate", "set_hvac_mode"): ("climate", "set_hvac_mode", {"hvac_mode": "heat"}, "heat"),
    ("cover", "open_cover"): ("cover", "open_cover", {}, "open"),
    ("cover", "close_cover"): ("cover", "close_cover", {}, "closed"),
    ("garage", "open_cover"): ("cover", "open_cover", {}, "open"),
    ("garage", "close_cover"): ("cover", "close_cover", {}, "closed"),
    ("lock", "lock"): ("lock", "lock", {}, "locked"),
    ("lock", "unlock"): ("lock", "unlock", {}, "unlocked"),
}


def operation_matrix_plan() -> tuple[dict[str, Any], ...]:
    """Return the executable Core service case for every published row."""
    plan = []
    for domain, operation, entity_id in PUBLISHED_MATRIX:
        try:
            service_domain, service, service_data, expected_state = MATRIX_SERVICE_CASES[(domain, operation)]
        except KeyError:
            raise RuntimeError(f"No local exercise case for {domain}.{operation}") from None
        plan.append({
            "domain": domain,
            "operation": operation,
            "entity_id": entity_id,
            "service_domain": service_domain,
            "service": service,
            "service_data": dict(service_data),
            "expected_state": expected_state,
        })
    return tuple(plan)


def unsupported_surface_report(
    states: Mapping[str, Mapping[str, Any]], exposed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Report native Core surfaces that are intentionally outside Switchboard."""
    exposed_ids = {
        entity_id for entity_id, assistants in exposed.items()
        if isinstance(assistants, Mapping) and assistants.get("conversation")
    }
    rows = [
        {
            "domain": domain,
            "operation": operation,
            "entity_id": entity_id,
            "present": entity_id in states,
            "exposed": entity_id in exposed_ids,
            "supported_by_switchboard": False,
            "reason": "native_core_only",
        }
        for domain, operation, entity_id in NATIVE_HASS_SURFACES
    ]
    return {
        "rows": rows,
        "present_count": sum(row["present"] for row in rows),
        "unexpectedly_exposed": [row["entity_id"] for row in rows if row["exposed"]],
        "complete": all(row["present"] and not row["exposed"] for row in rows),
    }

PRIMARY_ENTITIES = (
    "light.switchboard_fixture_light", "light.switchboard_fixture_lamp",
    "switch.switchboard_fixture_switch", "fan.switchboard_fixture_fan",
    "cover.switchboard_fixture_cover", "cover.switchboard_fixture_garage",
    "lock.switchboard_fixture_lock", "climate.switchboard_fixture_thermostat",
    "media_player.switchboard_fixture_player", "sensor.switchboard_fixture_temperature_reading",
    "binary_sensor.switchboard_fixture_motion", "script.switchboard_fixture_evening",
    "scene.switchboard_fixture_calm",
)


def registry_supported_entities(
    registry_entries: list[dict],
    candidates: tuple[str, ...] = PRIMARY_ENTITIES,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Select metadata targets without masking missing executable fixtures.

    Scripts and scenes are native Core surfaces and may have no entity-registry
    records. Every other fixture entity must be registered so a broken fixture
    fails closed instead of silently reducing the test scope.
    """
    registered = {
        item.get("entity_id") for item in registry_entries if item.get("entity_id")
    }
    supported = tuple(entity_id for entity_id in candidates if entity_id in registered)
    skipped = tuple(
        entity_id for entity_id in candidates
        if entity_id not in registered and entity_id in NATIVE_CORE_ONLY_ENTITY_IDS
    )
    missing = tuple(
        entity_id for entity_id in candidates
        if entity_id not in registered and entity_id not in NATIVE_CORE_ONLY_ENTITY_IDS
    )
    if missing:
        raise RuntimeError(f"Local fixture entities missing from registry: {list(missing)}")
    return supported, skipped


DETERMINISTIC_FAILURES = {
    "provider_unavailable": {"kind": "provider_error", "reason": "provider_unavailable"},
    "provider_malformed": {"kind": "provider_error", "reason": "provider_malformed_response"},
    "parameter_missing": {"kind": "parameter_error", "reason": "parameter_missing", "parameter": "brightness"},
    "parameter_out_of_range": {"kind": "parameter_error", "reason": "parameter_out_of_range", "parameter": "brightness", "minimum": 0, "maximum": 100},
    "unknown_capability": {"kind": "policy_error", "reason": "unknown_capability"},
}


def coverage_report(states: dict[str, dict], exposed: dict[str, dict]) -> dict:
    """Return stable, secret-free fixture coverage evidence for CI and humans."""
    present = set(states)
    exposed_ids = {
        entity_id for entity_id, assistants in exposed.items()
        if "conversation" in assistants and assistants["conversation"]
    }
    rows = [
        {"domain": domain, "operation": operation, "entity_id": entity_id,
         "present": entity_id in present, "exposed": entity_id in exposed_ids}
        for domain, operation, entity_id in PUBLISHED_MATRIX
    ]
    return {
        "matrix_rows": len(rows),
        "covered_rows": sum(row["present"] and row["exposed"] for row in rows),
        "missing_entities": sorted({row["entity_id"] for row in rows if not row["present"]}),
        "unexposed_entities": sorted({row["entity_id"] for row in rows if row["present"] and not row["exposed"]}),
        "unsupported": unsupported_surface_report(states, exposed),
        "rows": rows,
    }


def named_group_acceptance(profile: Any, utterance: str = FIXTURE_GROUP_UTTERANCE) -> dict[str, Any]:
    """Prove named-group profile representation and bounded selection safely.

    This is intentionally a pure acceptance helper.  It consumes the already
    sanitized profile object used by the gateway, returns only counts and
    stable error codes, and never executes an operation or emits opaque/raw
    entity references.
    """
    from ha_switchboard.batch import BatchRequestError, build_batch_group

    named = [item for item in profile.groups if item.name == FIXTURE_GROUP]
    report: dict[str, Any] = {
        "group_name": FIXTURE_GROUP,
        "group_count": len(named),
        "group_present": len(named) == 1,
        "group_valid": bool(named and named[0].valid),
        "member_count": len(named[0].members) if len(named) == 1 else 0,
        "selected": False,
        "operation": None,
        "error": None,
    }
    try:
        selected = build_batch_group(utterance, profile)
    except BatchRequestError as exc:
        report["error"] = exc.code
        return report
    if selected is not None:
        report.update(
            selected=True,
            operation=selected.operation,
            selected_member_count=len(selected.members),
        )
    return report


def config_entry_report(entries: list[dict]) -> dict:
    """Return safe evidence that the local Core entry is installed and usable.

    The gateway token is deliberately reduced to a boolean.  The URL is
    reduced to host/port so this report is safe to paste into a test log.
    """
    switchboard = [entry for entry in entries if entry.get("domain") == "ha_switchboard"]
    if len(switchboard) != 1:
        raise RuntimeError(
            f"Expected exactly one local Switchboard config entry; found {len(switchboard)}"
        )
    entry = switchboard[0]
    data = entry.get("data") or {}
    gateway_url = data.get("gateway_url")
    if not isinstance(gateway_url, str) or not gateway_url:
        raise RuntimeError("Local Switchboard config entry has no gateway URL")
    parsed = urlsplit(gateway_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("Local Switchboard gateway URL contains unsafe URL fields")
    return {
        "domain": entry.get("domain"),
        "source": entry.get("source"),
        "title": entry.get("title"),
        "version": entry.get("version"),
        "has_gateway_token": bool(data.get("gateway_token")),
        "gateway_host": parsed.hostname,
        "gateway_port": parsed.port,
    }


def profile_status_report(status: dict) -> dict:
    """Reduce a gateway profile response to safe lifecycle evidence."""
    monitor = status.get("monitor") if isinstance(status.get("monitor"), dict) else {}
    pending_sections = monitor.get("pending_sections")
    pending_invalidations = monitor.get("pending_invalidations")
    return {
        "status": status.get("status"),
        "capability_count": status.get("capability_count"),
        "has_revision": bool(status.get("profile_revision")),
        "pending_section_count": len(pending_sections) if isinstance(pending_sections, list) else None,
        "pending_invalidation_count": len(pending_invalidations) if isinstance(pending_invalidations, list) else None,
    }


def gateway_config(entries: list[dict]) -> tuple[str, str]:
    """Return the local gateway URL/token for in-memory use only."""
    switchboard = [entry for entry in entries if entry.get("domain") == "ha_switchboard"]
    if len(switchboard) != 1:
        raise RuntimeError(f"Expected exactly one local Switchboard config entry; found {len(switchboard)}")
    data = switchboard[0].get("data") or {}
    gateway_url = data.get("gateway_url")
    gateway_token = data.get("gateway_token")
    if not isinstance(gateway_url, str) or not gateway_url:
        raise RuntimeError("Local Switchboard config entry has no gateway URL")
    if not isinstance(gateway_token, str) or not gateway_token:
        raise RuntimeError("Local Switchboard config entry has no gateway token")
    parsed = urlsplit(gateway_url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("Local Switchboard gateway URL is not safe for fixture use")
    if parsed.hostname not in {"local-ha-switchboard", "localhost", "127.0.0.1"}:
        raise RuntimeError("Fixture gateway must be the disposable local Switchboard host")
    try:
        port = parsed.port
    except ValueError:
        raise RuntimeError("Fixture gateway must use a valid disposable local Switchboard port") from None
    if port not in {None, 8099}:
        raise RuntimeError("Fixture gateway must use the disposable local Switchboard port")
    return gateway_url.rstrip("/"), gateway_token


async def gateway_request(
    session,
    gateway_url: str,
    gateway_token: str,
    method: str,
    path: str,
    payload: dict | None = None,
    timeout_seconds: float = GATEWAY_TIMEOUT_SECONDS,
) -> tuple[int, dict]:
    """Make one bounded gateway request without exposing response bodies on errors."""
    import aiohttp

    try:
        timeout = aiohttp.ClientTimeout(
            total=max(0.2, min(float(timeout_seconds), GATEWAY_TIMEOUT_SECONDS))
        )
        async with session.request(
            method,
            gateway_url + path,
            headers={"Authorization": f"Bearer {gateway_token}", "Accept": "application/json"},
            json=payload,
            timeout=timeout,
        ) as response:
            status_code = response.status
            try:
                body = await response.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError):
                body = {}
            if not isinstance(body, dict):
                body = {}
            return status_code, body
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        raise RuntimeError(f"Gateway {method} {path} failed within {GATEWAY_TIMEOUT_SECONDS}s: {type(exc).__name__}") from None


def lifecycle_report(config: dict, states: dict[str, dict], profile: dict) -> dict:
    """Build restart-safe evidence without raw IDs, URLs, or credentials."""
    return {
        "config_entry": {
            "domain": config.get("domain"),
            "source": config.get("source"),
            "version": config.get("version"),
            "has_gateway_token": config.get("has_gateway_token"),
        },
        "core": {
            "fixture_entity_count": sum(
                isinstance(entity_id, str) and "switchboard_fixture" in entity_id
                for entity_id in states
            ),
            "conversation_agent_present": AGENT in states,
            "fixture_identity_fingerprint": fixture_identity_fingerprint(states),
        },
        "gateway": profile_status_report(profile),
    }


def profile_is_settled(status: dict) -> bool:
    """Return true only for an active profile with no pending work."""
    report = profile_status_report(status)
    return (
        report["status"] == "active"
        and report["pending_section_count"] == 0
        and report["pending_invalidation_count"] == 0
    )


def scan_invariant_report(before: dict, after: dict, request_status: int, settled: bool) -> dict:
    """Summarize scan acceptance without returning gateway or entity data."""
    before_report = profile_status_report(before)
    after_report = profile_status_report(after)
    revision_present = bool(before_report["has_revision"] and after_report["has_revision"])
    return {
        "request_accepted": request_status == 202,
        "before_settled": profile_is_settled(before),
        "after_settled": profile_is_settled(after),
        "revision_present": bool(before_report["has_revision"] and after_report["has_revision"]),
        "capability_count_preserved": (
            isinstance(before_report["capability_count"], int)
            and isinstance(after_report["capability_count"], int)
            and before_report["capability_count"] == after_report["capability_count"]
        ),
        "complete": bool(
            request_status == 202
            and settled
            and profile_is_settled(before)
            and profile_is_settled(after)
            and revision_present
            and (
                isinstance(before_report["capability_count"], int)
                and isinstance(after_report["capability_count"], int)
                and before_report["capability_count"] == after_report["capability_count"]
            )
        ),
    }


def fixture_identity_fingerprint(states: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Hash the disposable fixture set without exposing entity identifiers."""
    fixture_ids = sorted(
        entity_id
        for entity_id in states
        if isinstance(entity_id, str) and "switchboard_fixture" in entity_id
    )
    if not fixture_ids:
        return None
    return hashlib.sha256("\0".join(fixture_ids).encode("utf-8")).hexdigest()[:16]


def valid_fixture_identity_fingerprint(value: Any) -> bool:
    """Accept only the bounded, secret-free fixture-set fingerprint shape."""
    return isinstance(value, str) and len(value) == 16 and all(
        character in "0123456789abcdef" for character in value
    )


def lifecycle_profile_is_settled(lifecycle: Mapping[str, Any]) -> bool:
    """Require an active, revisioned profile with no pending work."""
    gateway = lifecycle.get("gateway")
    return isinstance(gateway, Mapping) and (
        gateway.get("status") == "active"
        and gateway.get("has_revision") is True
        and gateway.get("pending_section_count") == 0
        and gateway.get("pending_invalidation_count") == 0
    )


def safe_lifecycle_evidence(report: dict) -> dict:
    """Keep lifecycle output to the established secret-free contract."""
    config = report.get("config_entry") if isinstance(report.get("config_entry"), dict) else {}
    core = report.get("core") if isinstance(report.get("core"), dict) else {}
    gateway = report.get("gateway") if isinstance(report.get("gateway"), dict) else {}
    return {
        "config_entry": {
            "domain": config.get("domain"),
            "source": config.get("source"),
            "version": config.get("version"),
            "has_gateway_token": bool(config.get("has_gateway_token")),
        },
        "core": {
            "fixture_entity_count": core.get("fixture_entity_count"),
            "conversation_agent_present": bool(core.get("conversation_agent_present")),
            "fixture_identity_fingerprint": (
                core.get("fixture_identity_fingerprint")
                if valid_fixture_identity_fingerprint(core.get("fixture_identity_fingerprint"))
                else None
            ),
        },
        "gateway": {
            "status": gateway.get("status"),
            "capability_count": gateway.get("capability_count"),
            "has_revision": bool(gateway.get("has_revision")),
            "pending_section_count": gateway.get("pending_section_count"),
            "pending_invalidation_count": gateway.get("pending_invalidation_count"),
        },
    }


def safe_target_evidence(target: dict) -> dict:
    """Return only non-sensitive target and volume invariants."""
    fingerprint = target.get("volume_identity_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 16 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        fingerprint = None
    return {
        "container": target.get("container"),
        "supervisor_port": target.get("supervisor_port"),
        "supervisor_volume_verified": bool(target.get("supervisor_volume_verified")),
        "volume_identity_verified": bool(target.get("volume_identity_verified")),
        "volume_identity_fingerprint": fingerprint,
    }


def supervisor_options_report(options: dict) -> dict:
    """Expose only option presence; values stay in memory for comparison."""
    if not isinstance(options, dict):
        raise RuntimeError("Local App options were not returned as an object")
    fields = (
        "gateway_token", "jev_endpoint", "jev_api_key", "privacy_mode",
        "profile_refresh_minutes", "fallback_provider", "fallback_endpoint",
        "fallback_model", "fallback_api_key",
    )
    return {
        "options_present": bool(options),
        "app_started": None,
        "configured_fields": {field: bool(options.get(field)) for field in fields},
    }


def target_identity_is_verified(target: dict) -> bool:
    """Require the canonical disposable target and a usable volume fingerprint."""
    fingerprint = target.get("volume_identity_fingerprint")
    return (
        target.get("container") == LOCAL_SUPERVISOR_CONTAINER
        and target.get("supervisor_port") == LOCAL_SUPERVISOR_PORT
        and target.get("supervisor_volume_verified") is True
        and target.get("volume_identity_verified") is True
        and isinstance(fingerprint, str)
        and len(fingerprint) == 16
        and all(character in "0123456789abcdef" for character in fingerprint)
    )


def validate_local_supervisor_inspect(inspect: dict) -> dict:
    """Fail closed unless Docker describes the disposable local harness."""
    if inspect.get("name") != f"/{LOCAL_SUPERVISOR_CONTAINER}":
        raise RuntimeError("Refusing non-local Supervisor container")
    if inspect.get("running") is not True:
        raise RuntimeError("Local Supervisor container is not running")

    bindings = (inspect.get("port_bindings") or {}).get("80/tcp")
    if not isinstance(bindings, list) or not any(
        str(binding.get("HostPort")) == str(LOCAL_SUPERVISOR_PORT)
        and binding.get("HostIp", "") in {"", "127.0.0.1", "::1"}
        for binding in bindings
        if isinstance(binding, dict)
    ):
        raise RuntimeError("Refusing a Supervisor host that is not the disposable local port")

    mounts = inspect.get("mounts") or []
    supervisor_mounts = [
        mount for mount in mounts
        if isinstance(mount, dict) and mount.get("Destination") == LOCAL_SUPERVISOR_VOLUME_DESTINATION
    ]
    if len(supervisor_mounts) != 1:
        raise RuntimeError("Refusing an unverified local Supervisor volume")
    mount = supervisor_mounts[0]
    volume_name = mount.get("Name")
    volume_source = mount.get("Source")
    if (
        mount.get("Type") != "volume"
        or not isinstance(volume_name, str)
        or not volume_name
        or not isinstance(volume_source, str)
        or not volume_source.endswith(f"/volumes/{volume_name}/_data")
        or mount.get("RW") is not True
    ):
        raise RuntimeError("Refusing an unverified local Supervisor volume")
    volume_identity_fingerprint = hashlib.sha256(
        f"{volume_name}\0{volume_source}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "container": LOCAL_SUPERVISOR_CONTAINER,
        "supervisor_port": LOCAL_SUPERVISOR_PORT,
        "supervisor_volume_verified": True,
        "volume_identity_verified": True,
        "volume_identity_fingerprint": volume_identity_fingerprint,
    }


def bounded_timeout(requested: float, maximum: float) -> float:
    """Clamp every external operation to a positive, finite timeout."""
    try:
        value = float(requested)
    except (TypeError, ValueError):
        raise RuntimeError("timeout must be numeric") from None
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("timeout must be positive")
    maximum_value = float(maximum)
    if not math.isfinite(maximum_value) or maximum_value <= 0:
        raise RuntimeError("timeout maximum must be positive")
    return min(value, maximum_value)


def run_host_command(
    args: list[str],
    *,
    timeout: float,
    input_text: str | None = None,
) -> str:
    """Run a local harness command without exposing stderr or credentials."""
    try:
        result = subprocess.run(
            args,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=bounded_timeout(timeout, RESTART_CYCLE_TIMEOUT_SECONDS),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"bounded local command timed out: {args[0]}") from None
    if result.returncode != 0:
        raise RuntimeError(f"bounded local command failed: {args[0]}")
    return result.stdout


def inspect_local_supervisor() -> dict:
    """Read only non-secret Docker metadata and verify the local volume."""
    template = (
        "{{json .Name}}\n{{json .State.Running}}\n"
        "{{json .HostConfig.PortBindings}}\n{{json .Mounts}}"
    )
    output = run_host_command(
        ["docker", "inspect", "--format", template, LOCAL_SUPERVISOR_CONTAINER],
        timeout=HOST_COMMAND_TIMEOUT_SECONDS,
    )
    lines = output.splitlines()
    if len(lines) != 4:
        raise RuntimeError("Docker returned incomplete local Supervisor metadata")
    try:
        inspect = {
            "name": json.loads(lines[0]),
            "running": json.loads(lines[1]),
            "port_bindings": json.loads(lines[2]),
            "mounts": json.loads(lines[3]),
        }
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError("Docker returned invalid local Supervisor metadata") from None
    evidence = validate_local_supervisor_inspect(inspect)
    run_host_command(
        [
            "docker", "exec", LOCAL_SUPERVISOR_CONTAINER, "sh", "-c",
            "test -d /mnt/supervisor && test -d /mnt/supervisor/homeassistant",
        ],
        timeout=HOST_COMMAND_TIMEOUT_SECONDS,
    )
    return evidence


def run_core_fixture_command(command: str) -> dict:
    """Reuse the Core-side lifecycle command and reduce it again at the edge."""
    if command != "lifecycle":
        raise RuntimeError("Host-side lifecycle wrapper only permits the lifecycle command")
    output = run_host_command(
        [
            "docker", "exec", "-i", LOCAL_SUPERVISOR_CONTAINER,
            "docker", "exec", "-i", LOCAL_CORE_CONTAINER,
            "python3", "-", command,
        ],
        timeout=RESTART_ACTION_TIMEOUT_SECONDS,
        input_text=Path(__file__).read_text(encoding="utf-8"),
    )
    try:
        report = json.loads(output)
    except json.JSONDecodeError:
        raise RuntimeError("Local Core lifecycle command returned invalid evidence") from None
    return safe_lifecycle_evidence(report)


def read_local_app_options() -> tuple[dict, dict]:
    """Return safe App-option evidence and a private in-memory comparison copy."""
    output = run_host_command(
        [
            "docker", "exec", LOCAL_SUPERVISOR_CONTAINER,
            "ha", "apps", "info", "--raw-json", LOCAL_APP_SLUG,
        ],
        timeout=HOST_COMMAND_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(output)
        data = payload["data"]
        options = data["options"]
        app_state = data["state"]
    except (KeyError, TypeError, json.JSONDecodeError):
        raise RuntimeError("Local App options were not available") from None
    report = supervisor_options_report(options)
    report["app_state"] = app_state
    report["app_started"] = app_state == "started"
    return report, dict(options)


def startup_check() -> dict:
    """Capture safe startup evidence without changing the local environment."""
    target = inspect_local_supervisor()
    options, _private_options = read_local_app_options()
    lifecycle = run_core_fixture_command("lifecycle")
    ready = (
        target_identity_is_verified(target)
        and lifecycle["config_entry"]["domain"] == "ha_switchboard"
        and lifecycle["config_entry"].get("has_gateway_token") is True
        and lifecycle["core"]["conversation_agent_present"]
        and lifecycle["core"].get("fixture_entity_count", 0) > 0
        and valid_fixture_identity_fingerprint(
            lifecycle["core"].get("fixture_identity_fingerprint")
        )
        and lifecycle_profile_is_settled(lifecycle)
        and options["options_present"]
        and options.get("configured_fields", {}).get("gateway_token") is True
        and options["app_started"] is True
    )
    if not ready:
        raise RuntimeError("Local startup evidence is incomplete")
    return {
        "command": "startup",
        "mode": "read_only",
        "target": safe_target_evidence(target),
        "options": options,
        "lifecycle": lifecycle,
        "ready": True,
    }


def wait_for_local_component(component: str, *, timeout: float = RESTART_WAIT_SECONDS) -> None:
    """Check one local Supervisor-managed component once within a deadline.

    Supervisor's restart command is the synchronization boundary for this
    disposable probe.  A second status read is useful evidence, but retrying
    it in a loop can turn a failed restart into an unbounded readiness poll.
    """
    if component not in {"app", "core"}:
        raise RuntimeError(f"unsupported local component: {component}")
    command = [
        "docker", "exec", LOCAL_SUPERVISOR_CONTAINER,
        "ha", "apps", "info", "--raw-json", LOCAL_APP_SLUG,
    ] if component == "app" else [
        "docker", "exec", LOCAL_SUPERVISOR_CONTAINER,
        "ha", "core", "info", "--raw-json",
    ]
    output = run_host_command(
        command,
        timeout=min(HOST_COMMAND_TIMEOUT_SECONDS, bounded_timeout(timeout, RESTART_WAIT_SECONDS)),
    )
    try:
        payload = json.loads(output)
        state = payload["data"]["state"]
    except (KeyError, TypeError, json.JSONDecodeError):
        raise RuntimeError(f"local {component} readiness evidence was invalid") from None
    expected = "started" if component == "app" else "running"
    if state != expected:
        raise RuntimeError(f"local {component} was not ready after the bounded restart check")


def restart_cycle(*, allow_restart: bool) -> dict:
    """Run a read-only lifecycle check or an explicitly authorized local cycle."""
    target = inspect_local_supervisor()
    before_lifecycle = run_core_fixture_command("lifecycle")
    before_options, before_options_private = read_local_app_options()
    if not target_identity_is_verified(target):
        raise RuntimeError("Refusing restart without verified local Supervisor volume identity")
    # Keep the authorization boundary type-strict.  The CLI supplies a real
    # bool, but this function is also imported by tests and local tooling; a
    # truthy string or integer must never accidentally authorize restarts.
    if allow_restart is not True:
        return {
            "command": "restart-cycle",
            "mode": "read_only",
            "restart_requested": False,
            "restart_performed": False,
            "target": safe_target_evidence(target),
            "before": before_lifecycle,
            "options": before_options,
            "next_action": "rerun with --allow-restart only for the disposable local harness",
        }

    if before_lifecycle["config_entry"]["domain"] != "ha_switchboard":
        raise RuntimeError("Refusing restart without the existing Switchboard config entry")
    if before_lifecycle["config_entry"].get("has_gateway_token") is not True:
        raise RuntimeError("Refusing restart without the existing Switchboard gateway token")
    if not before_lifecycle["core"]["conversation_agent_present"]:
        raise RuntimeError("Refusing restart without the existing Switchboard conversation agent")
    if (
        not before_options["options_present"]
        or before_options.get("app_started") is not True
        or before_options.get("configured_fields", {}).get("gateway_token") is not True
    ):
        raise RuntimeError("Refusing restart without existing local App options")
    if before_lifecycle["core"].get("fixture_entity_count", 0) <= 0:
        raise RuntimeError("Refusing restart without existing fixture entities")
    if not valid_fixture_identity_fingerprint(
        before_lifecycle["core"].get("fixture_identity_fingerprint")
    ):
        raise RuntimeError("Refusing restart without verified fixture identity")
    if (
        before_lifecycle["gateway"].get("status") != "active"
        or not before_lifecycle["gateway"].get("has_revision")
        or before_lifecycle["gateway"].get("pending_section_count") != 0
        or before_lifecycle["gateway"].get("pending_invalidation_count") != 0
    ):
        raise RuntimeError("Refusing restart with an unsettled Switchboard profile")

    deadline = time.monotonic() + RESTART_CYCLE_TIMEOUT_SECONDS

    def remaining(maximum: float) -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise RuntimeError("local restart cycle exceeded its bounded deadline")
        return min(maximum, seconds)

    run_host_command(
        ["docker", "exec", LOCAL_SUPERVISOR_CONTAINER, "ha", "apps", "restart", LOCAL_APP_SLUG],
        timeout=remaining(RESTART_ACTION_TIMEOUT_SECONDS),
    )
    wait_for_local_component("app", timeout=remaining(RESTART_WAIT_SECONDS))
    after_app_target = inspect_local_supervisor()
    if not target_identity_is_verified(after_app_target) or safe_target_evidence(after_app_target) != safe_target_evidence(target):
        raise RuntimeError("Refusing to continue after local Supervisor volume identity changed")
    after_app_lifecycle = run_core_fixture_command("lifecycle")
    after_app_options, after_app_options_private = read_local_app_options()
    app_restart_profile_settled = lifecycle_profile_is_settled(after_app_lifecycle)
    app_restart_preserved = (
        before_lifecycle["config_entry"] == after_app_lifecycle["config_entry"]
        and before_lifecycle["core"] == after_app_lifecycle["core"]
        and before_lifecycle["gateway"] == after_app_lifecycle["gateway"]
        and before_options == after_app_options
        and before_options_private == after_app_options_private
        and app_restart_profile_settled
    )
    if not app_restart_preserved:
        raise RuntimeError(
            "Local App restart did not preserve config entry and fixture anchors; settled profile missing"
        )

    core_restart_output = run_host_command(
        ["docker", "exec", LOCAL_SUPERVISOR_CONTAINER, "ha", "core", "restart", "--raw-json"],
        timeout=remaining(RESTART_ACTION_TIMEOUT_SECONDS),
    )
    # Supervisor normally returns JSON for --raw-json.  Keep compatibility
    # with wrappers that intentionally suppress successful stdout, but reject
    # any non-empty malformed or unsuccessful response.
    if core_restart_output.strip():
        try:
            core_restart_result = json.loads(core_restart_output)
        except json.JSONDecodeError:
            raise RuntimeError("Local Core restart returned invalid bounded evidence") from None
        if not isinstance(core_restart_result, dict) or core_restart_result.get("result") != "ok":
            raise RuntimeError("Local Core restart did not report success")
    wait_for_local_component("core", timeout=remaining(RESTART_WAIT_SECONDS))
    after_target = inspect_local_supervisor()
    if not target_identity_is_verified(after_target) or safe_target_evidence(after_target) != safe_target_evidence(target):
        raise RuntimeError("Refusing to report success after local Supervisor volume identity changed")
    after_lifecycle = run_core_fixture_command("lifecycle")
    after_options, after_options_private = read_local_app_options()

    preserved = {
        "options": before_options_private == after_options_private,
        "app_restart_preserved": app_restart_preserved,
        "config_entry": before_lifecycle["config_entry"] == after_lifecycle["config_entry"],
        "fixture_count": before_lifecycle["core"]["fixture_entity_count"] == after_lifecycle["core"]["fixture_entity_count"],
        "fixture_identity": (
            before_lifecycle["core"].get("fixture_identity_fingerprint")
            == after_lifecycle["core"].get("fixture_identity_fingerprint")
        ),
        "conversation_agent": after_lifecycle["core"]["conversation_agent_present"],
        "profile_recovered": lifecycle_profile_is_settled(after_lifecycle),
        "options_started": after_options.get("options_present") is True
        and after_options.get("app_started") is True,
        "volume_identity": (
            safe_target_evidence(after_app_target) == safe_target_evidence(target)
            and safe_target_evidence(after_target) == safe_target_evidence(target)
        ),
    }
    return {
        "command": "restart-cycle",
        "mode": "opt_in",
        "restart_requested": True,
        "restart_performed": True,
        "target": safe_target_evidence(target),
        "before": before_lifecycle,
        "after_app_restart": after_app_lifecycle,
        "after": after_lifecycle,
        "options": after_options,
        "preserved": preserved,
        "complete": all(preserved.values()),
    }


def temporary_token() -> str:
    # This local dev Core already has a human admin account. Its existing
    # refresh token's signing key can mint a short access token in memory.
    import jwt

    data = json.loads(Path("/config/.storage/auth").read_text())["data"]
    users = {user["id"]: user for user in data["users"]}
    candidates = [
        token for token in data["refresh_tokens"]
        if token["token_type"] == "long_lived_access_token"
        and users.get(token["user_id"], {}).get("is_owner")
    ]
    if len(candidates) != 1:
        raise SystemExit("Expected one existing local owner token; no auth change made")
    token = candidates[0]
    now = int(time.time())
    return jwt.encode(
        {"iss": token["id"], "iat": now, "exp": now + 300},
        token["jwt_key"],
        algorithm="HS256",
    )


def owner_user_id() -> str:
    """Return the existing owner's ID in memory without emitting auth data."""
    try:
        data = json.loads(Path("/config/.storage/auth").read_text())["data"]
        users = {user["id"]: user for user in data["users"]}
        candidates = [
            token for token in data["refresh_tokens"]
            if token["token_type"] == "long_lived_access_token"
            and users.get(token["user_id"], {}).get("is_owner")
        ]
        user_id = candidates[0]["user_id"] if len(candidates) == 1 else None
    except (KeyError, TypeError, json.JSONDecodeError, OSError):
        user_id = None
    if not isinstance(user_id, str) or not user_id:
        raise RuntimeError("existing local owner identity could not be verified")
    return user_id


def access_token_user_id(access_token: str) -> str:
    """Map an already-authenticated HA access token to its existing user."""
    import jwt

    try:
        claims = jwt.decode(access_token, options={"verify_signature": False})
        issuer = claims.get("iss")
        data = json.loads(Path("/config/.storage/auth").read_text())["data"]
        matches = [
            item for item in data["refresh_tokens"]
            if item.get("id") == issuer
        ]
        user_id = matches[0].get("user_id") if len(matches) == 1 else None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        user_id = None
    if not isinstance(user_id, str) or not user_id:
        raise RuntimeError("supplied second-user identity could not be verified")
    return user_id


def follow_up_opt_ins(environ: Mapping[str, str] | None = None) -> tuple[str | None, bool]:
    """Read optional follow-up gates only after explicit live-probe authorization."""
    source = os.environ if environ is None else environ
    if source.get(FOLLOW_UP_RUN_OPT_IN_ENV) != "1":
        return None, False
    second_user_token = source.get(FOLLOW_UP_SECOND_USER_ACCESS_TOKEN_ENV, "").strip() or None
    natural_expiry = source.get(FOLLOW_UP_NATURAL_EXPIRY_ENV) == "1"
    return second_user_token, natural_expiry


async def authenticate_websocket(ws: aiohttp.ClientWebSocketResponse, token: str) -> None:
    """Authenticate one Core WebSocket without exposing auth response details."""
    hello = await ws.receive_json(timeout=ASSIST_EVENT_TIMEOUT_SECONDS)
    if hello.get("type") != "auth_required":
        raise RuntimeError("Core WebSocket did not request authentication")
    await ws.send_json({"type": "auth", "access_token": token})
    response = await ws.receive_json(timeout=ASSIST_EVENT_TIMEOUT_SECONDS)
    if response.get("type") != "auth_ok":
        raise RuntimeError("Core rejected the supplied follow-up access token")


async def wait_for_natural_continuation_expiry() -> int:
    """Wait for the real continuation TTL, subject to a hard upper bound."""
    wait_seconds = FOLLOW_UP_CONTINUATION_TTL_SECONDS + FOLLOW_UP_NATURAL_EXPIRY_SAFETY_SECONDS
    if wait_seconds > FOLLOW_UP_NATURAL_EXPIRY_MAX_WAIT_SECONDS:
        raise RuntimeError("natural continuation expiry exceeds the bounded wait")
    try:
        await asyncio.wait_for(
            asyncio.sleep(wait_seconds),
            timeout=FOLLOW_UP_NATURAL_EXPIRY_MAX_WAIT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise RuntimeError("natural continuation expiry exceeded the bounded wait") from None
    return wait_seconds


async def websocket_call(ws: aiohttp.ClientWebSocketResponse, message: dict) -> dict:
    await ws.send_json(message)
    deadline = time.monotonic() + WEBSOCKET_CALL_TIMEOUT_SECONDS
    for _ in range(WEBSOCKET_CALL_MAX_EVENTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        received = await ws.receive_json(timeout=min(ASSIST_EVENT_TIMEOUT_SECONDS, remaining))
        if received.get("id") == message["id"] and received.get("type") in {"result", "event"}:
            return received
    raise RuntimeError("Core WebSocket call did not complete within the bounded deadline")


def _conversation_id_from_event(value: Any, *, depth: int = 0) -> str | None:
    """Find only the bounded Assist conversation identifier in an event."""
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        candidate = value.get("conversation_id")
        if isinstance(candidate, str) and candidate:
            return candidate
        for item in value.values():
            found = _conversation_id_from_event(item, depth=depth + 1)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value[:ASSIST_MAX_EVENTS]:
            found = _conversation_id_from_event(item, depth=depth + 1)
            if found:
                return found
    return None


async def assist_pipeline_turn(
    ws: aiohttp.ClientWebSocketResponse,
    pipeline_id: str,
    text: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Run one bounded Assist turn and retain only safe lifecycle evidence."""
    message_id = int(time.monotonic() * 1000) % 900_000 + 100
    await ws.send_json({
        "id": message_id,
        "type": "assist_pipeline/run",
        "pipeline": pipeline_id,
        "start_stage": "intent",
        "end_stage": "intent",
        "conversation_id": conversation_id,
        "input": {"text": text},
    })
    deadline = time.monotonic() + ASSIST_FOLLOW_UP_TIMEOUT_SECONDS
    event_types: list[str] = []
    observed_conversation_id: str | None = None
    continuation_requested: bool | None = None
    for _ in range(ASSIST_MAX_EVENTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            event = await ws.receive_json(timeout=min(ASSIST_EVENT_TIMEOUT_SECONDS, remaining))
        except asyncio.TimeoutError:
            break
        if event.get("id") != message_id:
            continue
        observed_conversation_id = observed_conversation_id or _conversation_id_from_event(event)
        if event.get("type") == "result":
            if not event.get("success"):
                raise RuntimeError("Assist follow-up pipeline returned an error")
            continue
        if event.get("type") != "event":
            continue
        event_data = event.get("event", {})
        event_type = str(event_data.get("type", "unknown"))
        event_types.append(event_type)
        if event_type == "intent-end":
            intent_output = (event_data.get("data") or {}).get("intent_output") or {}
            value = intent_output.get("continue_conversation")
            continuation_requested = value if isinstance(value, bool) else None
        if event_type in {"run-end", "error"}:
            if event_type == "error":
                raise RuntimeError("Assist follow-up pipeline emitted an error")
            return {
                "conversation_id": observed_conversation_id,
                "conversation_id_observed": observed_conversation_id is not None,
                "requested_conversation_id": conversation_id,
                "event_count": len(event_types),
                "continuation_requested": continuation_requested,
                "completed": True,
            }
    raise RuntimeError("Assist follow-up did not complete within the bounded deadline")


async def native_assist_evidence(
    ws: aiohttp.ClientWebSocketResponse,
    pipeline_id: str,
    *,
    text: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Run one bounded native-intent Assist turn and retain safe evidence."""
    message_id = int(time.monotonic() * 1000) % 900_000 + 100
    await ws.send_json({
        "id": message_id,
        "type": "assist_pipeline/run",
        "pipeline": pipeline_id,
        "start_stage": "intent",
        "end_stage": "intent",
        "conversation_id": conversation_id,
        "input": {"text": text},
    })
    deadline = time.monotonic() + ASSIST_FOLLOW_UP_TIMEOUT_SECONDS
    event_types: list[str] = []
    speech_present = False
    observed_conversation_id: str | None = None
    for _ in range(ASSIST_MAX_EVENTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        event = await ws.receive_json(timeout=min(ASSIST_EVENT_TIMEOUT_SECONDS, remaining))
        if event.get("id") != message_id:
            continue
        observed_conversation_id = observed_conversation_id or _conversation_id_from_event(event)
        if event.get("type") == "result":
            if not event.get("success"):
                raise RuntimeError("Native Assist pipeline returned an error")
            continue
        if event.get("type") != "event":
            continue
        event_data = event.get("event") or {}
        event_type = str(event_data.get("type", "unknown"))
        event_types.append(event_type)
        if event_type == "intent-end":
            intent_output = (event_data.get("data") or {}).get("intent_output") or {}
            speech = ((intent_output.get("response") or {}).get("speech") or {}).get("plain")
            speech_present = isinstance(speech, Mapping) and bool(speech.get("speech"))
        if event_type == "error":
            raise RuntimeError("Native Assist pipeline emitted an error")
        if event_type == "run-end":
            return {
                "completed": True,
                "event_types": event_types,
                "speech_present": speech_present,
                "conversation_id_observed": observed_conversation_id is not None,
                "conversation_id_reused": (
                    observed_conversation_id == conversation_id
                    if observed_conversation_id is not None
                    else None
                ),
            }
    raise RuntimeError("Native Assist pipeline did not complete within the bounded deadline")


async def main(command: str) -> None:
    if command == "failures":
        print(json.dumps(DETERMINISTIC_FAILURES, sort_keys=True))
        return
    if command == "verify":
        entries = json.loads(Path("/config/.storage/core.config_entries").read_text(encoding="utf-8"))["data"]["entries"]
        print(json.dumps(config_entry_report(entries), sort_keys=True))
        return
    import aiohttp

    token = temporary_token()
    entries = json.loads(Path("/config/.storage/core.config_entries").read_text(encoding="utf-8"))["data"]["entries"]
    entry_report = config_entry_report(entries)
    if command in {"profile", "scan", "lifecycle"}:
        gateway_url, gateway_token = gateway_config(entries)
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=GATEWAY_TIMEOUT_SECONDS)
        ) as gateway:
            before_status, before = await gateway_request(
                gateway, gateway_url, gateway_token, "GET", "/v1/profile/status"
            )
            if before_status != 200:
                raise RuntimeError(f"Gateway profile status returned HTTP {before_status}")
            if command == "profile":
                print("Gateway profile:", profile_status_report(before))
                return
            if command == "scan":
                request_status, _request_body = await gateway_request(
                    gateway, gateway_url, gateway_token, "POST", "/v1/profile/scan", {}
                )
                if request_status != 202:
                    raise RuntimeError(f"Gateway manual scan returned HTTP {request_status}")
                after_status, after = request_status, before
                settled = False
                polls = 0
                deadline = time.monotonic() + SCAN_STATUS_WINDOW_SECONDS
                for polls in range(1, SCAN_POLL_ATTEMPTS + 1):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    await asyncio.sleep(min(SCAN_POLL_INTERVAL_SECONDS, remaining))
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    after_status, after = await gateway_request(
                        gateway, gateway_url, gateway_token, "GET", "/v1/profile/status",
                        timeout_seconds=remaining,
                    )
                    if after_status != 200:
                        raise RuntimeError(f"Gateway profile status after scan returned HTTP {after_status}")
                    if profile_is_settled(after):
                        settled = True
                        break
                report = {
                    "request_http_status": request_status,
                    "before": profile_status_report(before),
                    "after": profile_status_report(after),
                    "poll_attempts": polls,
                    "completion": "settled" if settled else "timeout",
                    "invariants": scan_invariant_report(before, after, request_status, settled),
                }
                print(json.dumps(report, sort_keys=True))
                if not report["invariants"]["complete"]:
                    raise SystemExit("Manual scan did not preserve a settled profile within the bounded wait")
                return
            async with aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=GATEWAY_TIMEOUT_SECONDS),
            ) as core:
                response = await core.get(BASE + "/api/states")
                if response.status != 200:
                    raise RuntimeError(f"Home Assistant states returned HTTP {response.status}")
                states = {item["entity_id"]: item for item in await response.json()}
            print(json.dumps(lifecycle_report(entry_report, states, before), sort_keys=True))
            return
    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {token}"},
        timeout=aiohttp.ClientTimeout(total=GATEWAY_TIMEOUT_SECONDS),
    ) as session:
        async with session.get(BASE + "/api/states") as response:
            response.raise_for_status()
            states = {item["entity_id"]: item for item in await response.json()}
        fixtures = sorted(entity_id for entity_id in states if "switchboard_fixture" in entity_id)
        agent = states.get(AGENT)
        if command != "native":
            diagnostic_sensors = [
                item for name, item in states.items()
                if name.startswith("sensor.")
                and any(part in name for part in ("switchboard", "gateway_ready", "capabilities", "last_scan"))
            ]
            # Keep fixture command output safe to paste into issues and release
            # evidence.  Raw entity IDs and per-entity states belong in the
            # Core runtime, never in host-side harness output.
            print(json.dumps({
                "agent_state": None if agent is None else agent["state"],
                "fixture_entity_count": len(fixtures),
                "diagnostic_sensor_count": len(diagnostic_sensors),
            }, sort_keys=True))
        if command == "exercise":
            results = []
            for case in operation_matrix_plan():
                domain = case["service_domain"]
                service = case["service"]
                entity_id = case["entity_id"]
                payload = {"entity_id": entity_id, **case["service_data"]}
                async with session.get(BASE + f"/api/states/{entity_id}") as response:
                    response.raise_for_status()
                    before = await response.json()
                async with session.post(BASE + f"/api/services/{domain}/{service}", json=payload) as response:
                    response.raise_for_status()
                    await response.read()
                await asyncio.sleep(0.2)
                async with session.get(BASE + f"/api/states/{entity_id}") as response:
                    response.raise_for_status()
                    state = await response.json()
                actual = state["state"]
                expected = case["expected_state"]
                if case["operation"] == "toggle":
                    previous = str(before.get("state", "unknown"))
                    expected = "off" if previous in {"on", "open", "unlocked", "playing"} else "on"
                if expected is not None and actual != expected:
                    raise RuntimeError(f"Mock service state mismatch: {entity_id} {service} => {actual}")
                if case["operation"] == "set_temperature" and abs(float(state["attributes"]["temperature"]) - 21) > 0.2:
                    raise RuntimeError("Mock thermostat target temperature did not update")
                if case["operation"] == "set_brightness" and abs(float(state["attributes"]["brightness"]) * 100 / 255 - 40) > 2:
                    raise RuntimeError("Mock light brightness did not update")
                if case["operation"] == "set_volume" and abs(float(state["attributes"]["volume_level"]) - 0.25) > 0.02:
                    raise RuntimeError("Mock media player volume did not update")
                results.append({
                    "domain": case["domain"],
                    "operation": case["operation"],
                    "service": service,
                    "verified": True,
                    "state": actual,
                })
            print(json.dumps({
                "command": "exercise",
                "matrix_rows": len(results),
                "verified_rows": sum(item["verified"] for item in results),
                "rows": results,
            }, sort_keys=True))
            return

        async with session.ws_connect(BASE.replace("http", "ws") + "/api/websocket") as ws:
            await authenticate_websocket(ws, token)
            if command == "native":
                listing = await websocket_call(ws, {"id": 1, "type": "assist_pipeline/pipeline/list"})
                if not listing.get("success"):
                    raise RuntimeError("Could not list local Assist pipelines")
                pipelines = listing["result"]["pipelines"]
                native_pipelines = [
                    item for item in pipelines
                    if item.get("name") == "Switchboard"
                    and item.get("conversation_engine") == AGENT
                ]
                if len(native_pipelines) != 1:
                    raise RuntimeError(
                        "Expected exactly one Switchboard pipeline using the Switchboard conversation agent"
                    )
                pipeline = native_pipelines[0]
                if pipeline.get("prefer_local_intents") is not True:
                    raise RuntimeError("Switchboard pipeline does not prefer local intents")

                entity_id = "light.switchboard_fixture_light"

                async def state_of(entity: str) -> str:
                    async with session.get(BASE + f"/api/states/{entity}") as response:
                        response.raise_for_status()
                        payload = await response.json()
                    return str(payload.get("state", "unknown"))

                before_state = await state_of(entity_id)
                if before_state not in {"on", "off"}:
                    raise RuntimeError(f"Fixture light has unexpected state: {before_state}")

                gateway_url, gateway_token = gateway_config(entries)
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=GATEWAY_TIMEOUT_SECONDS)
                ) as gateway:
                    before_status, before_diagnostics = await gateway_request(
                        gateway,
                        gateway_url,
                        gateway_token,
                        "GET",
                        "/v1/diagnostics?limit=1&route_class=jev",
                    )
                    if before_status != 200:
                        raise RuntimeError(
                            f"Gateway diagnostics returned HTTP {before_status} before native Assist"
                        )
                    native_result = None
                    native_after_state = None
                    try:
                        native_result = await native_assist_evidence(
                            ws,
                            pipeline["id"],
                            text="Turn off the Switchboard Fixture light.",
                            conversation_id=NATIVE_FAST_PATH_CONVERSATION,
                        )
                        native_after_state = await state_of(entity_id)
                    finally:
                        restore_service = "turn_on" if before_state == "on" else "turn_off"
                        async with session.post(
                            BASE + f"/api/services/light/{restore_service}",
                            json={"entity_id": entity_id},
                        ) as response:
                            response.raise_for_status()
                            await response.read()
                    after_state = await state_of(entity_id)
                    after_status, after_diagnostics = await gateway_request(
                        gateway,
                        gateway_url,
                        gateway_token,
                        "GET",
                        "/v1/diagnostics?limit=1&route_class=jev",
                    )
                if after_status != 200:
                    raise RuntimeError(
                        f"Gateway diagnostics returned HTTP {after_status} after native Assist"
                    )
                before_total = before_diagnostics.get("total")
                after_total = after_diagnostics.get("total")
                if not isinstance(before_total, int) or not isinstance(after_total, int):
                    raise RuntimeError("Gateway diagnostics did not return a bounded event count")
                provider_delta = after_total - before_total
                report = {
                    "command": "native",
                    "pipeline": {
                        "name": "Switchboard",
                        "conversation_engine": AGENT,
                        "prefer_local_intents": True,
                    },
                    "assist": native_result,
                    "fixture_state": {
                        "changed_to_off": native_after_state == "off",
                        "restored": after_state == before_state,
                    },
                    "jev_diagnostic_delta": provider_delta,
                    "native_provider_bypass": "proved" if provider_delta == 0 else "failed",
                }
                print(json.dumps(report, sort_keys=True))
                if (
                    not native_result
                    or not native_result["completed"]
                    or not native_result["speech_present"]
                    or native_result.get("conversation_id_reused") is False
                    or native_after_state != "off"
                    or after_state != before_state
                    or provider_delta != 0
                ):
                    raise SystemExit("Native Assist fast-path evidence failed")
                return
            if command == "area":
                existing = await websocket_call(ws, {"id": 10, "type": "config/area_registry/list"})
                if not existing.get("success"):
                    raise RuntimeError("Could not list local areas")
                areas = [item for item in existing["result"] if item["name"] == FIXTURE_AREA]
                if not areas:
                    created = await websocket_call(ws, {
                        "id": 11, "type": "config/area_registry/create", "name": FIXTURE_AREA,
                    })
                    if not created.get("success"):
                        raise RuntimeError("Could not create local fixture area")
                    areas = [created["result"]]
                area_id = areas[0]["area_id"]
                registry = await websocket_call(ws, {"id": 12, "type": "config/entity_registry/list"})
                if not registry.get("success"):
                    raise RuntimeError("Could not list local entity registry")
                supported, skipped = registry_supported_entities(registry["result"])
                for index, entity_id in enumerate(supported, start=13):
                    updated = await websocket_call(ws, {
                        "id": index, "type": "config/entity_registry/update",
                        "entity_id": entity_id, "area_id": area_id,
                    })
                    if not updated.get("success"):
                        raise RuntimeError(f"Could not assign local fixture area to {entity_id}")
                print(json.dumps({
                    "area": areas[0]["name"],
                    "assigned_entities": len(supported),
                    "skipped_count": len(skipped),
                    "skipped_native_core_only": list(skipped),
                }, sort_keys=True))
                return
            if command == "metadata":
                areas = await websocket_call(ws, {"id": 30, "type": "config/area_registry/list"})
                if not areas.get("success"):
                    raise RuntimeError("Could not list local areas")
                fixture_areas = [item for item in areas["result"] if item["name"] == FIXTURE_AREA]
                if not fixture_areas:
                    created = await websocket_call(ws, {
                        "id": 31, "type": "config/area_registry/create", "name": FIXTURE_AREA,
                    })
                    if not created.get("success"):
                        raise RuntimeError("Could not create local fixture area")
                    fixture_areas = [created["result"]]
                labels = await websocket_call(ws, {"id": 32, "type": "config/label_registry/list"})
                if not labels.get("success"):
                    raise RuntimeError("Could not list local labels")
                label_ids = {}
                for offset, name in enumerate(FIXTURE_LABELS, start=33):
                    found = [item for item in labels["result"] if item["name"] == name]
                    if not found:
                        created = await websocket_call(ws, {
                            "id": offset, "type": "config/label_registry/create", "name": name,
                        })
                        if not created.get("success"):
                            raise RuntimeError(f"Could not create local label: {name}")
                        found = [created["result"]]
                    label_ids[name] = found[0]["label_id"]
                registry = await websocket_call(ws, {"id": 34, "type": "config/entity_registry/list"})
                if not registry.get("success"):
                    raise RuntimeError("Could not list local entity registry")
                supported, skipped = registry_supported_entities(registry["result"])
                for index, entity_id in enumerate(supported, start=40):
                    updated = await websocket_call(ws, {
                        "id": index, "type": "config/entity_registry/update", "entity_id": entity_id,
                        "area_id": fixture_areas[0]["area_id"],
                        "labels": list(label_ids.values()),
                    })
                    if not updated.get("success"):
                        raise RuntimeError(f"Could not assign local metadata to {entity_id}")
                print(json.dumps({
                    "area": FIXTURE_AREA,
                    "labels": sorted(label_ids),
                    "assigned_entities": len(supported),
                    "skipped_count": len(skipped),
                    "skipped_native_core_only": list(skipped),
                }, sort_keys=True))
                return
            if command == "expose":
                allowed = (
                    "light.switchboard_fixture_light",
                    "light.switchboard_fixture_lamp",
                    "switch.switchboard_fixture_switch",
                    "fan.switchboard_fixture_fan",
                    "cover.switchboard_fixture_cover",
                    "cover.switchboard_fixture_garage",
                    "lock.switchboard_fixture_lock",
                    "climate.switchboard_fixture_thermostat",
                    "media_player.switchboard_fixture_player",
                    "sensor.switchboard_fixture_temperature_reading",
                    "binary_sensor.switchboard_fixture_motion",
                )
                missing = set(allowed) - states.keys()
                if missing:
                    raise RuntimeError(f"Local fixture entities missing: {sorted(missing)}")
                response = await websocket_call(ws, {
                    "id": 20, "type": "homeassistant/expose_entity",
                    "assistants": ["conversation"], "entity_ids": list(allowed),
                    "should_expose": True,
                })
                if not response.get("success"):
                    raise RuntimeError("Could not expose local fixture entities to Assist")
                hidden = await websocket_call(ws, {
                    "id": 22, "type": "homeassistant/expose_entity",
                    "assistants": ["conversation"],
                    "entity_ids": [
                        "switch.switchboard_fixture_heater",
                        "script.switchboard_fixture_evening",
                        "scene.switchboard_fixture_calm",
                    ],
                    "should_expose": False,
                })
                if not hidden.get("success"):
                    raise RuntimeError("Could not hide unsupported local fixture surfaces from Assist")
                print("Exposed fixture entities to Assist:", len(allowed))
                return
            if command == "exposure":
                response = await websocket_call(ws, {
                    "id": 21, "type": "homeassistant/expose_entity/list",
                })
                if not response.get("success"):
                    raise RuntimeError("Could not read local Assist exposure")
                exposed = response["result"]["exposed_entities"]
                print("Fixture Assist exposure:", sorted(
                    name for name, assistants in exposed.items()
                    if "switchboard_fixture" in name and assistants.get("conversation")
                ))
                return
            if command == "coverage":
                response = await websocket_call(ws, {"id": 23, "type": "homeassistant/expose_entity/list"})
                if not response.get("success"):
                    raise RuntimeError("Could not read local Assist exposure")
                report = coverage_report(states, response["result"]["exposed_entities"])
                print(json.dumps(report, sort_keys=True))
                if (
                    report["missing_entities"]
                    or report["unexposed_entities"]
                    or not report["unsupported"]["complete"]
                ):
                    raise SystemExit("Fixture coverage is incomplete")
                return
            if command == "unsupported":
                response = await websocket_call(ws, {"id": 24, "type": "homeassistant/expose_entity/list"})
                if not response.get("success"):
                    raise RuntimeError("Could not read local Assist exposure")
                report = unsupported_surface_report(states, response["result"]["exposed_entities"])
                print(json.dumps(report, sort_keys=True))
                if not report["complete"]:
                    raise SystemExit("An unsupported native Core surface was exposed")
                return
            listing = await websocket_call(ws, {"id": 1, "type": "assist_pipeline/pipeline/list"})
            if not listing.get("success"):
                raise RuntimeError("Could not list local Assist pipelines")
            pipelines = listing["result"]["pipelines"]
            ours = [item for item in pipelines if item["name"] == PIPELINE_NAME]
            if command == "configure" and not ours:
                if agent is None:
                    raise RuntimeError("Switchboard conversation agent is missing")
                fields = {
                    "name": PIPELINE_NAME,
                    "language": "en",
                    "conversation_engine": AGENT,
                    "conversation_language": "en",
                    "stt_engine": None,
                    "stt_language": None,
                    "tts_engine": None,
                    "tts_language": None,
                    "tts_voice": None,
                    "wake_word_entity": None,
                    "wake_word_id": None,
                    "prefer_local_intents": False,
                }
                result = await websocket_call(ws, {"id": 2, "type": "assist_pipeline/pipeline/create", **fields})
                if not result.get("success"):
                    raise RuntimeError(f"Assist pipeline creation failed: {result.get('error', {}).get('code')}")
                ours = [result["result"]]
            print("Fixture pipeline:", [(item["id"], item["conversation_engine"]) for item in ours])
            if command == "follow-up":
                if len(ours) != 1 or ours[0]["conversation_engine"] != AGENT:
                    raise RuntimeError("Fixture pipeline is absent or points to another agent")
                conversation_id = ASSIST_FOLLOW_UP_CONVERSATION
                lock_entity = "lock.switchboard_fixture_lock"
                second_user_token, run_natural_expiry = follow_up_opt_ins()

                async def state_of(entity_id: str) -> str:
                    async with session.get(BASE + f"/api/states/{entity_id}") as response:
                        response.raise_for_status()
                        payload = await response.json()
                    return str(payload.get("state", "unknown"))

                before_state = await state_of(lock_entity)
                if before_state != "locked":
                    raise RuntimeError("fixture lock must start locked for follow-up evidence")
                first = await assist_pipeline_turn(
                    ws, ours[0]["id"],
                    "Unlock the Switchboard Fixture lock.", conversation_id,
                )
                cancelled = await assist_pipeline_turn(ws, ours[0]["id"], "No.", conversation_id)
                after_cancel_state = await state_of(lock_entity)
                replay = await assist_pipeline_turn(ws, ours[0]["id"], "Yes.", conversation_id)
                after_replay_state = await state_of(lock_entity)
                turns = (first, cancelled, replay)
                observed_ids = [item.get("conversation_id") for item in turns]
                same_id = all(item == conversation_id for item in observed_ids)
                conversation_status = (
                    "proved"
                    if same_id and first.get("continuation_requested") is True
                    else "unavailable"
                    if not any(observed_ids)
                    else "failed"
                )
                different_user = {
                    "status": "unavailable",
                    "reason": (
                        "requires a second existing HA user token and explicit "
                        "HA_SWITCHBOARD_RUN_FOLLOW_UP=1 authorization; no auth mutation is performed"
                    ),
                }
                if second_user_token is not None:
                    try:
                        if access_token_user_id(second_user_token) == owner_user_id():
                            raise RuntimeError("second-user token belongs to the existing owner")
                        cross_user_conversation = "fixture-follow-up-cross-user"
                        cross_before_state = await state_of(lock_entity)
                        cross_first = await assist_pipeline_turn(
                            ws,
                            ours[0]["id"],
                            "Unlock the Switchboard Fixture lock.",
                            cross_user_conversation,
                        )
                        async with session.ws_connect(BASE.replace("http", "ws") + "/api/websocket") as second_ws:
                            await authenticate_websocket(second_ws, second_user_token)
                            cross_follow_up = await assist_pipeline_turn(
                                second_ws,
                                ours[0]["id"],
                                "Yes.",
                                cross_user_conversation,
                            )
                        cross_after_state = await state_of(lock_entity)
                        cross_conversation_reused = all(
                            item.get("conversation_id") == cross_user_conversation
                            for item in (cross_first, cross_follow_up)
                        )
                        cross_follow_up_refused = (
                            cross_first.get("continuation_requested") is True
                            and cross_follow_up.get("continuation_requested") is False
                        )
                        cross_unchanged = cross_before_state == cross_after_state
                        different_user = {
                            "status": (
                                "proved"
                                if cross_conversation_reused and cross_follow_up_refused and cross_unchanged
                                else "failed"
                            ),
                            "conversation_reused": cross_conversation_reused,
                            "follow_up_refused": cross_follow_up_refused,
                            "state_unchanged": cross_unchanged,
                        }
                    except Exception:
                        # Never expose authentication errors, provider payloads, or
                        # Core's user/entity references in fixture evidence.
                        different_user = {
                            "status": "failed",
                            "reason": "second-user identity or follow-up did not complete within the bounded probe",
                        }

                expiry = {
                    "status": "unavailable",
                    "reason": (
                        "requires explicit HA_SWITCHBOARD_RUN_FOLLOW_UP=1 authorization and "
                        "waiting for the Core continuation TTL; covered by the bounded clock-controlled test"
                    ),
                }
                if run_natural_expiry:
                    try:
                        expiry_conversation = "fixture-follow-up-expiry"
                        expiry_before_state = await state_of(lock_entity)
                        expiry_first = await assist_pipeline_turn(
                            ws,
                            ours[0]["id"],
                            "Unlock the Switchboard Fixture lock.",
                            expiry_conversation,
                        )
                        waited_seconds = await wait_for_natural_continuation_expiry()
                        expiry_follow_up = await assist_pipeline_turn(
                            ws,
                            ours[0]["id"],
                            "Yes.",
                            expiry_conversation,
                        )
                        expiry_after_state = await state_of(lock_entity)
                        expiry_conversation_reused = all(
                            item.get("conversation_id") == expiry_conversation
                            for item in (expiry_first, expiry_follow_up)
                        )
                        expiry_follow_up_refused = (
                            expiry_first.get("continuation_requested") is True
                            and expiry_follow_up.get("continuation_requested") is False
                        )
                        expiry_unchanged = expiry_before_state == expiry_after_state
                        expiry = {
                            "status": (
                                "proved"
                                if expiry_conversation_reused and expiry_follow_up_refused and expiry_unchanged
                                else "failed"
                            ),
                            "conversation_reused": expiry_conversation_reused,
                            "follow_up_refused": expiry_follow_up_refused,
                            "state_unchanged": expiry_unchanged,
                            "wait_seconds": waited_seconds,
                        }
                    except Exception:
                        expiry = {
                            "status": "failed",
                            "reason": "natural continuation expiry did not complete within the bounded wait",
                        }

                report = {
                    "command": "follow-up",
                    "same_conversation": {
                        "status": conversation_status,
                        "conversation_id_reused": same_id,
                        "reason": (
                            None
                            if conversation_status == "proved"
                            else "Core Assist events did not echo the requested conversation identifier"
                        ),
                    },
                    "cancellation": {
                        "status": (
                            "proved"
                            if before_state == after_cancel_state
                            and cancelled.get("continuation_requested") is False
                            else "failed"
                        ),
                    "fixture_lock_unchanged": before_state == after_cancel_state,
                    "continuation_requested": cancelled.get("continuation_requested"),
                },
                "replay": {
                    "status": (
                        "proved"
                        if after_cancel_state == after_replay_state
                        and replay.get("continuation_requested") is False
                        else "failed"
                    ),
                    "fixture_lock_unchanged": after_cancel_state == after_replay_state,
                    "continuation_requested": replay.get("continuation_requested"),
                },
                    "different_user": different_user,
                    "expiry": expiry,
                    "event_counts": {
                        "first": first["event_count"],
                        "cancelled": cancelled["event_count"],
                        "replay": replay["event_count"],
                    },
                }
                print(json.dumps(report, sort_keys=True))
                if any(
                    item.get("status") == "failed"
                    for item in report.values()
                    if isinstance(item, dict) and "status" in item
                ):
                    raise SystemExit("Assist follow-up fixture evidence failed")
                return
            if command in {"invoke", "invoke-control", "invoke-vague", "invoke-batch", "invoke-batch-off"}:
                if len(ours) != 1 or ours[0]["conversation_engine"] != AGENT:
                    raise RuntimeError("Fixture pipeline is absent or points to another agent")
                await ws.send_json({
                    "id": 3, "type": "assist_pipeline/run", "pipeline": ours[0]["id"],
                    "start_stage": "intent", "end_stage": "intent",
                    "input": {"text": (
                        "Turn on the Switchboard Fixture light."
                        if command == "invoke-control"
                        else "Turn all the lights on."
                        if command == "invoke-batch"
                        else "Turn all the lights off."
                        if command == "invoke-batch-off"
                        else "Turn the lights on."
                        if command == "invoke-vague"
                        else "What is the Switchboard Fixture Temperature Reading?"
                    )},
                })
                event_types = []
                completed = False
                deadline = time.monotonic() + ASSIST_FOLLOW_UP_TIMEOUT_SECONDS
                for _ in range(ASSIST_MAX_EVENTS):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    event = await ws.receive_json(timeout=min(ASSIST_EVENT_TIMEOUT_SECONDS, remaining))
                    if event.get("id") != 3:
                        continue
                    if event["type"] == "result" and not event.get("success"):
                        raise RuntimeError(f"Assist invocation failed: {event.get('error', {}).get('code')}")
                    if event["type"] == "event":
                        event_type = event.get("event", {}).get("type", "unknown")
                        event_types.append(event_type)
                        if event_type == "intent-end":
                            output = event.get("event", {}).get("data", {}).get("intent_output", {})
                            speech = output.get("response", {}).get("speech", {}).get("plain", {}).get("speech")
                            print("Assist speech:", speech)
                        if event_type == "error":
                            detail = event.get("event", {}).get("data", {})
                            print("Assist error code:", detail.get("code"))
                        if event_type in {"run-end", "error"}:
                            completed = event_type == "run-end"
                            break
                if not completed:
                    raise SystemExit("Assist invocation did not complete within the bounded deadline")
                print("Assist event types:", event_types)


def parse_cli_args(argv: list[str]) -> tuple[str, bool]:
    commands = {
        "inspect", "configure", "invoke", "invoke-control", "invoke-vague",
        "invoke-batch", "invoke-batch-off", "native", "exercise", "area", "metadata",
        "expose", "exposure", "coverage", "unsupported", "follow-up", "failures",
        "profile", "scan", "lifecycle", "startup", "verify", "restart-cycle",
    }
    parser = argparse.ArgumentParser(prog="local_api.py")
    parser.add_argument("command", choices=sorted(commands))
    parser.add_argument(
        "--allow-restart",
        action="store_true",
        help="explicitly authorize the disposable local App/Core restart cycle",
    )
    parsed = parser.parse_args(argv)
    if parsed.allow_restart and parsed.command != "restart-cycle":
        parser.error("--allow-restart is valid only with restart-cycle")
    return parsed.command, parsed.allow_restart


if __name__ == "__main__":
    command, allow_restart = parse_cli_args(sys.argv[1:])
    if command == "restart-cycle":
        print(json.dumps(restart_cycle(allow_restart=allow_restart), sort_keys=True))
    elif command == "startup":
        print(json.dumps(startup_check(), sort_keys=True))
    else:
        asyncio.run(main(command))
