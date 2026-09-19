"""Minimize data crossing the gateway/provider boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


class SensitiveDataError(ValueError):
    """Raised when a credential or private Home Assistant reference crosses a boundary."""


SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "access_token",
        "api_key",
        "apikey",
        "bearer",
        "cookie",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)

RAW_REFERENCE_KEYS = frozenset({"entity_id", "device_id", "area_id", "unique_id", "config_entry_id"})
PRIVATE_STATE_KEYS = frozenset(
    {
        "camera",
        "latitude",
        "longitude",
        "location",
        "occupancy",
        "person",
        "presence",
        "alarm_code",
        "pin",
        "user_id",
    }
)


def opaque_id(namespace: str, value: str, *, length: int = 20) -> str:
    """Return a stable non-reversible identifier for an adapter-local value."""

    if not namespace or not value:
        raise ValueError("namespace and value are required")
    digest = hashlib.sha256(f"{namespace}\0{value}".encode("utf-8")).hexdigest()
    return f"{namespace[:16]}-{digest[:length]}"


def _key_is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or normalized.endswith("_token")


def sanitize_for_gateway(value: Any, *, reject_references: bool = True) -> Any:
    """Copy JSON-like data while rejecting credentials and raw HA references.

    The function intentionally fails instead of silently masking a credential.
    Silent masking can make an integration appear safe while still sending
    malformed or unexpectedly private context to a provider.
    """

    def visit(item: Any, key: str | None = None) -> Any:
        if key is not None and _key_is_sensitive(key):
            raise SensitiveDataError(f"sensitive field {key!r} is not allowed")
        if reject_references and key is not None and key.lower() in RAW_REFERENCE_KEYS:
            raise SensitiveDataError(f"raw Home Assistant reference {key!r} is not allowed")
        if isinstance(item, Mapping):
            if len(item) > 128:
                raise SensitiveDataError("object exceeds bounded field count")
            return {str(k): visit(v, str(k)) for k, v in item.items()}
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            if len(item) > 128:
                raise SensitiveDataError("list exceeds bounded item count")
            return [visit(v, key) for v in item]
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str) and len(item) > 4_000:
                raise SensitiveDataError("text value exceeds bound")
            return item
        raise SensitiveDataError(f"unsupported value type {type(item).__name__}")

    return visit(value)


def sanitize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Remove privacy-sensitive state while preserving bounded useful facts."""

    if not isinstance(state, Mapping):
        raise SensitiveDataError("state must be an object")
    filtered = {key: value for key, value in state.items() if key.lower() not in PRIVATE_STATE_KEYS}
    return sanitize_for_gateway(filtered)


def sanitized_json(value: Any) -> str:
    """Serialize a validated payload deterministically for hashing or transport."""

    return json.dumps(sanitize_for_gateway(value), sort_keys=True, separators=(",", ":"))


def assert_no_secrets(value: Any) -> None:
    """Recursively verify that a value contains no credential-like field names."""

    sanitize_for_gateway(value, reject_references=False)
