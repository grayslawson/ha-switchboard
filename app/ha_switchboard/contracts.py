"""Strict, versioned JSON boundary contracts for the App gateway."""

from __future__ import annotations

from typing import Any, Mapping

from .limits import MAX_CANDIDATES, MAX_CONTEXT_ITEMS, MAX_TEXT, MAX_UTTERANCE
from .protocol import DecisionRequest, DecisionResult

WIRE_VERSION = 1
ERROR_CODES = frozenset(
    {
        "invalid_request", "unauthorized", "forbidden", "not_found", "method_not_allowed",
        "unsupported_media_type", "request_too_large", "rate_limited", "internal_error",
    }
)


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def validate_decision_payload(payload: Mapping[str, Any]) -> DecisionRequest:
    """Validate the public decision shape before it reaches gateway logic."""

    value = _object(payload, "request")
    allowed = {
        "wire_version", "request_id", "conversation_id", "utterance", "language",
        "profile_revision", "policy_revision", "candidates", "bounded_context",
        "sanitized_state", "privacy_mode", "decision_only", "handoff_depth",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("request contains unknown fields")
    if value.get("wire_version", WIRE_VERSION) != WIRE_VERSION:
        raise ValueError("unsupported wire version")
    candidates = value.get("candidates", ())
    context = value.get("bounded_context", ())
    if not isinstance(candidates, (list, tuple)) or len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidates exceeds bound")
    if not isinstance(context, (list, tuple)) or len(context) > MAX_CONTEXT_ITEMS:
        raise ValueError("bounded_context exceeds bound")
    utterance = value.get("utterance")
    if not isinstance(utterance, str) or not utterance.strip() or len(utterance) > MAX_UTTERANCE:
        raise ValueError("utterance exceeds bound")
    return DecisionRequest.from_dict(value)


def validate_result_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = _object(payload, "result")
    if value.get("wire_version", WIRE_VERSION) != WIRE_VERSION:
        raise ValueError("unsupported wire version")
    required = {"kind", "request_id", "profile_revision", "policy_revision", "response_key"}
    if not required <= value.keys():
        raise ValueError("result is missing required fields")
    for field in ("request_id", "profile_revision", "policy_revision", "response_key"):
        if not isinstance(value[field], str) or not value[field] or len(value[field]) > 128:
            raise ValueError(f"{field} is invalid")
    if "text" in value and value["text"] is not None and (
        not isinstance(value["text"], str) or len(value["text"]) > MAX_TEXT
    ):
        raise ValueError("result text exceeds bound")
    return value


def error_envelope(code: str, *, trace_id: str | None = None) -> dict[str, Any]:
    if code not in ERROR_CODES:
        code = "internal_error"
    result: dict[str, Any] = {"error": {"code": code}}
    if trace_id:
        result["error"]["trace_id"] = trace_id[:32]
    return result
