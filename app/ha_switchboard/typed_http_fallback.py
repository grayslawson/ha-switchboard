"""Strict HTTP adapter for the normalized fallback provider contract."""

from __future__ import annotations

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from .handoff import HandoffError, validate_response
from .http_security import RetryPolicy
from .protocol import HandoffRequest, ModelRoute
from .redaction import SensitiveDataError, open_provider_url, require_secure_provider_endpoint, sanitize_for_gateway

_LOG = logging.getLogger("ha_switchboard.typed_http_fallback")
MAX_REQUEST_BYTES = 32_000
MAX_RESPONSE_BYTES = 32_000
MAX_API_KEY = 512
MAX_ENDPOINT = 2_048
_RETRY_POLICY = RetryPolicy(attempts=2, base_delay=0.25, max_delay=2.0)
_RETRYABLE_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def _read_provider_response(request: urllib.request.Request, *, timeout: float) -> bytes:
    last_error: Exception | None = None
    for attempt in range(_RETRY_POLICY.attempts + 1):
        try:
            with open_provider_url(request, timeout=timeout) as response:
                return response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_HTTP_STATUS or not _RETRY_POLICY.can_retry(attempt):
                raise
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            if not _RETRY_POLICY.can_retry(attempt):
                raise
            last_error = exc
        time.sleep(_RETRY_POLICY.delay(attempt))
    assert last_error is not None
    raise last_error


class TypedHttpFallbackError(HandoffError):
    """A typed provider could not satisfy the normalized contract."""


class TypedHttpFallbackUnavailable(TypedHttpFallbackError):
    """Transport, endpoint, or provider availability failure."""


class TypedHttpFallbackInvalidResponse(TypedHttpFallbackError):
    """Provider returned malformed or unsafe JSON."""


@dataclass(slots=True)
class TypedHttpFallbackAdapter:
    endpoint: str
    api_key: str | None = None
    api_key_env: str = "FALLBACK_API_KEY"
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint.strip() or len(self.endpoint) > MAX_ENDPOINT:
            raise ValueError("typed fallback endpoint is invalid")
        self.endpoint = self.endpoint.strip()
        parsed = urlsplit(self.endpoint)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("typed fallback endpoint must not contain credentials or query data")
        if self.api_key is not None and (not isinstance(self.api_key, str) or len(self.api_key) > MAX_API_KEY):
            raise ValueError("typed fallback API key is invalid")
        if not 0.2 <= self.timeout <= 15.0:
            raise ValueError("typed fallback timeout is outside its bound")
        try:
            require_secure_provider_endpoint(self.endpoint, has_credentials=bool(self.api_key), has_context=True)
        except ValueError as exc:
            raise ValueError("typed fallback endpoint is not allowed") from exc

    def invoke(self, route: ModelRoute, request: HandoffRequest) -> Mapping[str, Any]:
        if request.handoff_depth != 1 or route.route_id != request.route_id:
            raise TypedHttpFallbackError("typed fallback route or handoff depth is invalid")
        try:
            payload = sanitize_for_gateway({
                "contract": "ha-switchboard-fallback/v1",
                "handoff_id": request.handoff_id,
                "route_id": route.route_id,
                "request_id": request.request_id,
                "conversation_id": request.conversation_id,
                "utterance": request.utterance,
                "bounded_context": list(request.bounded_context),
                "relevant_facts": list(request.relevant_facts),
                "complexity": request.complexity.value,
                "allowed_response_kinds": [item.value for item in request.allowed_response_kinds],
                "handoff_depth": 1,
            })
        except SensitiveDataError as exc:
            raise TypedHttpFallbackError("typed fallback payload is not sanitized") from exc
        body = json.dumps(payload, separators=(",", ":")).encode()
        if len(body) > MAX_REQUEST_BYTES:
            raise TypedHttpFallbackError("typed fallback request is too large")
        key = self.api_key if self.api_key is not None else os.environ.get(self.api_key_env, "")
        if len(key) > MAX_API_KEY:
            raise TypedHttpFallbackError("typed fallback API key is too long")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request_obj = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            raw = _read_provider_response(request_obj, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=provider_http_error provider=typed_http status=%d", exc.code)
            raise TypedHttpFallbackUnavailable("typed fallback request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=provider_transport_error provider=typed_http error_type=%s", type(exc).__name__)
            raise TypedHttpFallbackUnavailable("typed fallback request failed") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise TypedHttpFallbackInvalidResponse("typed fallback response is too large")
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise TypedHttpFallbackInvalidResponse("typed fallback response is not JSON") from exc
        if not isinstance(decoded, Mapping):
            raise TypedHttpFallbackInvalidResponse("typed fallback response is not an object")
        try:
            clean = sanitize_for_gateway(decoded)
        except SensitiveDataError as exc:
            raise TypedHttpFallbackInvalidResponse("typed fallback response contains sensitive data") from exc
        if set(clean) - {"handoff_id", "route_id", "handoff_depth", "kind", "text", "proposals"}:
            raise TypedHttpFallbackInvalidResponse("typed fallback response contains unsupported fields")
        if clean.get("handoff_id") != request.handoff_id or clean.get("route_id", route.route_id) != route.route_id:
            raise TypedHttpFallbackInvalidResponse("typed fallback response identity mismatch")
        try:
            validate_response(clean, request, expected_route_id=route.route_id)
        except (HandoffError, TypeError, ValueError) as exc:
            raise TypedHttpFallbackInvalidResponse("typed fallback response violates the normalized contract") from exc
        return clean


# Short compatibility name for callers that model all fallback providers as
# adapters, while keeping the explicit contract name available for discovery.
TypedHttpFallback = TypedHttpFallbackAdapter
