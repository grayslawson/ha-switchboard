from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ha_switchboard.gateway import Gateway
from ha_switchboard.jev_client import StaticJevClient
from ha_switchboard.protocol import Complexity, JevDecision, RouteKind
from ha_switchboard.store import ProfileStore
from custom_components.ha_switchboard.conversation import JevConversationEntity
from custom_components.ha_switchboard.conversation_context import ConversationContextStore


ROOT = Path(__file__).parents[1]
LOCAL_SUPERVISOR_CONTAINER = "busy_cohen"
LOCAL_CORE_CONTAINER = "homeassistant"
HARNESS = ROOT / "tools" / "app-image-e2e.sh"
WORKFLOW = ROOT / ".forgejo" / "workflows" / "build-app.yml"


def _fixture_api():
    path = ROOT / "tools" / "local-fixtures" / "local_api.py"
    spec = importlib.util.spec_from_file_location("e2e_fixture_local_api", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_e2e_harness_is_source_build_and_secret_free() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert HARNESS.stat().st_mode & 0o111
    assert '"$ROOT_DIR/app"' in text
    assert "localhost/ha-switchboard-local" in text
    assert "ghcr.io/grayslawson/ha-switchboard" not in text
    assert '--build-arg "BUILD_ARCH=${HA_ARCH}"' in text
    assert "HA_SWITCHBOARD_E2E_DISCOVERY_HOOK=1" in text
    assert "env -i" in text
    assert "/healthz" in text and "/readyz" in text
    assert "172.30.32.2" in text
    assert '172.30.32.3:8099 "$path"' in text
    assert 'if [[ "$ENGINE" == podman ]]; then' in text
    assert "65532:65532" in text
    assert "apparmor" in text


def test_release_workflow_maps_docker_arm64_to_home_assistant_aarch64() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "for arch in amd64 arm64; do" in text
    assert "hass_arch=aarch64" in text
    assert '--build-arg "BUILD_ARCH=${hass_arch}"' in text


def _request(
    gateway: Gateway,
    *,
    request_id: str = "e2e-contract-request",
    capability_id: str | None = None,
    revision: str | None = None,
) -> dict:
    return {
        "request_id": request_id,
        "conversation_id": "e2e-contract-conversation",
        "utterance": "turn on the fixture light",
        "language": "en",
        "profile_revision": revision or gateway.active_profile.revision,
        "policy_revision": "policy-1",
        "candidates": ([{"capability_id": capability_id}] if capability_id else []),
        "bounded_context": [],
        "sanitized_state": {},
    }


class _MalformedProvider:
    def decide(self, _request):
        raise ValueError("provider payload was malformed")


def test_sanitized_e2e_failure_scenarios_are_bounded_and_non_executing(tmp_path, sanitized_discovery):
    gateway = Gateway(store=ProfileStore(tmp_path), jev=StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE)))
    gateway.reconcile(sanitized_discovery)
    light = next(item for item in gateway.active_profile.capabilities if item.domain == "light" and item.operation == "turn_on")

    stale = gateway.process(_request(gateway, request_id="stale", capability_id=light.capability_id, revision="sha256:stale"))
    assert stale.response_key == "profile_stale"

    gateway.jev = StaticJevClient(JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, "capability-not-offered", 1.0, 0.0))
    unknown = gateway.process(_request(gateway, request_id="unknown", capability_id="capability-not-offered"))
    assert unknown.response_key == "candidate_not_allowed"

    temperature = next(item for item in gateway.active_profile.capabilities if item.domain == "climate" and item.operation == "set_temperature")
    gateway.jev = StaticJevClient(JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, temperature.capability_id, 1.0, 0.0, parameters={"temperature": 999}))
    invalid = gateway.process(_request(gateway, request_id="invalid", capability_id=temperature.capability_id))
    assert invalid.response_key == "invalid_parameters"

    gateway.jev = _MalformedProvider()
    malformed = gateway.process(_request(gateway, request_id="malformed", capability_id=light.capability_id))
    assert malformed.response_key == "jev_invalid_response"
    assert all(not hasattr(result, "entity_id") for result in (stale, unknown, invalid, malformed))


def test_local_startup_evidence_is_read_only_and_secret_free(monkeypatch) -> None:
    api = _fixture_api()
    lifecycle = {
        "config_entry": {"domain": "ha_switchboard", "source": "hassio", "version": 1, "has_gateway_token": True},
        "core": {"fixture_entity_count": 28, "conversation_agent_present": True},
        "gateway": {
            "status": "active",
            "has_revision": True,
            "pending_section_count": 0,
            "pending_invalidation_count": 0,
        },
    }
    calls: list[str] = []
    monkeypatch.setattr(api, "inspect_local_supervisor", lambda: {
        "container": "busy_cohen", "supervisor_port": 7123,
        "supervisor_volume_verified": True, "volume_identity_verified": True,
        "volume_identity_fingerprint": "0123456789abcdef",
    })
    monkeypatch.setattr(api, "read_local_app_options", lambda: (
        {"options_present": True, "app_started": True, "configured_fields": {"gateway_token": True}},
        {"gateway_token": "secret-in-memory-only"},
    ))
    monkeypatch.setattr(api, "run_core_fixture_command", lambda command: calls.append(command) or lifecycle)

    report = api.startup_check()

    assert calls == ["lifecycle"]
    assert report["ready"] is True
    assert report["mode"] == "read_only"
    assert "secret-in-memory-only" not in repr(report)


def test_runtime_operation_matrix_covers_every_published_fixture_row(tmp_path) -> None:
    api = _fixture_api()
    plan = api.operation_matrix_plan()
    assert len(plan) == len(api.PUBLISHED_MATRIX) == 24
    assert {(row["domain"], row["operation"], row["entity_id"]) for row in plan} == set(api.PUBLISHED_MATRIX)
    assert {row["operation"] for row in plan} >= {"toggle", "set_brightness", "set_volume", "stop"}

    snapshot = {"entities": []}
    for domain, operation, entity_id in api.PUBLISHED_MATRIX:
        snapshot["entities"].append({
            "adapter_ref": f"fixture-{entity_id}",
            "domain": domain,
            "name": entity_id,
            "exposed": True,
            "available": True,
            "operations": [operation],
        })
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE)),
    )
    gateway.reconcile(snapshot)
    for index, row in enumerate(api.PUBLISHED_MATRIX):
        domain, operation, _entity_id = row
        capability = next(
            item for item in gateway.active_profile.capabilities
            if item.domain == domain and item.operation == operation
        )
        parameters = {
            "brightness": 40,
            "volume": 0.25,
            "temperature": 21,
            "hvac_mode": "heat",
        }
        parameters = {key: value for key, value in parameters.items() if key in capability.parameter_schema.get("required", ())}
        gateway.jev = StaticJevClient(JevDecision(
            RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 1.0, 0.0,
            parameters=parameters,
        ))
        result = gateway.process(_request(gateway, request_id=f"matrix-{index}", capability_id=capability.capability_id))
        expected = "confirmation_required" if operation in {"lock", "unlock", "open_cover", "close_cover"} else "execute"
        assert result.response_key == expected


def test_unsupported_fixture_surfaces_are_present_but_not_switchboard_exposed() -> None:
    api = _fixture_api()
    states = {entity_id: {"state": "off"} for _, _, entity_id in api.PUBLISHED_MATRIX}
    states.update({entity_id: {"state": "off"} for _, _, entity_id in api.NATIVE_HASS_SURFACES})
    exposed = {entity_id: {"conversation": True} for _, _, entity_id in api.PUBLISHED_MATRIX}

    report = api.unsupported_surface_report(states, exposed)

    assert report["complete"] is True
    assert report["present_count"] == 2
    assert report["unexpectedly_exposed"] == []
    assert all(row["supported_by_switchboard"] is False for row in report["rows"])


class _FollowUpClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.executions = 0

    async def process(self, payload: dict) -> dict:
        self.payloads.append(payload)
        if payload.get("sanitized_state", {}).get("confirmation") is True:
            self.executions += 1
            return {"kind": "execute", "response_key": "execute_verified"}
        if payload.get("utterance") == "Unlock the fixture lock":
            return {"kind": "confirm", "response_key": "confirmation_required"}
        return {"kind": "refuse", "response_key": "request_refused"}


def _follow_up_input(text: str, conversation_id: str, user_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        conversation_id=conversation_id,
        language="en",
        context=SimpleNamespace(user_id=user_id),
    )


def test_follow_up_assist_is_same_conversation_user_bound_expiring_cancelable_and_one_shot() -> None:
    async def run() -> None:
        now = [100.0]
        client = _FollowUpClient()
        store = ConversationContextStore(ttl=10, clock=lambda: now[0])
        entity = JevConversationEntity(client, context_store=store)
        entity.context_store = store

        first = await entity._async_handle_message(
            _follow_up_input("Unlock the fixture lock", "conversation-a", "user-a"), SimpleNamespace()
        )
        assert first["response_key"] == "confirmation_required"
        assert entity.context_store.peek("conversation-a", "user-a") is not None

        cancelled = await entity._async_handle_message(
            _follow_up_input("No", "conversation-a", "user-a"), SimpleNamespace()
        )
        assert cancelled["response_key"] == "confirmation_cancelled"
        assert entity.context_store.peek("conversation-a", "user-a") is None

        replay = await entity._async_handle_message(
            _follow_up_input("Yes", "conversation-a", "user-a"), SimpleNamespace()
        )
        assert replay["response_key"] == "request_refused"
        assert client.executions == 0
        assert not any(payload.get("sanitized_state", {}).get("confirmation") for payload in client.payloads[1:])

        different_user_store = ConversationContextStore(ttl=10, clock=lambda: now[0])
        different_user_client = _FollowUpClient()
        different_user_entity = JevConversationEntity(different_user_client, context_store=different_user_store)
        different_user_entity.context_store = different_user_store
        await different_user_entity._async_handle_message(
            _follow_up_input("Unlock the fixture lock", "conversation-b", "user-a"), SimpleNamespace()
        )
        different_user = await different_user_entity._async_handle_message(
            _follow_up_input("Yes", "conversation-b", "user-b"), SimpleNamespace()
        )
        assert different_user["response_key"] == "request_refused"
        assert different_user_entity.context_store.peek("conversation-b", "user-a") is not None
        assert different_user_client.executions == 0
        assert not different_user_client.payloads[-1]["sanitized_state"].get("confirmation")

        expired_store = ConversationContextStore(ttl=10, clock=lambda: now[0])
        expired_client = _FollowUpClient()
        expired_entity = JevConversationEntity(expired_client, context_store=expired_store)
        expired_entity.context_store = expired_store
        await expired_entity._async_handle_message(
            _follow_up_input("Unlock the fixture lock", "conversation-expired", "user-a"), SimpleNamespace()
        )
        now[0] += 11
        expired = await expired_entity._async_handle_message(
            _follow_up_input("Yes", "conversation-expired", "user-a"), SimpleNamespace()
        )
        assert expired["response_key"] == "request_refused"
        assert expired_entity.context_store.peek("conversation-expired", "user-a") is None
        assert expired_client.executions == 0
        assert not expired_client.payloads[-1]["sanitized_state"].get("confirmation")

        accepted_store = ConversationContextStore(ttl=10, clock=lambda: now[0])
        accepted_client = _FollowUpClient()
        accepted_entity = JevConversationEntity(accepted_client, context_store=accepted_store)
        accepted_entity.context_store = accepted_store
        await accepted_entity._async_handle_message(
            _follow_up_input("Unlock the fixture lock", "conversation-c", "user-a"), SimpleNamespace()
        )
        accepted = await accepted_entity._async_handle_message(
            _follow_up_input("Yes", "conversation-c", "user-a"), SimpleNamespace()
        )
        assert accepted["response_key"] == "execute_verified"
        assert accepted_entity.context_store.peek("conversation-c", "user-a") is None
        assert accepted_client.executions == 1
        assert accepted_client.payloads[1]["sanitized_state"]["confirmation"] is True

        replay_after_accept = await accepted_entity._async_handle_message(
            _follow_up_input("Yes", "conversation-c", "user-a"), SimpleNamespace()
        )
        assert replay_after_accept["response_key"] == "request_refused"
        assert accepted_client.executions == 1
        assert not accepted_client.payloads[-1]["sanitized_state"].get("confirmation")

    asyncio.run(run())


def test_live_follow_up_passes_conversation_id_at_assist_pipeline_boundary() -> None:
    text = (ROOT / "tools" / "local-fixtures" / "local_api.py").read_text(encoding="utf-8")

    assert "ASSIST_FOLLOW_UP_TIMEOUT_SECONDS = 30" in text
    assert 'FOLLOW_UP_SECOND_USER_ACCESS_TOKEN_ENV = "HA_SWITCHBOARD_FOLLOW_UP_SECOND_USER_ACCESS_TOKEN"' in text
    assert 'FOLLOW_UP_NATURAL_EXPIRY_ENV = "HA_SWITCHBOARD_RUN_FOLLOW_UP_NATURAL_EXPIRY"' in text
    assert 'FOLLOW_UP_RUN_OPT_IN_ENV = "HA_SWITCHBOARD_RUN_FOLLOW_UP"' in text
    assert "FOLLOW_UP_NATURAL_EXPIRY_MAX_WAIT_SECONDS = 150" in text
    assert "for _ in range(ASSIST_MAX_EVENTS)" in text
    assert '"conversation_id": conversation_id' in text
    assert '"input": {"text": text}' in text
    for section in ("same_conversation", "cancellation", "replay"):
        assert f'"{section}": {{' in text
    assert "different_user = {" in text
    assert "expiry = {" in text
    assert '"status": "unavailable"' in text
    assert "requires a second existing HA user token" in text
    assert "Core continuation TTL" in text
    assert 'item.get("status") == "failed"' in text
    assert 'raise SystemExit("Assist follow-up fixture evidence failed")' in text


def test_follow_up_opt_ins_are_strict_and_default_to_unavailable(monkeypatch) -> None:
    api = _fixture_api()

    monkeypatch.delenv(api.FOLLOW_UP_SECOND_USER_ACCESS_TOKEN_ENV, raising=False)
    monkeypatch.delenv(api.FOLLOW_UP_NATURAL_EXPIRY_ENV, raising=False)
    monkeypatch.delenv(api.FOLLOW_UP_RUN_OPT_IN_ENV, raising=False)
    token, natural_expiry = api.follow_up_opt_ins()
    assert token is None
    assert natural_expiry is False

    supplied = "second-user-token-never-in-report"
    token, natural_expiry = api.follow_up_opt_ins({
        api.FOLLOW_UP_SECOND_USER_ACCESS_TOKEN_ENV: supplied,
        api.FOLLOW_UP_NATURAL_EXPIRY_ENV: "1",
        api.FOLLOW_UP_RUN_OPT_IN_ENV: "1",
    })
    assert token == supplied
    assert natural_expiry is True

    token, natural_expiry = api.follow_up_opt_ins({
        api.FOLLOW_UP_SECOND_USER_ACCESS_TOKEN_ENV: "  ",
        api.FOLLOW_UP_NATURAL_EXPIRY_ENV: "true",
        api.FOLLOW_UP_RUN_OPT_IN_ENV: "1",
    })
    assert token is None
    assert natural_expiry is False

    token, natural_expiry = api.follow_up_opt_ins({
        api.FOLLOW_UP_SECOND_USER_ACCESS_TOKEN_ENV: supplied,
        api.FOLLOW_UP_NATURAL_EXPIRY_ENV: "1",
        api.FOLLOW_UP_RUN_OPT_IN_ENV: "yes",
    })
    assert token is None
    assert natural_expiry is False


def test_second_user_identity_is_checked_in_memory_and_fails_closed(monkeypatch) -> None:
    api = _fixture_api()

    class FakeJwt:
        @staticmethod
        def decode(_token, *, options):
            assert options == {"verify_signature": False}
            return {"iss": "second-refresh"}

    class FakeAuthPath:
        def __init__(self, _path):
            pass

        def read_text(self, *args, **kwargs):
            return json.dumps({
                "data": {
                    "users": [
                        {"id": "owner", "is_owner": True},
                        {"id": "second", "is_owner": False},
                    ],
                    "refresh_tokens": [
                        {"id": "owner-refresh", "user_id": "owner", "token_type": "long_lived_access_token"},
                        {"id": "second-refresh", "user_id": "second", "token_type": "long_lived_access_token"},
                    ],
                }
            })

    monkeypatch.setitem(sys.modules, "jwt", FakeJwt)
    monkeypatch.setattr(api, "Path", FakeAuthPath)

    assert api.owner_user_id() == "owner"
    assert api.access_token_user_id("opaque-second-token") == "second"

    class SameUserJwt(FakeJwt):
        @staticmethod
        def decode(_token, *, options):
            return {"iss": "owner-refresh"}

    monkeypatch.setitem(sys.modules, "jwt", SameUserJwt)
    assert api.access_token_user_id("opaque-owner-token") == "owner"

    class UnknownUserJwt(FakeJwt):
        @staticmethod
        def decode(_token, *, options):
            return {"iss": "unknown-refresh"}

    monkeypatch.setitem(sys.modules, "jwt", UnknownUserJwt)
    with pytest.raises(RuntimeError, match="identity could not be verified"):
        api.access_token_user_id("opaque-unknown-token")


def test_natural_ttl_wait_has_a_fixed_maximum(monkeypatch) -> None:
    api = _fixture_api()
    slept: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        slept.append(seconds)

    monkeypatch.setattr(api, "FOLLOW_UP_CONTINUATION_TTL_SECONDS", 3)
    monkeypatch.setattr(api, "FOLLOW_UP_NATURAL_EXPIRY_SAFETY_SECONDS", 2)
    monkeypatch.setattr(api, "FOLLOW_UP_NATURAL_EXPIRY_MAX_WAIT_SECONDS", 10)
    monkeypatch.setattr(api.asyncio, "sleep", fake_sleep)

    waited = asyncio.run(api.wait_for_natural_continuation_expiry())

    assert waited == 5
    assert slept == [5]


def _run_live_follow_up_fixture() -> dict:
    """Run the preserved Core-side probe and retain only its sanitized report."""
    fixture_script = ROOT / "tools" / "local-fixtures" / "local_api.py"
    forwarded_outer_env: list[str] = []
    forwarded_inner_env: list[str] = []
    forwarded_names = (
        "HA_SWITCHBOARD_FOLLOW_UP_SECOND_USER_ACCESS_TOKEN",
        "HA_SWITCHBOARD_RUN_FOLLOW_UP_NATURAL_EXPIRY",
        "HA_SWITCHBOARD_RUN_FOLLOW_UP",
    )
    supplied_token = os.environ.get(forwarded_names[0])
    for name in forwarded_names:
        value = os.environ.get(name)
        if value is not None:
            # Both Docker CLIs inherit the value from this process environment
            # and receive only the variable name.  Neither command argument,
            # output, nor the sanitized report contains the value.
            forwarded_outer_env.extend(["--env", name])
            forwarded_inner_env.extend(["--env", name])
    completed = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            *forwarded_outer_env,
            LOCAL_SUPERVISOR_CONTAINER,
            "docker",
            "exec",
            "-i",
            *forwarded_inner_env,
            LOCAL_CORE_CONTAINER,
            "python3",
            "-",
            "follow-up",
        ],
        input=fixture_script.read_bytes(),
        capture_output=True,
        timeout=210 if os.environ.get("HA_SWITCHBOARD_RUN_FOLLOW_UP_NATURAL_EXPIRY") == "1" else 45,
        check=False,
    )
    # Never put captured output in an assertion: fixture diagnostics must not
    # echo credentials, raw Core references, utterances, or provider bodies.
    output = completed.stdout + completed.stderr
    forbidden = (
        b"gateway_token",
        b"api_key",
        b"password",
        b"authorization",
        b"user_id",
        b"entity_id",
        b"utterance",
        b"provider_body",
    )
    if any(value in output.lower() for value in forbidden):
        raise AssertionError("live follow-up probe output was not sanitized")
    if supplied_token and supplied_token.encode() in output:
        raise AssertionError("live follow-up probe output contained the supplied token")
    if completed.returncode != 0 or completed.stderr:
        raise AssertionError("live follow-up probe failed without sanitized evidence")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, "live follow-up probe returned no sanitized report"
    try:
        report = json.loads(lines[-1].decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError("live follow-up probe did not return JSON evidence") from exc
    assert isinstance(report, dict)
    rendered = json.dumps(report, sort_keys=True)
    for forbidden in (
        "gateway_token",
        "api_key",
        "password",
        "authorization",
        "user_id",
        "entity_id",
        "utterance",
        "provider_body",
    ):
        assert forbidden not in rendered.casefold()
    return report


def test_live_follow_up_forwards_token_by_environment_name_only(monkeypatch) -> None:
    supplied_token = "second-user-token-never-in-report"
    monkeypatch.setenv("HA_SWITCHBOARD_FOLLOW_UP_SECOND_USER_ACCESS_TOKEN", supplied_token)
    monkeypatch.setenv("HA_SWITCHBOARD_RUN_FOLLOW_UP", "1")

    def fake_run(command, *, input, capture_output, timeout, check):
        assert supplied_token not in " ".join(command)
        assert supplied_token.encode() not in input
        assert timeout == 45
        return SimpleNamespace(
            stdout=b'{"command":"follow-up","different_user":{"status":"proved"}}\n',
            stderr=b"",
            returncode=0,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = _run_live_follow_up_fixture()

    assert report["different_user"]["status"] == "proved"
    assert supplied_token not in json.dumps(report)


@pytest.mark.local_fixture
@pytest.mark.skipif(
    os.environ.get("HA_SWITCHBOARD_RUN_FOLLOW_UP") != "1",
    reason="live disposable Home Assistant follow-up probe is opt-in",
)
def test_live_follow_up_fixture_is_bounded_and_reports_unavailable_gates() -> None:
    report = _run_live_follow_up_fixture()

    assert report["command"] == "follow-up"
    assert report["same_conversation"]["status"] == "proved"
    assert report["cancellation"]["status"] == "proved"
    assert report["replay"]["status"] == "proved"
    for name, gate in (
        ("different_user", "requires a second existing HA user token"),
        ("expiry", "requires explicit HA_SWITCHBOARD_RUN_FOLLOW_UP=1 authorization"),
    ):
        assert report[name]["status"] in {"proved", "unavailable"}
        if report[name]["status"] == "unavailable":
            assert report[name]["reason"].startswith(gate)
