"""Bounded native Assist miss-path evidence and harness safety contracts."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.ha_switchboard.native_path import native_intent_filter


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "tools" / "local-fixtures" / "native_miss_runtime.py"


def _load_harness():
    namespace: dict[str, object] = {"__name__": "native_miss_runtime_test"}
    exec(compile(HARNESS.read_text(encoding="utf-8"), str(HARNESS), "exec"), namespace)
    return namespace


def test_unsupported_native_target_is_a_miss_candidate() -> None:
    recognized = SimpleNamespace(
        intent=SimpleNamespace(name="HassTurnOn"),
        entities={"domain": SimpleNamespace(value="cover")},
    )
    assert native_intent_filter(recognized) is True


def test_safe_report_drops_private_runtime_material() -> None:
    harness = _load_harness()
    report = harness["_safe_report"](
        target_verified=True,
        pipeline_present=True,
        prefer_local_intents=True,
        completed=True,
        run_start_count=1,
        run_end_count=1,
        event_count=4,
        gateway_result_delta=1,
        conversation_id_reused=True,
    )
    rendered = json.dumps(report, sort_keys=True)
    assert "native-miss-runtime" not in rendered
    assert "Turn the lights on." not in rendered
    assert "gateway_token" not in rendered
    assert "provider" not in rendered.lower()
    assert report["switchboard_continuation"]["exactly_one_gateway_result"] is True


def test_harness_accepts_only_the_disposable_local_gateway() -> None:
    harness = _load_harness()
    local_gateway_url = harness["_local_gateway_url"]

    assert local_gateway_url("http://local-ha-switchboard:8099") is True
    assert local_gateway_url("http://127.0.0.1:8099") is True
    for value in (
        "https://ha.possumden.net:8099",
        "http://local-ha-switchboard:8123",
        "http://local-ha-switchboard:8099/path",
        "http://user:secret@local-ha-switchboard:8099",
    ):
        assert local_gateway_url(value) is False


def test_harness_is_bounded_and_never_contains_mutating_commands() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    assert "MAX_EVENTS = 24" in source
    assert "TIMEOUT_SECONDS = 20.0" in source
    assert "capture_output=True" in source
    assert "print(completed.stdout" not in source
    tree = ast.parse(source)
    command_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert {"docker", "inspect", "busy_cohen"} <= command_literals
    assert not command_literals & {
        "allow-restart",
        "docker rm",
        "docker volume rm",
        "docker compose down",
        "uninstall",
        "reset",
        "rebuild",
    }


@pytest.mark.local_fixture
@pytest.mark.skipif(
    os.environ.get("HA_SWITCHBOARD_RUN_NATIVE_MISS") != "1",
    reason="live disposable Home Assistant fixture probe is opt-in",
)
def test_native_miss_live_fixture() -> None:
    completed = subprocess.run(
        [sys.executable, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.stderr == ""
    assert completed.stdout.count("\n") == 1
    report = json.loads(completed.stdout)
    assert completed.returncode == 0, report
    assert report["target_verified"] is True
    assert report["pipeline"] == {
        "switchboard_agent_present": True,
        "prefer_local_intents": True,
    }
    assert report["bounded_assist"]["completed"] is True
    assert report["bounded_assist"]["single_run"] is True
    assert report["switchboard_continuation"]["gateway_result_delta"] == 1
    assert report["recursion_guard"]["no_gateway_recursion_observed"] is True
