"""Bounded Core-local diagnostics for HA Switchboard conversations.

The App owns the operator-facing diagnostic stream.  The Core integration
still needs a small local diagnostic buffer so conversation and execution
failures can be correlated without forwarding Home Assistant references,
credentials, or exception messages to the gateway.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping


MAX_EVENTS = 128
MAX_FIELDS = 24
MAX_TEXT = 256
MAX_DEPTH = 4
MAX_LIST_ITEMS = 32

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "gateway_token",
        "password",
        "secret",
        "token",
    }
)
_RAW_REFERENCE_KEYS = frozenset(
    {"area_id", "config_entry_id", "device_id", "entity_id", "unique_id"}
)


def _safe_key(value: Any) -> str:
    return str(value)[:64]


def _safe_value(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    """Return a JSON-safe, bounded value without sensitive references."""

    normalized_key = key.casefold() if key else ""
    if normalized_key in _SECRET_KEYS or any(
        marker in normalized_key for marker in ("api_key", "authorization", "password", "token")
    ):
        return "[redacted]"
    if normalized_key in _RAW_REFERENCE_KEYS:
        return "[core-local]"
    if depth >= MAX_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= MAX_FIELDS:
                result["_truncated"] = True
                break
            safe_key = _safe_key(raw_key)
            result[safe_key] = _safe_value(raw_value, key=safe_key, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _safe_value(item, depth=depth + 1)
            for item in list(value)[:MAX_LIST_ITEMS]
        ]
    return type(value).__name__[:MAX_TEXT]


def safe_exception_code(exc: BaseException) -> str:
    """Map an exception to a stable user/operator-safe category.

    Exception text is intentionally excluded: Home Assistant exceptions may
    contain URLs, entity references, credentials, or provider response data.
    """

    name = type(exc).__name__
    if name == "GatewayClientError":
        return "gateway_unavailable"
    if isinstance(exc, (TimeoutError,)):  # includes asyncio.TimeoutError
        return "gateway_timeout"
    if name == "ParameterValidationError":
        return "invalid_parameters"
    if isinstance(exc, (ValueError, TypeError)):
        return "invalid_request"
    return "core_error"


@dataclass(frozen=True, slots=True)
class CoreDiagnosticEvent:
    """A redacted event retained only by the Core integration."""

    event_id: str
    correlation_id: str
    code: str
    level: str
    occurred_at: float
    fields: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        summary = self.fields.get("summary") or self.code
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "code": self.code,
            "level": self.level,
            "occurred_at": self.occurred_at,
            "summary": str(summary)[:MAX_TEXT],
            "fields": dict(self.fields),
        }


class CoreDiagnosticLog:
    """Small, bounded, secret-safe local event buffer."""

    def __init__(self, *, retention: int = MAX_EVENTS) -> None:
        if not isinstance(retention, int) or isinstance(retention, bool) or not 1 <= retention <= MAX_EVENTS:
            raise ValueError("diagnostic retention is out of bounds")
        self._events: deque[CoreDiagnosticEvent] = deque(maxlen=retention)

    def record(
        self,
        code: str,
        *,
        level: str = "info",
        correlation_id: str | None = None,
        **fields: Any,
    ) -> CoreDiagnosticEvent:
        if not isinstance(code, str) or not code or len(code) > 96:
            raise ValueError("diagnostic code is invalid")
        if level not in {"debug", "info", "warning", "error"}:
            raise ValueError("diagnostic level is invalid")
        if len(fields) > MAX_FIELDS:
            raise ValueError("diagnostic fields exceed bound")
        event = CoreDiagnosticEvent(
            event_id=uuid.uuid4().hex,
            correlation_id=(correlation_id or uuid.uuid4().hex)[:64],
            code=code,
            level=level,
            occurred_at=time.time(),
            fields=_safe_value(fields),
        )
        self._events.append(event)
        return event

    def record_exception(
        self,
        exc: BaseException,
        *,
        correlation_id: str | None = None,
        level: str = "warning",
        **fields: Any,
    ) -> CoreDiagnosticEvent:
        code = safe_exception_code(exc)
        return self.record(
            code,
            level=level,
            correlation_id=correlation_id,
            exception_type=type(exc).__name__[:MAX_TEXT],
            **fields,
        )

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        bounded = max(1, min(limit, MAX_EVENTS))
        return [event.to_dict() for event in list(self._events)[-bounded:]]


__all__ = [
    "CoreDiagnosticEvent",
    "CoreDiagnosticLog",
    "MAX_EVENTS",
    "safe_exception_code",
]
