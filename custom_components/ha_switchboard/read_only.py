"""Bounded Core-local answers for read-only entity-state questions.

This module deliberately never sends a read request to the App.  The Core
integration already owns the live state and the sanitized profile, so a
question is answered locally only when one exposed entity can be identified
unambiguously by its name, alias, or area.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_READ_RE = re.compile(r"\b(is|are|what(?:'s| is)|tell me|show me|how)\b", re.I)
_STATE_RE = re.compile(r"\b(on|off|open|closed|locked|unlocked|playing|paused|idle|unavailable|unknown)\b", re.I)
_MAX_TEXT = 512


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def _state_value(state: Any, key: str, default: Any = None) -> Any:
    if isinstance(state, Mapping):
        return state.get(key, default)
    return getattr(state, key, default)


def _is_read_only(text: str) -> bool:
    if len(text) > _MAX_TEXT or not _READ_RE.search(text):
        return False
    # Do not intercept imperative or mutating requests that happen to contain
    # “is” in a device name or phrase.
    if re.search(r"\b(turn|set|open|close|lock|unlock|start|stop|pause|play|toggle|activate)\b", text, re.I):
        return False
    return bool(_STATE_RE.search(text) or re.search(r"\b(state|status|temperature|humidity|brightness|volume)\b", text, re.I))


def _display_state(domain: str, state: str, attributes: Mapping[str, Any]) -> str:
    if domain == "climate" and attributes.get("temperature") is not None:
        return f"{state} at {attributes['temperature']} degrees."
    if attributes.get("current_temperature") is not None:
        return f"{state}; the temperature is {attributes['current_temperature']} degrees."
    return f"{state}."


def read_only_answer(
    hass: Any,
    text: str,
    profile: Mapping[str, Any],
    capability_map: Any,
    read_targets: Mapping[str, str] | None = None,
) -> str | None:
    """Return safe speech for one exposed entity, or ``None``.

    Parent integration call (before gateway processing):
    ``speech = read_only_answer(hass, request.text, coordinator.snapshot,
    coordinator.capability_map)``.  If it returns a string, use it as the
    conversation response; otherwise continue through the normal gateway.

    ``profile`` contains only sanitized entity rows.  ``capability_map`` is
    Core-local and supplies the opaque-id-to-entity mapping; raw IDs never
    leave this function or appear in speech.
    """
    if not isinstance(text, str) or not _is_read_only(text):
        return None
    rows = profile.get("entities", ()) if isinstance(profile, Mapping) else ()
    if not isinstance(rows, Sequence):
        return None
    query = _norm(text)
    matches: list[tuple[Mapping[str, Any], Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("exposed") or not row.get("available", True):
            continue
        terms = [_norm(row.get("name")), _norm(row.get("area"))]
        aliases = row.get("aliases", ())
        if isinstance(aliases, Sequence) and not isinstance(aliases, (str, bytes)):
            terms.extend(_norm(alias) for alias in aliases)
        terms = [term for term in terms if term]
        if not terms or not any(re.search(rf"\b{re.escape(term)}\b", query) for term in terms):
            continue
        adapter_ref = str(row.get("adapter_ref", ""))
        target = next((item for item in capability_map.values() if getattr(item, "adapter_ref", "") == adapter_ref), None)
        entity_id = read_targets.get(adapter_ref) if read_targets is not None else getattr(target, "entity_id", None)
        if isinstance(entity_id, str) and adapter_ref not in seen:
            matches.append((row, entity_id))
            seen.add(adapter_ref)
    if len(matches) != 1:
        return None
    row, entity_id = matches[0]
    state_obj = getattr(getattr(hass, "states", None), "get", lambda _entity: None)(entity_id)
    if state_obj is None:
        return None
    state = str(_state_value(state_obj, "state", "unknown"))
    if state in {"unknown", "unavailable"}:
        return f"{row.get('name', 'That device')} is {state}."
    attrs = _state_value(state_obj, "attributes", {})
    if not isinstance(attrs, Mapping):
        attrs = {}
    return f"{row.get('name', 'That device')} is {_display_state(str(row.get('domain', '')), state, attrs)}"
