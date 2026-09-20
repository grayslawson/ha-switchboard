from __future__ import annotations

import asyncio
from pathlib import Path

from ha_switchboard.batch import BatchRequestError, build_batch_group
from ha_switchboard.gateway import Gateway
from ha_switchboard.jev_client import StaticJevClient
from ha_switchboard.protocol import Complexity, JevDecision, ResultKind, RouteKind
from ha_switchboard.store import ProfileStore
from custom_components.ha_switchboard.capabilities import CapabilityTarget, operation_spec
from custom_components.ha_switchboard.execution import ExecutionBoundary


def _gateway(tmp_path: Path, snapshot: dict) -> Gateway:
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.REFUSE, Complexity.SIMPLE)),
    )
    gateway.reconcile(snapshot)
    return gateway


def _request(gateway: Gateway, utterance: str) -> dict:
    return {
        "request_id": "batch-request",
        "conversation_id": "batch-conversation",
        "utterance": utterance,
        "language": "en",
        "profile_revision": gateway.active_profile.revision,
        "policy_revision": "policy-1",
        "candidates": [],
        "sanitized_state": {},
    }


def test_explicit_all_lights_becomes_bounded_opaque_group(tmp_path, sanitized_discovery):
    gateway = _gateway(tmp_path, sanitized_discovery)
    group = build_batch_group("Can you turn all the lights on?", gateway.active_profile)

    assert group is not None
    assert group.domain == "light" and group.operation == "turn_on"
    assert len(group.members) == 2
    assert group.candidate()["member_count"] == 2
    assert "light.living_room" not in repr(group.candidate())

    gateway.jev = StaticJevClient(JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, group.group_id, 0.98, 0.02))
    result = gateway.process(_request(gateway, "Can you turn all the lights on?"))

    assert result.kind is ResultKind.EXECUTE
    assert result.response_key == "batch_execute"
    assert result.capability_id is None
    assert result.capability_ids == group.members


def test_explicit_group_scope_does_not_depend_on_jev_confidence(tmp_path, sanitized_discovery):
    gateway = _gateway(tmp_path, sanitized_discovery)
    group = build_batch_group("Turn all the lights on", gateway.active_profile)
    gateway.jev = StaticJevClient(JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, group.group_id, 0.56, 0.20))

    result = gateway.process(_request(gateway, "Turn all the lights on"))

    assert result.kind is ResultKind.EXECUTE
    assert result.capability_ids == group.members


def test_area_group_is_narrower_than_whole_home(tmp_path, sanitized_discovery):
    extra = dict(sanitized_discovery["entities"][0])
    extra.update(adapter_ref="fixture-light-kitchen", name="Kitchen lamp", area="Kitchen")
    sanitized_discovery["entities"].append(extra)
    sanitized_discovery["exposure"].append(extra["adapter_ref"])
    gateway = _gateway(tmp_path, sanitized_discovery)

    group = build_batch_group("Turn on the living room lights", gateway.active_profile)

    assert group is not None and group.area == "Living room"
    assert len(group.members) == 2


def test_unavailable_member_blocks_group_before_jev(tmp_path, sanitized_discovery):
    sanitized_discovery["entities"][1]["available"] = False
    gateway = _gateway(tmp_path, sanitized_discovery)

    result = gateway.process(_request(gateway, "Turn all the lights on"))

    assert result.kind is ResultKind.REFUSE
    assert result.response_key == "batch_target_unavailable"


def test_batch_caps_at_32_members(tmp_path, sanitized_discovery):
    source = sanitized_discovery["entities"][0]
    for index in range(31):
        item = dict(source)
        item.update(adapter_ref=f"fixture-extra-light-{index}", name=f"Extra light {index}")
        sanitized_discovery["entities"].append(item)
        sanitized_discovery["exposure"].append(item["adapter_ref"])
    gateway = _gateway(tmp_path, sanitized_discovery)

    try:
        build_batch_group("Turn all the lights on", gateway.active_profile)
    except BatchRequestError as exc:
        assert exc.code == "batch_too_large"
    else:
        raise AssertionError("oversized batch was accepted")


def test_core_batch_preflights_every_target_before_any_write():
    class Executor:
        def __init__(self):
            self.writes = []
            self.targets = {
                key: CapabilityTarget(key, key, f"light.fixture_{key}", "light", "turn_on", operation_spec("light", "turn_on"))
                for key in ("one", "two")
            }
            self.states = {"one": "off", "two": "unavailable"}

        def profile_current(self, revision):
            return revision == "current"

        async def resolve_capability(self, capability_id):
            return self.targets.get(capability_id)

        async def read_state(self, target):
            return {"state": self.states[target.capability_id], "attributes": {}}

        async def execute(self, target, parameters):
            self.writes.append(target.capability_id)
            self.states[target.capability_id] = "on"
            return {"ok": True}

        def verify(self, target, parameters, before, after, result):
            return after["state"] == "on" and result["ok"]

    executor = Executor()
    result = asyncio.run(ExecutionBoundary(executor).execute_batch_proposal(
        capability_ids=("one", "two"), expected_profile_revision="current", current_profile_revision="current"
    ))

    assert result["response_key"] == "batch_target_unavailable"
    assert executor.writes == []


def test_core_batch_stops_after_first_failed_verification():
    class Executor:
        def __init__(self):
            self.writes = []
            self.targets = {
                key: CapabilityTarget(key, key, f"light.fixture_{key}", "light", "turn_on", operation_spec("light", "turn_on"))
                for key in ("one", "two", "three")
            }
            self.states = {key: "off" for key in self.targets}

        def profile_current(self, revision):
            return True

        async def resolve_capability(self, capability_id):
            return self.targets.get(capability_id)

        async def read_state(self, target):
            return {"state": self.states[target.capability_id], "attributes": {}}

        async def execute(self, target, parameters):
            self.writes.append(target.capability_id)
            if target.capability_id != "two":
                self.states[target.capability_id] = "on"
            return {"ok": True}

        def verify(self, target, parameters, before, after, result):
            return after["state"] == "on"

    executor = Executor()
    result = asyncio.run(ExecutionBoundary(executor).execute_batch_proposal(
        capability_ids=("one", "two", "three"), expected_profile_revision="current", current_profile_revision="current"
    ))

    assert result == {"ok": False, "response_key": "batch_partial_failure", "verified_count": 1, "total_count": 3}
    assert executor.writes == ["one", "two"]
