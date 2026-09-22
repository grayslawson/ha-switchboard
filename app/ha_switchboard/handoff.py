"""Bounded traditional-LLM handoff and response validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from .protocol import HandoffRequest, HandoffResponse, ModelRoute, ResponseKind
from .redaction import (
    open_provider_url,
    require_secure_provider_endpoint,
    SensitiveDataError,
    sanitize_for_gateway,
)
from .route_policy import RouteRegistry, ordered_routes


_LOG = logging.getLogger("ha_switchboard.handoff")
MAX_HTTP_ROUTE_REQUEST_BYTES = 32_000
MAX_HTTP_ROUTE_RESPONSE_BYTES = 32_000
MAX_HTTP_ROUTE_ENDPOINT = 2_048


class HandoffError(RuntimeError):
    code = "handoff_unavailable"


class HandoffInvalidResponse(HandoffError):
    code = "handoff_invalid_response"


class RouteAdapter(Protocol):
    def invoke(self, route: ModelRoute, request: HandoffRequest) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class StaticRouteAdapter:
    responses: Mapping[str, Mapping[str, Any]]

    def invoke(self, route: ModelRoute, request: HandoffRequest) -> Mapping[str, Any]:
        response = self.responses.get(route.route_id)
        if response is None:
            raise HandoffError(f"route {route.route_id} unavailable")
        return response


@dataclass(slots=True)
class HttpRouteAdapter:
    """OpenAI-compatible/local/HA-agent transport without provider tool access."""

    endpoints: Mapping[str, str]
    api_key_env: Mapping[str, str] | None = None
    api_keys: Mapping[str, str] | None = None
    timeout: float = 5.0

    def invoke(self, route: ModelRoute, request: HandoffRequest) -> Mapping[str, Any]:
        endpoint = self.endpoints.get(route.route_id, "")
        if not endpoint:
            raise HandoffError(f"route {route.route_id} has no endpoint")
        if not isinstance(endpoint, str) or len(endpoint) > MAX_HTTP_ROUTE_ENDPOINT:
            raise HandoffError("provider endpoint is invalid")
        try:
            parsed_endpoint = urlsplit(endpoint.strip())
            endpoint_scheme = parsed_endpoint.scheme.lower()
            endpoint_host = parsed_endpoint.hostname
        except ValueError:
            raise HandoffError("provider endpoint is invalid") from None
        if (
            endpoint_scheme not in {"http", "https"}
            or not endpoint_host
            or parsed_endpoint.username
            or parsed_endpoint.password
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise HandoffError("provider endpoint is invalid")
        key = (self.api_keys or {}).get(route.route_id) or (
            os.environ.get(env_name) if (env_name := (self.api_key_env or {}).get(route.route_id)) else ""
        )
        try:
            require_secure_provider_endpoint(endpoint, has_credentials=bool(key), has_context=True)
        except ValueError as exc:
            _LOG.warning("event=provider_rejected provider=route reason=endpoint_policy")
            raise HandoffError("provider endpoint is not allowed") from exc
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
            raise HandoffError("provider payload is not sanitized") from exc
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_HTTP_ROUTE_REQUEST_BYTES:
            raise HandoffError("provider request is too large")
        request_obj = urllib.request.Request(
            endpoint.strip().rstrip("/"),
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with open_provider_url(request_obj, timeout=max(0.2, min(self.timeout, 15))) as response:
                raw = response.read(MAX_HTTP_ROUTE_RESPONSE_BYTES + 1)
                if len(raw) > MAX_HTTP_ROUTE_RESPONSE_BYTES:
                    raise HandoffInvalidResponse("provider response is too large")
                decoded = json.loads(raw)
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=provider_http_error provider=route status=%d", exc.code)
            raise HandoffError("provider request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=provider_transport_error provider=route error_type=%s", type(exc).__name__)
            raise HandoffError("provider request failed") from exc
        except (TypeError, ValueError) as exc:
            _LOG.warning("event=provider_invalid_response provider=route reason=malformed")
            raise HandoffInvalidResponse("provider returned malformed JSON") from exc
        if not isinstance(decoded, Mapping):
            _LOG.warning("event=provider_invalid_response provider=route reason=not_object")
            raise HandoffError("provider returned an invalid object")
        return decoded


def validate_response(
    payload: Mapping[str, Any],
    request: HandoffRequest,
    *,
    expected_route_id: str | None = None,
) -> HandoffResponse:
    """Accept only bounded prose or one typed capability proposal."""

    if not isinstance(payload, Mapping):
        raise HandoffInvalidResponse("downstream response is not an object")
    if payload.get("handoff_id") != request.handoff_id:
        raise HandoffInvalidResponse("handoff identifier mismatch")
    route_id = expected_route_id or request.route_id
    if payload.get("route_id", route_id) != route_id:
        raise HandoffInvalidResponse("route identity mismatch")
    if payload.get("handoff_depth", 1) != 1:
        raise HandoffInvalidResponse("invalid handoff depth")
    if "service" in payload or "service_data" in payload or "tool_calls" in payload:
        raise HandoffInvalidResponse("raw provider tool calls are not accepted")
    kind = payload.get("kind")
    try:
        response_kind = ResponseKind(kind)
    except ValueError as exc:
        raise HandoffInvalidResponse("unsupported response kind") from exc
    if response_kind not in request.allowed_response_kinds:
        raise HandoffInvalidResponse("response kind is outside policy")
    try:
        clean = sanitize_for_gateway(payload)
    except SensitiveDataError as exc:
        raise HandoffInvalidResponse("response contains sensitive data") from exc
    if response_kind is ResponseKind.PROSE_RESPONSE:
        text = clean.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 4_000:
            raise HandoffInvalidResponse("prose response is empty or oversized")
        if "proposals" in clean:
            raise HandoffInvalidResponse("mixed prose and proposal response")
        return HandoffResponse(kind=response_kind, handoff_id=request.handoff_id, text=text)
    proposals = clean.get("proposals")
    if not isinstance(proposals, list) or len(proposals) != 1:
        raise HandoffInvalidResponse("exactly one typed proposal is required")
    proposal = proposals[0]
    if not isinstance(proposal, Mapping):
        raise HandoffInvalidResponse("proposal is not an object")
    if set(proposal) - {"capability_id", "parameter_refs", "parameters", "reason"}:
        raise HandoffInvalidResponse("proposal contains unsupported fields")
    if not isinstance(proposal.get("capability_id"), str) or not proposal["capability_id"]:
        raise HandoffInvalidResponse("proposal must name an opaque capability")
    refs = proposal.get("parameter_refs", [])
    if not isinstance(refs, list) or len(refs) > 8 or any(not isinstance(item, Mapping) for item in refs):
        raise HandoffInvalidResponse("parameter references are invalid")
    parameters = proposal.get("parameters", {})
    if not isinstance(parameters, Mapping) or len(parameters) > 8:
        raise HandoffInvalidResponse("typed parameters are invalid")
    if any(not isinstance(key, str) or not key or len(key) > 64 for key in parameters):
        raise HandoffInvalidResponse("typed parameter names are invalid")
    if any(not isinstance(value, (str, int, float, bool)) and value is not None for value in parameters.values()):
        raise HandoffInvalidResponse("typed parameter values are invalid")
    relevant_facts = request.relevant_facts if isinstance(request.relevant_facts, (list, tuple)) else ()
    candidate = next(
        (item for item in relevant_facts if isinstance(item, Mapping) and item.get("capability_id") == proposal["capability_id"]),
        None,
    )
    if candidate is not None:
        schema = candidate.get("parameter_schema", {})
        allowed = set(schema.get("properties", {})) if isinstance(schema, Mapping) else set()
        if set(parameters) - allowed:
            raise HandoffInvalidResponse("parameters are outside the capability schema")
    return HandoffResponse(
        kind=response_kind,
        handoff_id=request.handoff_id,
        proposals=(dict(proposal),),
    )


class HandoffBroker:
    def __init__(self, registry: RouteRegistry, adapter: RouteAdapter) -> None:
        self.registry = registry
        self.adapter = adapter

    def dispatch(self, request: HandoffRequest) -> HandoffResponse:
        if request.handoff_depth != 1:
            raise HandoffError("handoff depth must be exactly one")
        route = self.registry.get(request.route_id)
        if route is None:
            raise HandoffError("unknown route")
        attempts = ordered_routes(
            self.registry,
            route,
            complexity=request.complexity,
            privacy_mode=_privacy_from_request(request),
            required_response=request.allowed_response_kinds,
            max_latency_ms=120_000,
            max_cost=float("inf"),
        )
        last_error: Exception | None = None
        for attempt in attempts[:8]:
            try:
                payload = self.adapter.invoke(attempt, request)
                response = validate_response(payload, request, expected_route_id=attempt.route_id)
                self.registry.record_success(attempt.route_id)
                return response
            except HandoffInvalidResponse as exc:
                # A malformed provider response is provider health failure,
                # not a caller error. Continue through the explicit chain.
                self.registry.record_failure(attempt.route_id)
                last_error = exc
            except HandoffError as exc:
                self.registry.record_failure(attempt.route_id)
                last_error = exc
        if isinstance(last_error, HandoffInvalidResponse):
            raise last_error
        raise HandoffError("all compatible handoff routes failed") from last_error


def _privacy_from_request(request: HandoffRequest):
    # The route has already been selected against privacy policy. Keeping this
    # helper conservative means operational failover can only use local routes
    # when the caller does not supply an explicit privacy extension.
    return request.privacy_mode
