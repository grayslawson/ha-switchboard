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
from custom_components.ha_switchboard.capabilities import resolve_batch_targets


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


def test_label_scope_selects_only_matching_lights(tmp_path, sanitized_discovery):
    sanitized_discovery["entities"][0]["labels"] = ["Evening"]
    sanitized_discovery["entities"][1]["labels"] = ["Reading"]
    gateway = _gateway(tmp_path, sanitized_discovery)

    group = build_batch_group("Turn on all lights with the Evening label", gateway.active_profile)

    assert group is not None and group.label == "Evening" and group.area is None
    assert len(group.members) == 1


def test_floor_scope_selects_only_matching_switches(tmp_path, sanitized_discovery):
    sanitized_discovery["entities"][3]["floor"] = "Main"
    sanitized_discovery["entities"][3]["available"] = True
    gateway = _gateway(tmp_path, sanitized_discovery)

    group = build_batch_group("Turn off all switches on the Main floor", gateway.active_profile)

    assert group is not None and group.floor == "Main" and group.area is None
    assert len(group.members) == 1


def test_ambiguous_label_scope_fails_closed(tmp_path, sanitized_discovery):
    for entity in sanitized_discovery["entities"][:2]:
        entity["labels"] = ["Scene"]
    sanitized_discovery["entities"][0]["labels"].append("Other")
    gateway = _gateway(tmp_path, sanitized_discovery)

    try:
        build_batch_group("Turn on all lights with the Scene or Other label", gateway.active_profile)
    except BatchRequestError as exc:
        assert exc.code == "batch_scope_ambiguous"
    else:
        raise AssertionError("ambiguous label scope was accepted")


def test_unavailable_label_member_blocks_group(tmp_path, sanitized_discovery):
    sanitized_discovery["entities"][0]["labels"] = ["Evening"]
    sanitized_discovery["entities"][0]["available"] = False
    gateway = _gateway(tmp_path, sanitized_discovery)

    try:
        build_batch_group("Turn on all lights with the Evening label", gateway.active_profile)
    except BatchRequestError as exc:
        assert exc.code == "batch_target_unavailable"
    else:
        raise AssertionError("unavailable label member was accepted")


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


def test_core_batch_rejects_duplicate_targets_and_caps_at_32_before_write():
    target = CapabilityTarget("one", "one", "light.one", "light", "turn_on", operation_spec("light", "turn_on"))

    class Executor:
        def __init__(self):
            self.writes = 0

        def profile_current(self, revision):
            return revision == "current"

        async def resolve_capability(self, capability_id):
            return target if capability_id == "one" else None

        async def read_state(self, _target):
            return {"state": "off", "attributes": {}}

        async def execute(self, _target, _parameters):
            self.writes += 1
            return {"ok": True}

        def verify(self, _target, _parameters, _before, _after, _result):
            return True

    executor = Executor()
    duplicate = asyncio.run(ExecutionBoundary(executor).execute_batch_proposal(
        capability_ids=("one", "one"), expected_profile_revision="current", current_profile_revision="current"
    ))
    oversized = asyncio.run(ExecutionBoundary(executor).execute_batch_proposal(
        capability_ids=tuple("missing-%d" % index for index in range(33)),
        expected_profile_revision="current", current_profile_revision="current",
    ))
    assert duplicate["response_key"] == oversized["response_key"] == "batch_invalid"
    assert executor.writes == 0


def test_core_target_resolver_supports_safe_area_label_and_group_phrases():
    targets = tuple(
        CapabilityTarget(
            name, name, f"light.{name}", "light", "turn_on", operation_spec("light", "turn_on"),
            display_name=display,
        )
        for name, display in (("kitchen", "Kitchen label group"), ("living", "Living room"))
    )
    assert [item.capability_id for item in resolve_batch_targets(targets, area="Kitchen")] == ["kitchen"]
    assert [item.capability_id for item in resolve_batch_targets(targets, label="label")] == ["kitchen"]
    assert [item.capability_id for item in resolve_batch_targets(targets, group="group")] == ["kitchen"]


def test_batch_preflight_rejects_confirmation_member_without_writes():
    safe = CapabilityTarget("safe", "safe", "light.safe", "light", "turn_on", operation_spec("light", "turn_on"))
    confirm = CapabilityTarget("confirm", "confirm", "lock.front", "lock", "lock", operation_spec("lock", "lock"))

    class Executor:
        writes = 0

        def profile_current(self, _revision):
            return True

        async def resolve_capability(self, capability_id):
            return {"safe": safe, "confirm": confirm}.get(capability_id)

        async def read_state(self, _target):
            return {"state": "off", "attributes": {}}

        async def execute(self, _target, _parameters):
            self.writes += 1
            return {"ok": True}

        def verify(self, *_args):
            return True

    executor = Executor()
    result = asyncio.run(ExecutionBoundary(executor).execute_batch_proposal(
        capability_ids=("safe", "confirm"), expected_profile_revision="current", current_profile_revision="current"
    ))
    assert result["response_key"] == "batch_target_unavailable"
    assert executor.writes == 0


def test_batch_preflight_allows_mixed_safe_domains_and_replays_non_toggle_idempotently():
    targets = {
        "light": CapabilityTarget("light", "light", "light.one", "light", "turn_on", operation_spec("light", "turn_on")),
        "switch": CapabilityTarget("switch", "switch", "switch.one", "switch", "turn_on", operation_spec("switch", "turn_on")),
    }

    class Executor:
        def __init__(self):
            self.writes = []
            self.states = {key: "off" for key in targets}

        def profile_current(self, _revision):
            return True

        async def resolve_capability(self, capability_id):
            return targets.get(capability_id)

        async def read_state(self, target):
            return {"state": self.states[target.capability_id], "attributes": {}}

        async def execute(self, target, _parameters):
            self.writes.append(target.capability_id)
            self.states[target.capability_id] = "on"
            return {"ok": True}

        def verify(self, _target, _parameters, _before, after, result):
            return result["ok"] and after["state"] == "on"

    executor = Executor()
    boundary = ExecutionBoundary(executor)
    first = asyncio.run(boundary.execute_batch_proposal(
        capability_ids=("light", "switch"), expected_profile_revision="current", current_profile_revision="current", request_id="same-request"
    ))
    replay = asyncio.run(boundary.execute_batch_proposal(
        capability_ids=("light", "switch"), expected_profile_revision="current", current_profile_revision="current", request_id="same-request"
    ))
    assert first["response_key"] == replay["response_key"] == "batch_execute_verified"
    assert first["verified_count"] == replay["verified_count"] == 2
    assert executor.writes == ["light", "switch"]


def test_toggle_request_is_retryable_and_not_replayed_from_a_success_receipt():
    target = CapabilityTarget("toggle", "toggle", "light.one", "light", "toggle", operation_spec("light", "toggle"))

    class Executor:
        def __init__(self):
            self.state = "off"
            self.writes = 0

        def profile_current(self, _revision):
            return True

        async def resolve_capability(self, capability_id):
            return target if capability_id == "toggle" else None

        async def read_state(self, _target):
            return {"state": self.state, "attributes": {}}

        async def execute(self, _target, _parameters):
            self.writes += 1
            self.state = "on" if self.state == "off" else "off"
            return {"ok": True}

        def verify(self, _target, _parameters, before, after, result):
            return result["ok"] and before["state"] != after["state"]

    executor = Executor()
    boundary = ExecutionBoundary(executor)
    for _attempt in range(2):
        result = asyncio.run(boundary.execute_proposal(
            capability_id="toggle", parameters={}, expected_profile_revision="current",
            current_profile_revision="current", confirmed=False, request_id="retry",
        ))
        assert result["response_key"] == "execute_verified"
    assert executor.writes == 2
