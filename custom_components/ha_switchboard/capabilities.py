"""Core-owned capability definitions and the execution target map."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class OperationSpec:
    service_domain: str
    service: str
    parameter_schema: Mapping[str, Any] = field(default_factory=dict)
    risk_class: str = "routine"


_EMPTY = {"properties": {}}
_BRIGHTNESS = {
    "required": ["brightness"],
    "properties": {"brightness": {"type": "number", "minimum": 0, "maximum": 100}},
}
_VOLUME = {
    "required": ["volume"],
    "properties": {"volume": {"type": "number", "minimum": 0, "maximum": 1}},
}
_TEMPERATURE = {
    "required": ["temperature"],
    "properties": {"temperature": {"type": "number", "minimum": 5, "maximum": 35}},
}


OPERATION_SPECS: dict[tuple[str, str], OperationSpec] = {
    ("light", "turn_on"): OperationSpec("light", "turn_on", _EMPTY),
    ("light", "turn_off"): OperationSpec("light", "turn_off", _EMPTY),
    ("light", "toggle"): OperationSpec("light", "toggle", _EMPTY),
    ("light", "set_brightness"): OperationSpec("light", "turn_on", _BRIGHTNESS),
    ("switch", "turn_on"): OperationSpec("switch", "turn_on", _EMPTY),
    ("switch", "turn_off"): OperationSpec("switch", "turn_off", _EMPTY),
    ("switch", "toggle"): OperationSpec("switch", "toggle", _EMPTY),
    ("fan", "turn_on"): OperationSpec("fan", "turn_on", _EMPTY),
    ("fan", "turn_off"): OperationSpec("fan", "turn_off", _EMPTY),
    ("fan", "toggle"): OperationSpec("fan", "toggle", _EMPTY),
    ("media_player", "turn_on"): OperationSpec("media_player", "turn_on", _EMPTY),
    ("media_player", "turn_off"): OperationSpec("media_player", "turn_off", _EMPTY),
    ("media_player", "play"): OperationSpec("media_player", "media_play", _EMPTY),
    ("media_player", "pause"): OperationSpec("media_player", "media_pause", _EMPTY),
    ("media_player", "stop"): OperationSpec("media_player", "media_stop", _EMPTY),
    ("media_player", "set_volume"): OperationSpec("media_player", "volume_set", _VOLUME),
    ("climate", "set_temperature"): OperationSpec("climate", "set_temperature", _TEMPERATURE),
    ("climate", "set_hvac_mode"): OperationSpec(
        "climate", "set_hvac_mode", {"required": ["hvac_mode"], "properties": {"hvac_mode": {"type": "string"}}}
    ),
    ("lock", "lock"): OperationSpec("lock", "lock", _EMPTY, "confirm"),
    ("lock", "unlock"): OperationSpec("lock", "unlock", _EMPTY, "confirm"),
    ("cover", "open_cover"): OperationSpec("cover", "open_cover", _EMPTY, "confirm"),
    ("cover", "close_cover"): OperationSpec("cover", "close_cover", _EMPTY, "confirm"),
    ("garage", "open_cover"): OperationSpec("cover", "open_cover", _EMPTY, "confirm"),
    ("garage", "close_cover"): OperationSpec("cover", "close_cover", _EMPTY, "confirm"),
    ("script", "activate"): OperationSpec("script", "turn_on", _EMPTY),
    ("scene", "activate"): OperationSpec("scene", "turn_on", _EMPTY),
}


@dataclass(frozen=True, slots=True)
class CapabilityTarget:
    capability_id: str
    adapter_ref: str
    entity_id: str
    domain: str
    operation: str
    spec: OperationSpec

    @property
    def risk_class(self) -> str:
        return self.spec.risk_class

    @property
    def parameter_schema(self) -> Mapping[str, Any]:
        return self.spec.parameter_schema

    def service_data(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        if self.operation == "set_brightness":
            return {"brightness_pct": parameters["brightness"]}
        if self.operation == "set_volume":
            return {"volume_level": parameters["volume"]}
        return dict(parameters)


class CapabilityMap:
    """Atomically replaceable map from opaque gateway IDs to Core targets."""

    def __init__(self) -> None:
        self._revision: str | None = None
        self._targets: dict[str, CapabilityTarget] = {}

    @property
    def revision(self) -> str | None:
        return self._revision

    def replace(self, revision: str, targets: Mapping[str, CapabilityTarget]) -> None:
        if not revision or not isinstance(targets, Mapping):
            raise ValueError("a profile revision and capability mapping are required")
        self._targets = dict(targets)
        self._revision = revision

    def clear(self) -> None:
        self._targets = {}
        self._revision = None

    def get(self, capability_id: str) -> CapabilityTarget | None:
        return self._targets.get(capability_id)

    def values(self) -> tuple[CapabilityTarget, ...]:
        return tuple(self._targets.values())

    def __len__(self) -> int:
        return len(self._targets)


def operation_spec(domain: str, operation: str) -> OperationSpec | None:
    return OPERATION_SPECS.get((domain, operation))


def operations_for_domain(domain: str) -> tuple[str, ...]:
    return tuple(operation for candidate_domain, operation in OPERATION_SPECS if candidate_domain == domain)
