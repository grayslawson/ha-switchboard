#!/usr/bin/env python3
"""Bounded, secret-free runtime probe for the native Assist miss path.

The outer process only inspects the preserved ``busy_cohen`` container and
passes this file to its Home Assistant Core container.  The inner probe sends
one sanitized fixture request through the existing Switchboard Assist
pipeline.  It intentionally emits only lifecycle booleans and event counts;
captured Core/App output is never forwarded to the terminal.

This is an observational fixture check.  It does not install, restart,
rebuild, reset, remove, or alter the harness.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


CONTAINER = "busy_cohen"
CORE_CONTAINER = "homeassistant"
HOST_PORT = "7123"
ASSIST_AGENT = "conversation.ha_switchboard"
PIPELINE_NAME = "Switchboard"
SANITIZED_UTTERANCE = "Turn the lights on."
MAX_EVENTS = 24
TIMEOUT_SECONDS = 20.0
DOCKER_TIMEOUT_SECONDS = 30.0
LOCAL_GATEWAY_HOSTS = frozenset({"local-ha-switchboard", "localhost", "127.0.0.1"})
LOCAL_GATEWAY_PORT = 8099


def _local_gateway_url(value: str) -> bool:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in LOCAL_GATEWAY_HOSTS
        and port == LOCAL_GATEWAY_PORT
        and parsed.path in {"", "/"}
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _safe_report(
    *,
    target_verified: bool,
    pipeline_present: bool,
    prefer_local_intents: bool,
    completed: bool,
    run_start_count: int,
    run_end_count: int,
    event_count: int,
    gateway_result_delta: int | None,
    conversation_id_reused: bool | None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Project private probe state into evidence safe to print."""

    report: dict[str, Any] = {
        "command": "native_miss",
        "target_verified": target_verified,
        "pipeline": {
            "switchboard_agent_present": pipeline_present,
            "prefer_local_intents": prefer_local_intents,
        },
        "bounded_assist": {
            "completed": completed,
            "event_count": event_count,
            "max_events": MAX_EVENTS,
            "timeout_seconds": TIMEOUT_SECONDS,
            "single_run": run_start_count == 1 and run_end_count == 1,
        },
        "switchboard_continuation": {
            "gateway_result_delta": gateway_result_delta,
            "exactly_one_gateway_result": gateway_result_delta == 1,
            "conversation_id_reused": conversation_id_reused,
        },
        "recursion_guard": {
            "completed_within_bound": completed,
            "single_assist_run": run_start_count == 1 and run_end_count == 1,
            "no_gateway_recursion_observed": gateway_result_delta == 1,
        },
    }
    if error_code is not None:
        report["error_code"] = error_code
    return report


def _container_metadata() -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", "inspect", CONTAINER],
        capture_output=True,
        text=True,
        timeout=DOCKER_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("target_unavailable")
    try:
        item = json.loads(completed.stdout)[0]
        ports = item["NetworkSettings"]["Ports"]
        host_ports = {
            str(binding.get("HostPort"))
            for binding in ports.get("80/tcp", []) or []
            if isinstance(binding, Mapping)
        }
        verified = (
            item.get("Name") == f"/{CONTAINER}"
            and item.get("State", {}).get("Running") is True
            and HOST_PORT in host_ports
        )
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("target_metadata_invalid") from exc
    if not verified:
        raise RuntimeError("target_not_verified")
    return {"verified": True}


def _run_inner() -> dict[str, Any]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "docker",
            "exec",
            "-i",
            CORE_CONTAINER,
            "python3",
            "-",
            "--inner",
        ],
        input=Path(__file__).read_bytes(),
        capture_output=True,
        timeout=DOCKER_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        return _safe_report(
            target_verified=True,
            pipeline_present=False,
            prefer_local_intents=False,
            completed=False,
            run_start_count=0,
            run_end_count=0,
            event_count=0,
            gateway_result_delta=None,
            conversation_id_reused=None,
            error_code="inner_probe_failed",
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return _safe_report(
            target_verified=True,
            pipeline_present=False,
            prefer_local_intents=False,
            completed=False,
            run_start_count=0,
            run_end_count=0,
            event_count=0,
            gateway_result_delta=None,
            conversation_id_reused=None,
            error_code="inner_evidence_invalid",
        )
    if not isinstance(value, dict):
        return _safe_report(
            target_verified=True,
            pipeline_present=False,
            prefer_local_intents=False,
            completed=False,
            run_start_count=0,
            run_end_count=0,
            event_count=0,
            gateway_result_delta=None,
            conversation_id_reused=None,
            error_code="inner_evidence_not_object",
        )
    return value


def _safe_failure(code: str) -> dict[str, Any]:
    return _safe_report(
        target_verified=False,
        pipeline_present=False,
        prefer_local_intents=False,
        completed=False,
        run_start_count=0,
        run_end_count=0,
        event_count=0,
        gateway_result_delta=None,
        conversation_id_reused=None,
        error_code=code,
    )


def _outer_main() -> int:
    try:
        _container_metadata()
        report = _run_inner()
    except subprocess.TimeoutExpired:
        report = _safe_failure("bounded_timeout")
    except RuntimeError as exc:
        report = _safe_failure(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("error_code") is None and all(
        (
            report["target_verified"],
            report["pipeline"]["switchboard_agent_present"],
            report["pipeline"]["prefer_local_intents"],
            report["bounded_assist"]["completed"],
            report["bounded_assist"]["single_run"],
            report["switchboard_continuation"]["exactly_one_gateway_result"],
            report["recursion_guard"]["no_gateway_recursion_observed"],
        )
    ) else 1


async def _inner_main() -> None:
    import aiohttp
    import jwt

    base = "http://127.0.0.1:80"
    auth_data = json.loads(Path("/config/.storage/auth").read_text(encoding="utf-8"))["data"]
    users = {item["id"]: item for item in auth_data["users"]}
    candidates = [
        item
        for item in auth_data["refresh_tokens"]
        if item.get("token_type") == "long_lived_access_token"
        and users.get(item.get("user_id"), {}).get("is_owner")
    ]
    if len(candidates) != 1:
        print(json.dumps(_safe_report(
            target_verified=True,
            pipeline_present=False,
            prefer_local_intents=False,
            completed=False,
            run_start_count=0,
            run_end_count=0,
            event_count=0,
            gateway_result_delta=None,
            conversation_id_reused=None,
            error_code="local_owner_token_unavailable",
        ), sort_keys=True))
        return
    refresh = candidates[0]
    now = int(time.time())
    token = jwt.encode(
        {"iss": refresh["id"], "iat": now, "exp": now + 300},
        refresh["jwt_key"],
        algorithm="HS256",
    )
    entries = json.loads(Path("/config/.storage/core.config_entries").read_text(encoding="utf-8"))["data"]["entries"]
    switchboard_entries = [item for item in entries if item.get("domain") == "ha_switchboard"]
    if len(switchboard_entries) != 1:
        print(json.dumps(_safe_report(
            target_verified=True,
            pipeline_present=False,
            prefer_local_intents=False,
            completed=False,
            run_start_count=0,
            run_end_count=0,
            event_count=0,
            gateway_result_delta=None,
            conversation_id_reused=None,
            error_code="switchboard_entry_unavailable",
        ), sort_keys=True))
        return
    entry_data = switchboard_entries[0].get("data", {})
    gateway_url = str(entry_data.get("gateway_url", ""))
    gateway_token = str(entry_data.get("gateway_token", ""))
    if not _local_gateway_url(gateway_url):
        print(json.dumps(_safe_report(
            target_verified=True,
            pipeline_present=True,
            prefer_local_intents=True,
            completed=False,
            run_start_count=0,
            run_end_count=0,
            event_count=0,
            gateway_result_delta=None,
            conversation_id_reused=None,
            error_code="gateway_target_not_local",
        ), sort_keys=True))
        return
    headers = {"Authorization": f"Bearer {gateway_token}"}
    conversation_id = f"native-miss-{uuid.uuid4().hex}"

    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
        async def diagnostics_total() -> int:
            params = {"limit": "128", "event_type": "conversation_result"}
            async with session.get(
                gateway_url.rstrip("/") + "/v1/diagnostics", params=params,
                headers=headers, timeout=5,
            ) as response:
                if response.status != 200:
                    raise RuntimeError("gateway_diagnostics_unavailable")
                body = await response.json()
            total = body.get("total")
            if not isinstance(total, int):
                raise RuntimeError("gateway_diagnostics_invalid")
            return total

        async with session.ws_connect(base.replace("http", "ws") + "/api/websocket", timeout=5) as ws:
            if (await ws.receive_json(timeout=5)).get("type") != "auth_required":
                raise RuntimeError("core_websocket_unavailable")
            await ws.send_json({"type": "auth", "access_token": token})
            if (await ws.receive_json(timeout=5)).get("type") != "auth_ok":
                raise RuntimeError("core_auth_rejected")

            async def call(message: dict[str, Any]) -> dict[str, Any]:
                await ws.send_json(message)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    received = await ws.receive_json(timeout=min(5, deadline - time.monotonic()))
                    if received.get("id") == message["id"]:
                        return received
                raise RuntimeError("core_call_timeout")

            listing = await call({"id": 1, "type": "assist_pipeline/pipeline/list"})
            pipelines = listing.get("result", {}).get("pipelines", []) if listing.get("success") else []
            selected = [
                item for item in pipelines
                if item.get("name") == PIPELINE_NAME
                and item.get("conversation_engine") == ASSIST_AGENT
            ]
            pipeline_present = len(selected) == 1
            prefer_local = pipeline_present and selected[0].get("prefer_local_intents") is True
            if not pipeline_present:
                print(json.dumps(_safe_report(
                    target_verified=True,
                    pipeline_present=False,
                    prefer_local_intents=False,
                    completed=False,
                    run_start_count=0,
                    run_end_count=0,
                    event_count=0,
                    gateway_result_delta=None,
                    conversation_id_reused=None,
                    error_code="switchboard_pipeline_unavailable",
                ), sort_keys=True))
                return

            before = await diagnostics_total()
            message_id = 2
            await ws.send_json({
                "id": message_id,
                "type": "assist_pipeline/run",
                "pipeline": selected[0]["id"],
                "start_stage": "intent",
                "end_stage": "intent",
                "conversation_id": conversation_id,
                "input": {"text": SANITIZED_UTTERANCE},
            })
            event_types: list[str] = []
            observed_conversation_id: str | None = None
            completed = False
            deadline = time.monotonic() + TIMEOUT_SECONDS
            for _ in range(MAX_EVENTS):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                event = await ws.receive_json(timeout=min(5, remaining))
                if event.get("id") != message_id:
                    continue
                if event.get("type") == "result":
                    if not event.get("success"):
                        raise RuntimeError("assist_pipeline_rejected")
                    continue
                if event.get("type") != "event":
                    continue
                detail = event.get("event") or {}
                event_type = str(detail.get("type", "unknown"))
                event_types.append(event_type)
                if observed_conversation_id is None:
                    candidate = detail.get("data", {}).get("conversation_id") if isinstance(detail.get("data"), Mapping) else None
                    if isinstance(candidate, str) and candidate:
                        observed_conversation_id = candidate
                if event_type == "error":
                    raise RuntimeError("assist_pipeline_error")
                if event_type == "run-end":
                    completed = True
                    break
            after = await diagnostics_total()
            report = _safe_report(
                target_verified=True,
                pipeline_present=pipeline_present,
                prefer_local_intents=prefer_local,
                completed=completed,
                run_start_count=event_types.count("run-start"),
                run_end_count=event_types.count("run-end"),
                event_count=len(event_types),
                gateway_result_delta=after - before,
                conversation_id_reused=(
                    observed_conversation_id == conversation_id
                    if observed_conversation_id is not None else None
                ),
            )
            print(json.dumps(report, sort_keys=True))


def main() -> int:
    if "--inner" in sys.argv[1:]:
        asyncio.run(_inner_main())
        return 0
    return _outer_main()


if __name__ == "__main__":
    raise SystemExit(main())
