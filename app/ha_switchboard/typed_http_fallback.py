"""Strict HTTP adapter for the normalized fallback provider contract."""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .handoff import HandoffError
from .protocol import HandoffRequest, ModelRoute
from .redaction import SensitiveDataError, open_provider_url, require_secure_provider_endpoint, sanitize_for_gateway

_LOG = logging.getLogger("ha_switchboard.typed_http_fallback")
MAX_REQUEST_BYTES = 32_000
MAX_RESPONSE_BYTES = 32_000


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
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request_obj = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with open_provider_url(request_obj, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
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
            clean = sanitize_for_gateway(decoded, reject_references=False)
        except SensitiveDataError as exc:
            raise TypedHttpFallbackInvalidResponse("typed fallback response contains sensitive data") from exc
        if clean.get("handoff_id") != request.handoff_id or clean.get("route_id", route.route_id) != route.route_id:
            raise TypedHttpFallbackInvalidResponse("typed fallback response identity mismatch")
        return clean


# Short compatibility name for callers that model all fallback providers as
# adapters, while keeping the explicit contract name available for discovery.
TypedHttpFallback = TypedHttpFallbackAdapter
