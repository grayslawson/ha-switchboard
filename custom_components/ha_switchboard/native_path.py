"""Conservative gate for Home Assistant's native conversation fast path.

The gate only inspects Home Assistant's already-recognized intent metadata. It
does not resolve entities, inspect registries, or invoke services; Home
Assistant's native intent handler remains the sole owner of those operations.
Unknown, missing, or non-routine targets stay on Switchboard's normal route.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_ROUTINE_TOGGLE_INTENTS = frozenset({"HassTurnOn", "HassTurnOff", "HassToggle"})
_ROUTINE_DOMAINS = frozenset({"light", "switch", "fan"})


def _slot_values(result: Any, slot_name: str) -> frozenset[str]:
    entities = getattr(result, "entities", None)
    if not isinstance(entities, Mapping):
        return frozenset()
    slot = entities.get(slot_name)
    if slot is None:
        return frozenset()
    value = getattr(slot, "value", slot)
    if isinstance(value, str):
        return frozenset({value.casefold()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(str(item).casefold() for item in value)
    return frozenset()


def is_routine_native_intent(result: Any) -> bool:
    """Return whether a recognized intent may bypass the remote gateway.

    ``HassLightSet`` is intrinsically light-scoped. Generic turn/toggle
    intents must carry a recognized routine domain so that a bare "turn on"
    or a lock/cover target cannot bypass Switchboard policy.
    """

    intent = getattr(result, "intent", None)
    intent_name = getattr(intent, "name", None)
    if intent_name == "HassLightSet":
        return True
    if intent_name not in _ROUTINE_TOGGLE_INTENTS:
        return False
    domains = _slot_values(result, "domain")
    return bool(domains) and domains <= _ROUTINE_DOMAINS


def native_intent_filter(result: Any) -> bool:
    """Return the Home Assistant filter value for non-routine intents."""

    return not is_routine_native_intent(result)


__all__ = ["is_routine_native_intent", "native_intent_filter"]
