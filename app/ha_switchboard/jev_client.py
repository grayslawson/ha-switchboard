"""Typed Jev client boundary with deterministic test doubles."""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .protocol import Complexity, DecisionRequest, JevDecision, RiskClass, RouteKind
from .redaction import (
    endpoint_is_hosted,
    open_provider_url,
    require_secure_provider_endpoint,
    sanitize_for_gateway,
)


_LOG = logging.getLogger("ha_switchboard.jev")


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
        {"name": "requires_confirmation", "kind": "boolean"},
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
        if self.endpoint:
            require_secure_provider_endpoint(self.endpoint, has_credentials=bool(api_key), has_context=True)
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.timeout = max(0.1, min(timeout, 10.0))

    @property
    def hosted(self) -> bool:
        """Fail closed for public HTTP destinations in local-only mode."""

        return endpoint_is_hosted(self.endpoint)

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
            with open_provider_url(request_obj, timeout=self.timeout) as response:
                raw = response.read(32_000)
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=jev_http_error provider=generic status=%d", exc.code)
            raise JevUnavailable("Jev request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=jev_transport_error provider=generic error_type=%s", type(exc).__name__)
            raise JevUnavailable("Jev request failed") from exc
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, Mapping):
                raise TypeError("response is not an object")
            decision_payload = decoded.get("decision", decoded)
            if not isinstance(decision_payload, Mapping):
                raise TypeError("decision is not an object")
            return JevDecision.from_dict(sanitize_for_gateway(decision_payload))
        except (ValueError, TypeError, KeyError) as exc:
            raise JevInvalidResponse("Jev response did not satisfy the typed contract") from exc


class OpenRouterDecisionsClient(HttpJevClient):
    """Translate OpenRouter's typed Decisions answers into a bounded proposal.

    Jev cannot emit arbitrary service JSON or free-form numeric parameters.
    Parameterized capabilities therefore remain fail-closed until a separate
    extractor and validation path is available.
    """

    def __init__(self, endpoint: str, *, model: str = "typesafe/jev-1.13", **kwargs: Any) -> None:
        super().__init__(endpoint, **kwargs)
        self.model = model

    def decide(self, request: DecisionRequest) -> JevDecision:
        if not self.endpoint or not self.model:
            raise JevUnavailable("OpenRouter endpoint or model is not configured")
        candidates = [item for item in request.candidates if isinstance(item, Mapping)]
        allowed = {
            str(item.get("capability_id")): item
            for item in candidates
            if isinstance(item.get("capability_id"), str) and item.get("available", True)
        }
        criteria = {
            capability_id: {
                "name": str(item.get("display_name", ""))[:256],
                "domain": str(item.get("domain", ""))[:64],
                "operation": str(item.get("operation", ""))[:64],
                "area": str(item.get("area") or "")[:128],
            }
            for capability_id, item in allowed.items()
        }
        criteria["none"] = "No listed capability clearly matches the request."
        payload = sanitize_for_gateway(
            {
                "model": self.model,
                "state": {
                    "utterance": request.utterance,
                    "language": request.language,
                    "candidates": candidates,
                    "bounded_context": list(request.bounded_context),
                    "sanitized_state": request.sanitized_state,
                },
                "questions": {
                    "route": {
                        "type": "choice",
                        "instructions": "Choose routine_control only for a clear parameter-free action on exactly one listed capability. Choose clarify if the target or intent is ambiguous. Otherwise refuse.",
                        "criteria": {
                            "routine_control": "A clear parameter-free control command matches one listed capability.",
                            "clarify": "The target or operation needs clarification, or a value is missing.",
                            "refuse": "The request is unsupported, unsafe, or requires a value not represented by a capability.",
                        },
                    },
                    "capability": {
                        "type": "choice",
                        "instructions": "Choose exactly one listed capability matching both target and operation; choose none if uncertain.",
                        "criteria": criteria,
                    },
                },
            }
        )
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        key = self.api_key if self.api_key is not None else os.environ.get(self.api_key_env, "")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            with open_provider_url(
                urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST"),
                timeout=self.timeout,
            ) as response:
                decoded = json.loads(response.read(32_000))
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=jev_http_error provider=openrouter status=%d", exc.code)
            raise JevUnavailable("OpenRouter Decisions request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, ValueError) as exc:
            _LOG.warning("event=jev_transport_error provider=openrouter error_type=%s", type(exc).__name__)
            raise JevUnavailable("OpenRouter Decisions request failed") from exc
        if not isinstance(decoded, Mapping) or not isinstance(decoded.get("answers"), Mapping):
            raise JevInvalidResponse("OpenRouter Decisions response is missing answers")
        answers = decoded["answers"]
        route_answer = answers.get("route")
        capability_answer = answers.get("capability")
        if not isinstance(route_answer, Mapping) or route_answer.get("type") != "choice":
            raise JevInvalidResponse("OpenRouter route answer is invalid")
        route_choice = route_answer.get("choice")
        if route_choice not in {"routine_control", "clarify", "refuse"}:
            raise JevInvalidResponse("OpenRouter route is not allowed")
        if route_choice != "routine_control":
            return JevDecision(route=RouteKind(route_choice), complexity=Complexity.SIMPLE, reason="openrouter_decisions")
        if not isinstance(capability_answer, Mapping) or capability_answer.get("type") != "choice":
            raise JevInvalidResponse("OpenRouter capability answer is invalid")
        capability_id = capability_answer.get("choice")
        if capability_id not in allowed:
            return JevDecision(route=RouteKind.CLARIFY, complexity=Complexity.SIMPLE, reason="no_matching_capability")
        chosen = allowed[capability_id]
        schema = chosen.get("parameter_schema") or {}
        if not isinstance(schema, Mapping) or schema.get("required"):
            return JevDecision(route=RouteKind.CLARIFY, complexity=Complexity.SIMPLE, reason="parameter_extraction_unavailable")
        route_confidence = _choice_probability(route_answer)
        capability_confidence = _choice_probability(capability_answer)
        confidence = min(route_confidence, capability_confidence)
        ambiguity = max(
            1.0 - confidence,
            _highest_competing_probability(route_answer),
            _highest_competing_probability(capability_answer),
        )
        return JevDecision(
            route=RouteKind.ROUTINE_CONTROL,
            complexity=Complexity.SIMPLE,
            capability_id=capability_id,
            confidence=confidence,
            ambiguity=ambiguity,
            risk=RiskClass(str(chosen.get("risk_class", "routine"))),
            requires_confirmation=chosen.get("risk_class") in {"confirm", "blocked"},
            reason="openrouter_decisions",
        )


def _choice_probability(answer: Mapping[str, Any]) -> float:
    """Use calibrated choice probability; missing evidence is zero confidence."""

    probabilities = answer.get("probabilities")
    choice = answer.get("choice")
    if not isinstance(probabilities, Mapping):
        return 0.0
    value = probabilities.get(choice)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
        return 0.0
    return float(value)


def _highest_competing_probability(answer: Mapping[str, Any]) -> float:
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, Mapping):
        return 1.0
    competitors = [value for key, value in probabilities.items() if key != answer.get("choice")]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1 for value in competitors):
        return 1.0
    return float(max(competitors, default=0.0))


def client_from_environment() -> JevClient:
    endpoint = os.environ.get("JEV_ENDPOINT", "").strip()
    return HttpJevClient(endpoint) if endpoint else StaticJevClient(
        JevDecision(route=RouteKind.REFUSE, complexity=Complexity.SIMPLE, reason="jev_not_configured")
    )
