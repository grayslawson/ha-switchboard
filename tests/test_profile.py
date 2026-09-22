from __future__ import annotations

from ha_switchboard.profile import ProfileCompiler, profile_fingerprint
from ha_switchboard.protocol import LifecycleStatus
import pytest


def test_compiler_builds_opaque_capabilities(discovery: dict) -> None:
    profile = ProfileCompiler().compile(discovery, now="2026-09-19T00:00:00Z")
    assert profile.status is LifecycleStatus.ACTIVE
    assert profile.capabilities
    assert all(item.adapter_ref.startswith("adapter-") for item in profile.capabilities)
    assert all("entity_id" not in item for item in profile.to_dict()["capabilities"])
    assert any(item.domain == "light" for item in profile.capabilities)
    assert profile_fingerprint(profile).startswith("sha256:")


def test_unavailable_entities_are_retained_but_not_executable(discovery: dict) -> None:
    profile = ProfileCompiler().compile(discovery)
    unavailable = [item for item in profile.capabilities if item.domain == "switch"]
    assert unavailable
    assert all(not item.available for item in unavailable)


def test_duplicate_aliases_remain_distinct(discovery: dict) -> None:
    profile = ProfileCompiler().compile(discovery)
    lights = [item for item in profile.capabilities if item.domain == "light" and item.operation == "turn_on"]
    assert len(lights) == 2
    assert len({item.capability_id for item in lights}) == 2


def test_malformed_and_oversized_snapshots_fail_closed() -> None:
    compiler = ProfileCompiler()
    with pytest.raises(ValueError, match="entities must be a list"):
        compiler.compile({"entities": {"not": "a list"}})
    with pytest.raises(ValueError, match="entity count exceeds bound"):
        compiler.compile({"entities": [{} for _ in range(2_001)]})


def test_compiler_validates_opaque_groups_and_keeps_invalid_groups_non_executable(discovery: dict) -> None:
    refs = []
    for entity in discovery["entities"][:2]:
        entity["adapter_ref"] = f"adapter-{entity['entity_id'].replace('.', '-') }"
        refs.append(entity["adapter_ref"])
    discovery["organization"]["groups"] = [
        {"adapter_ref": "adapter-group-evening", "name": "Evening lights", "members": refs},
        {"adapter_ref": "adapter-group-unknown", "name": "Unknown", "members": ["adapter-missing"]},
    ]

    profile = ProfileCompiler().compile(discovery)

    evening = next(item for item in profile.groups if item.name == "Evening lights")
    unknown = next(item for item in profile.groups if item.name == "Unknown")
    assert evening.valid and evening.members == tuple(refs)
    assert not unknown.valid and unknown.members == ()
    assert all("entity_id" not in item for item in profile.to_dict()["groups"])


def test_compiler_rejects_duplicate_and_cyclic_group_members(discovery: dict) -> None:
    discovery["entities"][0]["adapter_ref"] = "adapter-light-one"
    discovery["organization"]["groups"] = [
        {"adapter_ref": "adapter-group-a", "name": "A group", "members": ["adapter-group-b"]},
        {"adapter_ref": "adapter-group-b", "name": "B group", "members": ["adapter-group-a"]},
        {"adapter_ref": "adapter-group-duplicate", "name": "Duplicate group", "members": ["adapter-light-one", "adapter-light-one"]},
        {"adapter_ref": "adapter-group-collision", "name": "Collision A", "members": ["adapter-light-one"]},
        {"adapter_ref": "adapter-group-collision", "name": "Collision B", "members": ["adapter-light-one"]},
    ]

    profile = ProfileCompiler().compile(discovery)

    assert all(not item.valid for item in profile.groups)
