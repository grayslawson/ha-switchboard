"""Short-lived, user-bound continuation state for Assist turns.

The store is deliberately Core-local.  It contains the original bounded
request and opaque capability identifiers, never Home Assistant credentials
or raw entity references, and consumes a continuation exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Mapping


_RAW_REFERENCE_KEYS = frozenset({"entity_id", "device_id", "area_id", "unique_id", "config_entry_id"})
_SECRET_KEY_MARKERS = ("token", "password", "secret", "api_key", "authorization")
_MAX_DEPTH = 4
_MAX_TEXT = 2_000
_MAX_ITEMS = 64


def _validate_pending_value(value: Any, *, key: str | None = None, depth: int = 0) -> None:
    """Reject raw Core references and unbounded continuation state."""

    normalized_key = key.casefold() if key else ""
    if normalized_key in _RAW_REFERENCE_KEYS or any(marker in normalized_key for marker in _SECRET_KEY_MARKERS):
        raise ValueError("pending request contains a Core-local or secret field")
    if depth > _MAX_DEPTH:
        raise ValueError("pending request is too deeply nested")
    if isinstance(value, str):
        if len(value) > _MAX_TEXT:
            raise ValueError("pending request text is too long")
        return
    if isinstance(value, Mapping):
        if len(value) > _MAX_ITEMS:
            raise ValueError("pending request mapping is too large")
        for item_key, item in value.items():
            if not isinstance(item_key, str) or len(item_key) > 96:
                raise ValueError("pending request key is invalid")
            _validate_pending_value(item, key=item_key, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_ITEMS:
            raise ValueError("pending request list is too large")
        for item in value:
            _validate_pending_value(item, depth=depth + 1)
        return
    if value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("pending request contains an unsupported value")


@dataclass(frozen=True, slots=True)
class PendingConversation:
    conversation_id: str
    user_id: str | None
    kind: str
    request: Mapping[str, Any]
    created_at: float
    expires_at: float


class ConversationContextStore:
    """Bounded in-memory continuation store with TTL and one-shot consume."""

    def __init__(self, *, ttl: float = 120.0, max_entries: int = 128, clock=monotonic) -> None:
        if ttl <= 0 or max_entries <= 0:
            raise ValueError("context bounds must be positive")
        self.ttl = float(ttl)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._pending: dict[str, PendingConversation] = {}

    def _purge(self, now: float) -> None:
        for key, item in tuple(self._pending.items()):
            if item.expires_at <= now:
                self._pending.pop(key, None)

    def put(self, conversation_id: str, user_id: str | None, kind: str, request: Mapping[str, Any]) -> PendingConversation:
        if not conversation_id or kind not in {"clarification", "confirmation", "parameter"}:
            raise ValueError("invalid pending conversation")
        if not isinstance(request, Mapping) or len(request) > 16:
            raise ValueError("pending request must be bounded")
        _validate_pending_value(request)
        now = self._clock()
        self._purge(now)
        if conversation_id not in self._pending and len(self._pending) >= self.max_entries:
            oldest = min(self._pending, key=lambda key: self._pending[key].created_at)
            self._pending.pop(oldest, None)
        item = PendingConversation(conversation_id, user_id, kind, dict(request), now, now + self.ttl)
        self._pending[conversation_id] = item
        return item

    def peek(self, conversation_id: str, user_id: str | None) -> PendingConversation | None:
        now = self._clock()
        self._purge(now)
        item = self._pending.get(conversation_id)
        if item is None or item.user_id != user_id:
            return None
        return item

    def consume(self, conversation_id: str, user_id: str | None) -> PendingConversation | None:
        item = self.peek(conversation_id, user_id)
        if item is not None:
            self._pending.pop(conversation_id, None)
        return item

    def clear(self, conversation_id: str) -> None:
        self._pending.pop(conversation_id, None)

    def __len__(self) -> int:
        self._purge(self._clock())
        return len(self._pending)
