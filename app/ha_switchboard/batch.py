"""Bounded routine groups derived from the active sanitized profile."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .protocol import Capability, HomeProfile


MAX_BATCH_TARGETS = 32
_DOMAINS = {"lights": "light", "switches": "switch", "fans": "fan"}
_WORD = r"(?<!\w){}(?!\w)"


@dataclass(frozen=True, slots=True)
class BatchGroup:
    group_id: str
    domain: str
    operation: str
    area: str | None
    members: tuple[str, ...]

    def candidate(self) -> dict[str, object]:
        noun = self.domain.replace("_", " ") + "s"
        scope = f" in {self.area}" if self.area else ""
        return {
            "capability_id": self.group_id,
            "display_name": f"All exposed {noun}{scope}: {self.operation.replace('_', ' ')}",
            "kind": "group_action",
            "domain": self.domain,
            "operation": self.operation,
            "area": self.area,
            "member_count": len(self.members),
            "available": True,
            "risk_class": "routine",
            "parameter_schema": {"properties": {}, "required": []},
        }


class BatchRequestError(ValueError):
    """A multi-device request cannot be made into a safe bounded group."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def build_batch_group(utterance: str, profile: HomeProfile) -> BatchGroup | None:
    """Recognize explicit English plural on/off commands; never infer scope."""

    text = " ".join(utterance.casefold().split())
    domains = [domain for plural, domain in _DOMAINS.items() if re.search(_WORD.format(plural), text)]
    if not domains:
        return None
    if len(domains) != 1:
        raise BatchRequestError("batch_scope_ambiguous")
    if re.search(r"\b(?:don't|do not|never|not)\b", text):
        raise BatchRequestError("batch_scope_ambiguous")
    if not re.search(r"\b(?:turn|switch)\b", text):
        return None
    operations = [operation for word, operation in (("on", "turn_on"), ("off", "turn_off")) if re.search(_WORD.format(word), text)]
    if len(operations) != 1:
        raise BatchRequestError("batch_scope_ambiguous")
    operation = operations[0]
    domain = domains[0]

    # A named area must narrow the group; an overlapping/ambiguous area name
    # must not silently fall back to a whole-home action.
    matching_areas = {
        item.area for item in profile.capabilities
        if item.domain == domain and item.area and re.search(_WORD.format(re.escape(item.area.casefold())), text)
    }
    if len(matching_areas) > 1:
        raise BatchRequestError("batch_scope_ambiguous")
    area = next(iter(matching_areas), None)
    if area is None and not (
        re.search(r"\b(?:all|every|each)\b", text)
        or re.search(r"\b(?:the|my)\s+(?:lights|switches|fans)\b", text)
    ):
        return None

    matching: list[Capability] = sorted(
        (
            item for item in profile.capabilities
            if item.domain == domain and item.operation == operation and item.exposed
            and (area is None or item.area == area)
        ),
        key=lambda item: item.capability_id,
    )
    if not matching:
        raise BatchRequestError("batch_no_targets")
    if len(matching) > MAX_BATCH_TARGETS:
        raise BatchRequestError("batch_too_large")
    if any(not item.available or item.risk_class.value != "routine" for item in matching):
        raise BatchRequestError("batch_target_unavailable")
    if len({item.adapter_ref for item in matching}) != len(matching):
        raise BatchRequestError("batch_scope_ambiguous")
    key = f"{profile.revision}:{domain}:{operation}:{area or '*'}"
    group_id = "batch-" + hashlib.sha256(key.encode()).hexdigest()[:24]
    return BatchGroup(group_id, domain, operation, area, tuple(item.capability_id for item in matching))
