"""Bounded, redacted structured diagnostics for operator-visible state."""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from .limits import MAX_DIAGNOSTIC_EVENTS, MAX_DIAGNOSTIC_FIELDS, MAX_TEXT
from .redaction import SensitiveDataError, sanitize_for_gateway


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    event_id: str
    correlation_id: str
    code: str
    level: str
    occurred_at: float
    fields: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        summary = self.fields.get("summary") or self.fields.get("message") or self.code
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "code": self.code,
            "event_type": self.code,
            "level": self.level,
            "occurred_at": self.occurred_at,
            "summary": str(summary)[:MAX_TEXT],
            "fields": dict(self.fields),
        }


class DiagnosticLog:
    def __init__(self, *, retention: int = MAX_DIAGNOSTIC_EVENTS) -> None:
        if not 1 <= retention <= MAX_DIAGNOSTIC_EVENTS:
            raise ValueError("diagnostic retention is out of bounds")
        self._events: deque[DiagnosticEvent] = deque(maxlen=retention)

    def record(self, code: str, *, level: str = "info", correlation_id: str | None = None, **fields: Any) -> DiagnosticEvent:
        if not code or len(code) > 96 or level not in {"debug", "info", "warning", "error"}:
            raise ValueError("invalid diagnostic metadata")
        if len(fields) > MAX_DIAGNOSTIC_FIELDS:
            raise ValueError("diagnostic fields exceed bound")
        try:
            safe = sanitize_for_gateway(fields)
        except SensitiveDataError as exc:
            raise ValueError("diagnostic contains sensitive data") from exc
        event = DiagnosticEvent(
            event_id=uuid.uuid4().hex,
            correlation_id=(correlation_id or uuid.uuid4().hex)[:64],
            code=code,
            level=level,
            occurred_at=time.time(),
            fields=safe,
        )
        self._events.append(event)
        return event

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, MAX_DIAGNOSTIC_EVENTS))
        return [event.to_dict() for event in list(self._events)[-limit:]]

    def query(
        self,
        *,
        page: int = 1,
        limit: int = 20,
        level: str | None = None,
        event_type: str | None = None,
        correlation_id: str | None = None,
        route_class: str | None = None,
        outcome: str | None = None,
    ) -> dict[str, Any]:
        """Return one bounded, redacted page for the ingress diagnostics view."""

        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page must be a positive integer")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, MAX_DIAGNOSTIC_EVENTS))
        filters = {
            "level": level,
            "event_type": event_type,
            "correlation_id": correlation_id,
            "route_class": route_class,
            "outcome": outcome,
        }
        for name, value in filters.items():
            if value is not None and (not isinstance(value, str) or len(value) > 96):
                raise ValueError(f"{name} filter is invalid")

        def matches(event: DiagnosticEvent) -> bool:
            if level and event.level != level:
                return False
            if event_type and event.code != event_type:
                return False
            if correlation_id and event.correlation_id != correlation_id:
                return False
            if route_class and event.fields.get("route_class") != route_class:
                return False
            if outcome and event.fields.get("outcome") != outcome:
                return False
            return True

        selected = [event for event in self._events if matches(event)]
        total = len(selected)
        start = (page - 1) * limit
        events = [event.to_dict() for event in selected[start : start + limit]]
        return {
            "events": events,
            "page": page,
            "limit": limit,
            "total": total,
            "has_more": start + len(events) < total,
        }

    def safe_exception(self, exc: BaseException) -> str:
        return type(exc).__name__[:MAX_TEXT]
