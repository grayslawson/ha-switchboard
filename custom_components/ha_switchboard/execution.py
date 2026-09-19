"""Core-side execution boundary for opaque gateway proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import hashlib


def _opaque_capability(value: str) -> str:
    digest = hashlib.sha256(f"capability\0{value}".encode("utf-8")).hexdigest()
    return f"capability-{digest[:20]}"


class HomeAssistantExecutor(Protocol):
    async def resolve_capability(self, capability_id: str) -> Mapping[str, Any] | None: ...

    async def execute(self, target: Mapping[str, Any], parameters: Mapping[str, Any]) -> Mapping[str, Any]: ...

    async def read_state(self, target: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class ExecutionBoundary:
    executor: HomeAssistantExecutor

    async def execute_proposal(
        self,
        *,
        capability_id: str,
        parameters: Mapping[str, Any],
        expected_profile_revision: str,
        current_profile_revision: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        if expected_profile_revision != current_profile_revision:
            return {"ok": False, "response_key": "profile_stale"}
        target = await self.executor.resolve_capability(capability_id)
        if target is None:
            return {"ok": False, "response_key": "candidate_not_allowed"}
        if target.get("risk_class") in {"confirm", "blocked"} and not confirmed:
            return {"ok": False, "response_key": "confirmation_required"}
        pre_state = await self.executor.read_state(target)
        result = await self.executor.execute(target, parameters)
        post_state = await self.executor.read_state(target)
        verified = bool(result.get("ok", False)) and post_state != pre_state
        return {
            "ok": verified,
            "response_key": "execute_verified" if verified else "post_action_unverified",
            "pre_state": dict(pre_state),
            "post_state": dict(post_state),
            "result": {"ok": bool(result.get("ok", False))},
        }


class CoreHomeAssistantExecutor:
    """Small adapter-side executor; raw entity IDs never leave this object."""

    def __init__(self, hass: Any) -> None:
        self.hass = hass

    async def resolve_capability(self, capability_id: str) -> Mapping[str, Any] | None:
        states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []
        for state in states:
            entity_id = getattr(state, "entity_id", "")
            domain = entity_id.split(".", 1)[0]
            for operation in _operations(domain):
                if _opaque_capability(f"{entity_id}:{operation}") == capability_id:
                    return {"entity_id": entity_id, "domain": domain, "operation": operation, "risk_class": "routine"}
        return None

    async def execute(self, target: Mapping[str, Any], parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        await self.hass.services.async_call(
            target["domain"],
            target["operation"],
            {"entity_id": target["entity_id"], **dict(parameters)},
            blocking=True,
        )
        return {"ok": True}

    async def read_state(self, target: Mapping[str, Any]) -> Mapping[str, Any]:
        state = self.hass.states.get(target["entity_id"])
        if state is None:
            return {"state": "unavailable"}
        return {"state": getattr(state, "state", "unknown")}


def _operations(domain: str) -> tuple[str, ...]:
    return {
        "light": ("turn_on", "turn_off", "toggle", "set_brightness"),
        "switch": ("turn_on", "turn_off", "toggle"),
        "fan": ("turn_on", "turn_off", "toggle"),
        "media_player": ("turn_on", "turn_off", "play", "pause", "stop", "set_volume"),
        "climate": ("set_temperature", "set_hvac_mode"),
        "lock": ("lock", "unlock"),
        "cover": ("open_cover", "close_cover"),
    }.get(domain, ())
