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

from .protocol import HandoffRequest, HandoffResponse, ModelRoute, ResponseKind
from .redaction import (
    open_provider_url,
    require_secure_provider_endpoint,
    SensitiveDataError,
    sanitize_for_gateway,
)
from .route_policy import RouteRegistry, compatible_failovers


_LOG = logging.getLogger("ha_switchboard.handoff")


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
        key = (self.api_keys or {}).get(route.route_id) or (
            os.environ.get(env_name) if (env_name := (self.api_key_env or {}).get(route.route_id)) else ""
        )
        try:
            require_secure_provider_endpoint(endpoint, has_credentials=bool(key), has_context=True)
        except ValueError as exc:
            _LOG.warning("event=provider_rejected provider=route reason=endpoint_policy")
            raise HandoffError("provider endpoint is not allowed") from exc
        payload = {
            "handoff_id": request.handoff_id,
            "request_id": request.request_id,
            "conversation_id": request.conversation_id,
            "utterance": request.utterance,
            "bounded_context": list(request.bounded_context),
            "relevant_facts": list(request.relevant_facts),
            "complexity": request.complexity.value,
            "allowed_response_kinds": [item.value for item in request.allowed_response_kinds],
            "handoff_depth": request.handoff_depth,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request_obj = urllib.request.Request(
            endpoint.rstrip("/"),
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with open_provider_url(request_obj, timeout=max(0.2, min(self.timeout, 15))) as response:
                decoded = json.loads(response.read(128_000))
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=provider_http_error provider=route status=%d", exc.code)
            raise HandoffError("provider request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=provider_transport_error provider=route error_type=%s", type(exc).__name__)
            raise HandoffError("provider request failed") from exc
        if not isinstance(decoded, Mapping):
            _LOG.warning("event=provider_invalid_response provider=route reason=not_object")
            raise HandoffError("provider returned an invalid object")
        return decoded


def validate_response(payload: Mapping[str, Any], request: HandoffRequest) -> HandoffResponse:
    """Accept only bounded prose or one typed capability proposal."""

    if not isinstance(payload, Mapping):
        raise HandoffInvalidResponse("downstream response is not an object")
    if payload.get("handoff_id") != request.handoff_id:
        raise HandoffInvalidResponse("handoff identifier mismatch")
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
    if set(proposal) - {"capability_id", "parameter_refs", "reason"}:
        raise HandoffInvalidResponse("proposal contains unsupported fields")
    if not isinstance(proposal.get("capability_id"), str) or not proposal["capability_id"]:
        raise HandoffInvalidResponse("proposal must name an opaque capability")
    refs = proposal.get("parameter_refs", [])
    if not isinstance(refs, list) or len(refs) > 8 or any(not isinstance(item, Mapping) for item in refs):
        raise HandoffInvalidResponse("parameter references are invalid")
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
        attempts = [route, *compatible_failovers(self.registry, route, _privacy_from_request(request))]
        last_error: Exception | None = None
        for attempt in attempts[:3]:
            try:
                payload = self.adapter.invoke(attempt, request)
                return validate_response(payload, request)
            except HandoffInvalidResponse:
                raise
            except HandoffError as exc:
                last_error = exc
        raise HandoffError("all compatible handoff routes failed") from last_error


def _privacy_from_request(request: HandoffRequest):
    # The route has already been selected against privacy policy. Keeping this
    # helper conservative means operational failover can only use local routes
    # when the caller does not supply an explicit privacy extension.
    return request.privacy_mode
