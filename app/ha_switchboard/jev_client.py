"""Typed Jev client boundary with deterministic test doubles."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .protocol import Complexity, DecisionRequest, JevDecision, RouteKind
from .redaction import sanitize_for_gateway


class JevError(RuntimeError):
    code = "jev_unavailable"


class JevUnavailable(JevError):
    code = "jev_unavailable"


class JevInvalidResponse(JevError):
    code = "jev_invalid_response"


class JevClient(Protocol):
    def decide(self, request: DecisionRequest) -> JevDecision: ...


def build_questions(request: DecisionRequest) -> list[dict[str, Any]]:
    """Describe the independent typed questions Jev should answer."""

    return [
        {"name": "route", "kind": "choice", "options": [item.value for item in RouteKind]},
        {"name": "complexity", "kind": "choice", "options": ["simple", "medium", "complex", "reasoning"]},
        {
            "name": "capability",
            "kind": "choice",
            "options": [str(item.get("capability_id")) for item in request.candidates],
        },
        {"name": "ambiguity", "kind": "score", "range": [0, 1]},
        {"name": "risk", "kind": "choice", "options": ["read_only", "routine", "confirm", "blocked"]},
        {"name": "requires_confirmation", "kind": "noul"},
    ]


@dataclass(slots=True)
class StaticJevClient:
    """Fixture client used by tests and local development."""

    decision: JevDecision

    def decide(self, request: DecisionRequest) -> JevDecision:
        return self.decision


class HttpJevClient:
    """Minimal JSON client; credentials are read at call time only."""

    def __init__(self, endpoint: str, *, api_key: str | None = None, api_key_env: str = "JEV_API_KEY", timeout: float = 2.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.timeout = max(0.1, min(timeout, 10.0))

    def decide(self, request: DecisionRequest) -> JevDecision:
        if not self.endpoint:
            raise JevUnavailable("no Jev endpoint configured")
        payload = sanitize_for_gateway(
            {
                "utterance": request.utterance,
                "language": request.language,
                "candidates": list(request.candidates),
                "bounded_context": list(request.bounded_context),
                "sanitized_state": request.sanitized_state,
                "questions": build_questions(request),
                "profile_revision": request.profile_revision,
                "policy_revision": request.policy_revision,
            }
        )
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = self.api_key if self.api_key is not None else os.environ.get(self.api_key_env, "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request_obj = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request_obj, timeout=self.timeout) as response:
                raw = response.read(32_000)
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise JevUnavailable("Jev request failed") from exc
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, Mapping):
                raise TypeError("response is not an object")
            return JevDecision.from_dict(decoded.get("decision", decoded))
        except (ValueError, TypeError, KeyError) as exc:
            raise JevInvalidResponse("Jev response did not satisfy the typed contract") from exc


def client_from_environment() -> JevClient:
    endpoint = os.environ.get("JEV_ENDPOINT", "").strip()
    return HttpJevClient(endpoint) if endpoint else StaticJevClient(
        JevDecision(route=RouteKind.REFUSE, complexity=Complexity.SIMPLE, reason="jev_not_configured")
    )
