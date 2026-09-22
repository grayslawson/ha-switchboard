from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.ha_switchboard.capabilities import (
    OPERATION_SPECS,
    CapabilityMap,
    CapabilityTarget,
    OperationSpec,
    operations_for_domain,
    operation_spec,
)
from custom_components.ha_switchboard.profile_adapter import OPERATION_KEYS
from custom_components.ha_switchboard.execution import CoreHomeAssistantExecutor, ExecutionBoundary


PUBLISHED = {
    "light": {"turn_on", "turn_off", "toggle", "set_brightness"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle"},
    "media_player": {"turn_on", "turn_off", "play", "pause", "stop", "set_volume"},
    "climate": {"set_temperature", "set_hvac_mode"},
    "cover": {"open_cover", "close_cover"},
    "garage": {"open_cover", "close_cover"},
    "lock": {"lock", "unlock"},
}


def test_published_operation_matrix_is_complete_and_typed() -> None:
    assert {domain for domain, _operation in OPERATION_SPECS} == set(PUBLISHED)
    assert not {domain for domain, _operation in OPERATION_KEYS()} & {"script", "scene"}
    for domain, operations in PUBLISHED.items():
        assert set(operations_for_domain(domain)) == operations
        for operation in operations:
            spec = operation_spec(domain, operation)
            assert spec is not None
            assert spec.service_domain
            assert spec.service
            assert isinstance(spec.parameter_schema, dict)


@pytest.mark.parametrize("domain", ["script", "scene"])
def test_script_and_scene_are_not_published_or_core_executable(domain: str) -> None:
    assert domain not in PUBLISHED
    assert operations_for_domain(domain) == ()
    assert operation_spec(domain, "activate") is None

    async def run() -> dict:
        target = CapabilityTarget(
            f"{domain}-opaque",
            f"{domain}-ref",
            f"{domain}.fixture",
            domain,
            "activate",
            # A stale or hand-built map must not turn an unsupported target
            # back into an executable operation.
            OperationSpec(domain, "turn_on"),
        )
        mapping = CapabilityMap()
        mapping.replace("profile-one", {target.capability_id: target})
        boundary = ExecutionBoundary(CoreHomeAssistantExecutor(object(), mapping))
        return await boundary.execute_proposal(
            capability_id=target.capability_id,
            parameters={},
            expected_profile_revision="profile-one",
            current_profile_revision="profile-one",
            confirmed=True,
        )

    result = asyncio.run(run())
    assert result == {"ok": False, "response_key": "candidate_not_allowed"}


def test_supported_core_operation_remains_executable() -> None:
    async def run() -> dict:
        target = CapabilityTarget(
            "light-opaque",
            "light-ref",
            "light.fixture",
            "light",
            "turn_on",
            operation_spec("light", "turn_on"),
        )
        mapping = CapabilityMap()
        mapping.replace("profile-one", {target.capability_id: target})
        state = {"state": "off", "attributes": {}}

        async def async_call(domain, service, data, *, blocking):
            assert (domain, service, data, blocking) == (
                "light",
                "turn_on",
                {"entity_id": "light.fixture"},
                True,
            )
            state["state"] = "on"

        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _entity_id: state),
            services=SimpleNamespace(async_call=async_call),
        )
        boundary = ExecutionBoundary(CoreHomeAssistantExecutor(hass, mapping))
        return await boundary.execute_proposal(
            capability_id=target.capability_id,
            parameters={},
            expected_profile_revision="profile-one",
            current_profile_revision="profile-one",
            confirmed=False,
        )

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["response_key"] == "execute_verified"
