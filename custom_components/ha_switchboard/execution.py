"""Core-side capability resolution, bounded parameters, and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import TYPE_CHECKING, Any, Mapping, Protocol
import hashlib
import json

if TYPE_CHECKING:
    from homeassistant.core import Context

from .capabilities import CapabilityMap, CapabilityTarget

try:  # pragma: no cover - available in the Home Assistant runtime
    from homeassistant.exceptions import HomeAssistantError
except ImportError:  # pragma: no cover - host-side contract tests
    class HomeAssistantError(Exception):
        """Fallback marker for environments without Home Assistant."""


_CORE_EXECUTION_ERRORS = (HomeAssistantError, RuntimeError, ValueError, TypeError, OSError)


_CORE_EXECUTABLE_OPERATIONS = frozenset(
    {
        ("light", "turn_on"),
        ("light", "turn_off"),
        ("light", "toggle"),
        ("light", "set_brightness"),
        ("switch", "turn_on"),
        ("switch", "turn_off"),
        ("switch", "toggle"),
        ("fan", "turn_on"),
        ("fan", "turn_off"),
        ("fan", "toggle"),
        ("media_player", "turn_on"),
        ("media_player", "turn_off"),
        ("media_player", "play"),
        ("media_player", "pause"),
        ("media_player", "stop"),
        ("media_player", "set_volume"),
        ("climate", "set_temperature"),
        ("climate", "set_hvac_mode"),
        ("lock", "lock"),
        ("lock", "unlock"),
        ("cover", "open_cover"),
        ("cover", "close_cover"),
        ("garage", "open_cover"),
        ("garage", "close_cover"),
    }
)


class ParameterValidationError(ValueError):
    """A parameter is not allowed by the Core-owned operation schema."""


class HomeAssistantExecutor(Protocol):
    async def resolve_capability(self, capability_id: str) -> CapabilityTarget | None: ...

    async def execute(
        self, target: CapabilityTarget, parameters: Mapping[str, Any], *, context: Context | None = None
    ) -> Mapping[str, Any]: ...

    async def read_state(self, target: CapabilityTarget) -> Mapping[str, Any]: ...

    def verify(
        self,
        target: CapabilityTarget,
        parameters: Mapping[str, Any],
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool: ...


def validate_parameters(target: CapabilityTarget, parameters: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(parameters, Mapping) or len(parameters) > 8:
        raise ParameterValidationError("parameters must be a bounded object")
    schema = target.parameter_schema
    properties = schema.get("properties", {}) if isinstance(schema, Mapping) else {}
    if not isinstance(properties, Mapping):
        raise ParameterValidationError("invalid parameter schema")
    required = schema.get("required", ()) if isinstance(schema, Mapping) else ()
    if not isinstance(required, (list, tuple)) or set(required) - set(parameters):
        raise ParameterValidationError("required parameter is missing")
    unknown = set(parameters) - set(properties)
    if unknown:
        raise ParameterValidationError("unknown parameter")

    result: dict[str, Any] = {}
    for key, value in parameters.items():
        spec = properties.get(key, {})
        if not isinstance(spec, Mapping):
            raise ParameterValidationError("invalid parameter definition")
        kind = spec.get("type")
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise ParameterValidationError(f"{key} must be numeric")
            number = float(value)
            if "minimum" in spec and number < float(spec["minimum"]):
                raise ParameterValidationError(f"{key} is below its minimum")
            if "maximum" in spec and number > float(spec["maximum"]):
                raise ParameterValidationError(f"{key} is above its maximum")
            result[key] = number
        elif kind == "string":
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ParameterValidationError(f"{key} must be bounded text")
            values = spec.get("enum")
            if values and value not in values:
                raise ParameterValidationError(f"{key} is not an allowed value")
            result[key] = value
        else:
            raise ParameterValidationError("unsupported parameter type")
    return result


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def verify_operation(
    target: CapabilityTarget,
    parameters: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    result: Mapping[str, Any],
) -> bool:
    if not bool(result.get("ok", False)):
        return False
    after_state = str(after.get("state", "unknown"))
    if after_state in {"unknown", "unavailable"}:
        return False
    expected = {
        "turn_on": {"on", "playing"},
        "turn_off": {"off"},
        "play": {"playing"},
        "pause": {"paused"},
        "stop": {"idle", "off", "standby"},
        "lock": {"locked"},
        "unlock": {"unlocked"},
        "open_cover": {"open", "opening"},
        "close_cover": {"closed", "closing"},
    }.get(target.operation)
    if expected is not None:
        return after_state in expected
    if target.operation == "toggle":
        return after_state != str(before.get("state", "unknown"))
    attrs = after.get("attributes", {})
    if not isinstance(attrs, Mapping):
        attrs = {}
    if target.operation == "set_brightness":
        actual = _number(attrs.get("brightness_pct"))
        if actual is None:
            raw = _number(attrs.get("brightness"))
            actual = None if raw is None else raw * 100 / 255
        requested = _number(parameters.get("brightness"))
        return actual is not None and requested is not None and abs(actual - requested) <= 2.0
    if target.operation == "set_volume":
        actual = _number(attrs.get("volume_level"))
        requested = _number(parameters.get("volume"))
        return actual is not None and requested is not None and abs(actual - requested) <= 0.02
    if target.operation == "set_temperature":
        actual = _number(attrs.get("temperature"))
        requested = _number(parameters.get("temperature"))
        return actual is not None and requested is not None and abs(actual - requested) <= 0.2
    if target.operation == "set_hvac_mode":
        return attrs.get("hvac_mode") == parameters.get("hvac_mode") or after_state == parameters.get("hvac_mode")
    if target.operation == "activate":
        before_attrs = before.get("attributes", {})
        after_attrs = after.get("attributes", {})
        return isinstance(before_attrs, Mapping) and isinstance(after_attrs, Mapping) and after_attrs.get("last_triggered") != before_attrs.get("last_triggered")
    return False


@dataclass(slots=True)
class ExecutionBoundary:
    executor: HomeAssistantExecutor
    diagnostics: Any = None
    _receipts: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._receipts.clear()

    def _record_outcome(
        self,
        result: Mapping[str, Any],
        *,
        request_id: str | None,
        operation: str,
        **fields: Any,
    ) -> None:
        """Record only bounded outcome metadata; never target references."""

        if self.diagnostics is None:
            return
        ok = bool(result.get("ok", False))
        self.diagnostics.record(
            "execution_outcome",
            level="info" if ok else "warning",
            correlation_id=request_id,
            operation=operation,
            outcome=str(result.get("response_key", "unknown")),
            **fields,
        )

    def _idempotency_key(self, request_id: str, capability_ids: tuple[str, ...], operation: str) -> str:
        return hashlib.sha256(json.dumps([request_id, capability_ids, operation], sort_keys=True).encode()).hexdigest()

    async def execute_batch_proposal(
        self,
        *,
        capability_ids: tuple[str, ...],
        expected_profile_revision: str,
        current_profile_revision: str,
        context: Context | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = await self._execute_batch_proposal(
                capability_ids=capability_ids,
                expected_profile_revision=expected_profile_revision,
                current_profile_revision=current_profile_revision,
                context=context,
                request_id=request_id,
            )
        except _CORE_EXECUTION_ERRORS as exc:
            if self.diagnostics is not None:
                self.diagnostics.record_exception(
                    exc,
                    correlation_id=request_id,
                    operation="batch",
                )
            result = {
                "ok": False,
                "response_key": "batch_partial_failure",
                "verified_count": 0,
                "total_count": len(capability_ids),
            }
        self._record_outcome(
            result,
            request_id=request_id,
            operation="batch",
            verified_count=result.get("verified_count", 0),
            total_count=result.get("total_count", len(capability_ids)),
        )
        return result

    async def _execute_batch_proposal(
        self,
        *,
        capability_ids: tuple[str, ...],
        expected_profile_revision: str,
        current_profile_revision: str,
        context: Context | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Preflight every routine target before the first write, then verify each.

        Home Assistant service calls are not transactional. Stop at the first
        failure and report the verified count instead of claiming all succeeded.
        """

        if not 1 <= len(capability_ids) <= 32 or len(set(capability_ids)) != len(capability_ids):
            return {"ok": False, "response_key": "batch_invalid", "verified_count": 0, "total_count": len(capability_ids)}
        if expected_profile_revision != current_profile_revision:
            return {"ok": False, "response_key": "profile_stale", "verified_count": 0, "total_count": len(capability_ids)}
        current_check = getattr(self.executor, "profile_current", None)
        if callable(current_check) and not current_check(expected_profile_revision):
            return {"ok": False, "response_key": "profile_stale", "verified_count": 0, "total_count": len(capability_ids)}

        targets: list[CapabilityTarget] = []
        before_states: list[Mapping[str, Any]] = []
        for capability_id in capability_ids:
            target = await self.executor.resolve_capability(capability_id)
            if target is None or target.domain not in {"light", "switch", "fan"} or target.operation not in {"turn_on", "turn_off"} or target.risk_class != "routine":
                return {"ok": False, "response_key": "batch_target_unavailable", "verified_count": 0, "total_count": len(capability_ids)}
            try:
                validate_parameters(target, {})
            except ParameterValidationError:
                return {"ok": False, "response_key": "batch_target_unavailable", "verified_count": 0, "total_count": len(capability_ids)}
            before = await self.executor.read_state(target)
            if str(before.get("state", "unknown")) in {"unknown", "unavailable"}:
                return {"ok": False, "response_key": "batch_target_unavailable", "verified_count": 0, "total_count": len(capability_ids)}
            targets.append(target)
            before_states.append(before)
        if len({target.entity_id for target in targets}) != len(targets):
            return {"ok": False, "response_key": "batch_invalid", "verified_count": 0, "total_count": len(capability_ids)}
        if len({target.operation for target in targets}) != 1:
            return {"ok": False, "response_key": "batch_invalid", "verified_count": 0, "total_count": len(capability_ids)}

        operation = targets[0].operation
        if request_id and operation != "toggle":
            key = self._idempotency_key(request_id, capability_ids, operation)
            prior = self._receipts.get(key)
            if prior is not None:
                return dict(prior)

        verified_count = 0
        target_results: list[dict[str, Any]] = []
        for target, before in zip(targets, before_states):
            if callable(current_check) and not current_check(expected_profile_revision):
                result = {"ok": False, "response_key": "batch_partial_failure", "verified_count": verified_count, "total_count": len(targets)}
                if request_id:
                    result["target_results"] = target_results
                if request_id and operation != "toggle":
                    self._receipts[key] = dict(result)
                return result
            try:
                if context is None:
                    result = await self.executor.execute(target, {})
                else:
                    result = await self.executor.execute(target, {}, context=context)
                after = await self.executor.read_state(target)
                if not self.executor.verify(target, {}, before, after, result):
                    failure = {"ok": False, "response_key": "batch_partial_failure", "verified_count": verified_count, "total_count": len(targets)}
                    if request_id:
                        failure["target_results"] = target_results
                    if request_id and operation != "toggle":
                        self._receipts[key] = dict(failure)
                    return failure
            except _CORE_EXECUTION_ERRORS as exc:
                if self.diagnostics is not None:
                    self.diagnostics.record_exception(
                        exc,
                        correlation_id=request_id,
                        operation="batch",
                        target_count=len(targets),
                    )
                result = {"ok": False, "response_key": "batch_partial_failure", "verified_count": verified_count, "total_count": len(targets)}
                if request_id:
                    result["target_results"] = target_results
                if request_id and operation != "toggle":
                    self._receipts[key] = dict(result)
                return result
            target_results.append({"capability_id": target.capability_id, "display_name": target.display_name or target.domain, "verified": True})
            verified_count += 1
        result = {"ok": True, "response_key": "batch_execute_verified", "verified_count": verified_count, "total_count": len(targets)}
        if request_id:
            result["target_results"] = target_results
        if request_id and operation != "toggle":
            self._receipts[key] = dict(result)
        return result

    async def execute_proposal(
        self,
        *,
        capability_id: str,
        parameters: Mapping[str, Any],
        expected_profile_revision: str,
        current_profile_revision: str,
        confirmed: bool,
        context: Context | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = await self._execute_proposal(
                capability_id=capability_id,
                parameters=parameters,
                expected_profile_revision=expected_profile_revision,
                current_profile_revision=current_profile_revision,
                confirmed=confirmed,
                context=context,
                request_id=request_id,
            )
        except _CORE_EXECUTION_ERRORS as exc:
            if self.diagnostics is not None:
                self.diagnostics.record_exception(
                    exc,
                    correlation_id=request_id,
                    operation="execute",
                )
            result = {"ok": False, "response_key": "execution_failed"}
        self._record_outcome(result, request_id=request_id, operation="execute")
        return result

    async def _execute_proposal(
        self,
        *,
        capability_id: str,
        parameters: Mapping[str, Any],
        expected_profile_revision: str,
        current_profile_revision: str,
        confirmed: bool,
        context: Context | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if expected_profile_revision != current_profile_revision:
            return {"ok": False, "response_key": "profile_stale"}
        current_check = getattr(self.executor, "profile_current", None)
        if callable(current_check) and not current_check(expected_profile_revision):
            return {"ok": False, "response_key": "profile_stale"}
        target = await self.executor.resolve_capability(capability_id)
        if target is None:
            return {"ok": False, "response_key": "candidate_not_allowed"}
        if (target.domain, target.operation) not in _CORE_EXECUTABLE_OPERATIONS:
            return {"ok": False, "response_key": "candidate_not_allowed"}
        try:
            clean_parameters = validate_parameters(target, parameters)
        except ParameterValidationError:
            return {"ok": False, "response_key": "invalid_parameters"}
        if target.risk_class == "blocked":
            return {"ok": False, "response_key": "policy_denied"}
        if target.risk_class == "confirm" and not confirmed:
            return {"ok": False, "response_key": "confirmation_required"}
        idempotency_key = None
        if request_id and target.operation != "toggle":
            idempotency_key = self._idempotency_key(request_id, (capability_id,), target.operation)
            prior = self._receipts.get(idempotency_key)
            if prior is not None:
                return dict(prior)
        try:
            before = await self.executor.read_state(target)
        except _CORE_EXECUTION_ERRORS as exc:
            if self.diagnostics is not None:
                self.diagnostics.record_exception(
                    exc,
                    correlation_id=request_id,
                    operation="read_before",
                )
            failure = {"ok": False, "response_key": "execution_failed"}
            return failure
        if str(before.get("state", "unknown")) in {"unknown", "unavailable"}:
            return {"ok": False, "response_key": "candidate_not_allowed"}
        try:
            if context is None:
                result = await self.executor.execute(target, clean_parameters)
            else:
                result = await self.executor.execute(target, clean_parameters, context=context)
            after = await self.executor.read_state(target)
            verified = self.executor.verify(target, clean_parameters, before, after, result)
        except _CORE_EXECUTION_ERRORS as exc:
            if self.diagnostics is not None:
                self.diagnostics.record_exception(
                    exc,
                    correlation_id=request_id,
                    operation=target.operation,
                )
            failure = {"ok": False, "response_key": "execution_failed"}
            return failure
        result_payload = {
            "ok": verified,
            "response_key": "execute_verified" if verified else "post_action_unverified",
            "pre_state": dict(before),
            "post_state": dict(after),
            "result": {"ok": bool(result.get("ok", False))},
        }
        if idempotency_key:
            self._receipts[idempotency_key] = dict(result_payload)
        return result_payload


class CoreHomeAssistantExecutor:
    """Resolve and execute only through the revision-bound Core target map."""

    def __init__(self, hass: Any, capability_map: CapabilityMap, coordinator: Any = None) -> None:
        self.hass = hass
        self.capability_map = capability_map
        self.coordinator = coordinator

    def profile_current(self, revision: str) -> bool:
        return self.coordinator is None or self.coordinator.writes_allowed(revision)

    async def resolve_capability(self, capability_id: str) -> CapabilityTarget | None:
        return self.capability_map.get(capability_id)

    async def execute(
        self, target: CapabilityTarget, parameters: Mapping[str, Any], *, context: Context | None = None
    ) -> Mapping[str, Any]:
        services = getattr(self.hass, "services", None)
        call = getattr(services, "async_call", None)
        if not callable(call):
            return {"ok": False}
        call_kwargs: dict[str, Any] = {"blocking": True}
        if context is not None:
            call_kwargs["context"] = context
        await call(
            target.spec.service_domain,
            target.spec.service,
            {"entity_id": target.entity_id, **target.service_data(parameters)},
            **call_kwargs,
        )
        return {"ok": True}

    async def read_state(self, target: CapabilityTarget) -> Mapping[str, Any]:
        states = getattr(self.hass, "states", None)
        getter = getattr(states, "get", None)
        state = getter(target.entity_id) if callable(getter) else None
        if state is None:
            return {"state": "unavailable", "attributes": {}}
        attrs = state.attributes if hasattr(state, "attributes") else state.get("attributes", {})
        attrs = attrs if isinstance(attrs, Mapping) else {}
        allowed = {"brightness", "brightness_pct", "volume_level", "temperature", "hvac_mode", "last_triggered"}
        raw_state = state.state if hasattr(state, "state") else state.get("state", "unknown")
        return {"state": str(raw_state), "attributes": {key: attrs[key] for key in allowed if key in attrs}}

    def verify(
        self,
        target: CapabilityTarget,
        parameters: Mapping[str, Any],
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool:
        return verify_operation(target, parameters, before, after, result)
