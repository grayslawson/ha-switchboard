"""Typed Jev client boundary with deterministic test doubles."""

from __future__ import annotations

import json
import logging
import time
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
import math
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from .protocol import (
    Complexity,
    DecisionRequest,
    JevDecision,
    RiskClass,
    RouteKind,
    normalize_typed_parameters,
    parameter_questions,
)
from .http_security import RetryPolicy
from .redaction import (
    endpoint_is_hosted,
    open_provider_url,
    require_secure_provider_endpoint,
    sanitize_for_gateway,
)


_LOG = logging.getLogger("ha_switchboard.jev")
DEFAULT_TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_TYPESAFE_MODEL = "jev-1.13.0"
MAX_JEV_REQUEST_BYTES = 64_000
MAX_JEV_RESPONSE_BYTES = 32_000
MAX_PROVIDER_API_KEY = 512
MAX_PROVIDER_ENDPOINT = 2_048
_RETRY_POLICY = RetryPolicy(attempts=2, base_delay=0.25, max_delay=2.0)
_RETRYABLE_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})
DEFAULT_OPENROUTER_DECISIONS_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_OPENROUTER_DECISIONS_MODEL = "typesafe/jev-1.13"


class JevError(RuntimeError):
    code = "jev_unavailable"


class JevUnavailable(JevError):
    code = "jev_unavailable"


class JevInvalidResponse(JevError):
    code = "jev_invalid_response"


class JevClient(Protocol):
    def decide(self, request: DecisionRequest) -> JevDecision: ...


def _read_provider_response(request_obj: urllib.request.Request, *, timeout: float) -> bytes:
    last_error: Exception | None = None
    for attempt in range(_RETRY_POLICY.attempts + 1):
        try:
            with open_provider_url(request_obj, timeout=timeout) as response:
                return response.read(MAX_JEV_RESPONSE_BYTES + 1)
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


def build_questions(request: DecisionRequest) -> list[dict[str, Any]]:
    """Describe gray-area questions for Jev, never a universal HA intent path.

    Native Home Assistant handling and deterministic Core-local answers must be
    attempted before an adapter is invoked.  These questions only describe a
    bounded advisory decision; Core remains the policy and execution owner.
    """

    questions = [
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
    typed = parameter_questions(request.candidates)
    if typed:
        questions.append({"name": "parameters", "kind": "typed_object", "questions": typed})
    return questions


@dataclass(slots=True)
class StaticJevClient:
    """Fixture client used by tests and local development."""

    decision: JevDecision

    def decide(self, request: DecisionRequest) -> JevDecision:
        return self.decision


class HttpJevClient:
    """Minimal JSON client; credentials are read at call time only."""

    provider_name = "compatible"

    def __init__(self, endpoint: str, *, api_key: str | None = None, api_key_env: str = "JEV_API_KEY", timeout: float = 2.0) -> None:
        if not isinstance(endpoint, str):
            raise ValueError("Jev endpoint must be text")
        self.endpoint = endpoint.rstrip("/")
        if len(self.endpoint) > MAX_PROVIDER_ENDPOINT:
            raise ValueError("Jev endpoint is too long")
        if api_key is not None and len(api_key) > MAX_PROVIDER_API_KEY:
            raise ValueError("Jev API key is too long")
        if self.endpoint:
            parsed = urlsplit(self.endpoint)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Jev endpoint must not contain credentials or query data")
            require_secure_provider_endpoint(self.endpoint, has_credentials=bool(api_key), has_context=True)
        self.api_key = api_key
        self.api_key_env = api_key_env
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout):
            raise ValueError("Jev timeout is invalid")
        if not 0.2 <= timeout <= 15.0:
            raise ValueError("Jev timeout is outside its bound")
        self.timeout = float(timeout)

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
        if len(body) > MAX_JEV_REQUEST_BYTES:
            raise JevInvalidResponse("Jev request is too large")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = self.api_key if self.api_key is not None else os.environ.get(self.api_key_env, "")
        if len(api_key) > MAX_PROVIDER_API_KEY:
            raise JevUnavailable("Jev API key is too long")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request_obj = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            raw = _read_provider_response(request_obj, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=jev_http_error provider=generic status=%d", exc.code)
            raise JevUnavailable("Jev request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=jev_transport_error provider=generic error_type=%s", type(exc).__name__)
            raise JevUnavailable("Jev request failed") from exc
        if len(raw) > MAX_JEV_RESPONSE_BYTES:
            raise JevInvalidResponse("Jev response is too large")
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, Mapping):
                raise TypeError("response is not an object")
            decision_payload = decoded.get("decision", decoded)
            if not isinstance(decision_payload, Mapping):
                raise TypeError("decision is not an object")
            allowed_fields = {
                "route", "complexity", "capability_id", "confidence", "ambiguity",
                "risk", "requires_confirmation", "reason", "parameters",
            }
            if set(decision_payload) - allowed_fields:
                raise ValueError("decision contains unknown fields")
            if "parameters" in decision_payload and not isinstance(decision_payload["parameters"], Mapping):
                raise ValueError("parameters must be an object")
            decision = JevDecision.from_dict(sanitize_for_gateway(decision_payload))
            if decision.parameters:
                capability = next(
                    (
                        item for item in request.candidates
                        if isinstance(item, Mapping) and item.get("capability_id") == decision.capability_id
                    ),
                    None,
                )
                if capability is None:
                    raise ValueError("parameters require a listed capability")
                decision = JevDecision(
                    route=decision.route,
                    complexity=decision.complexity,
                    capability_id=decision.capability_id,
                    confidence=decision.confidence,
                    ambiguity=decision.ambiguity,
                    risk=decision.risk,
                    requires_confirmation=decision.requires_confirmation,
                    reason=decision.reason,
                    parameters=normalize_typed_parameters(decision.parameters, capability),
                )
            return decision
        except (ValueError, TypeError, KeyError) as exc:
            raise JevInvalidResponse("Jev response did not satisfy the typed contract") from exc


class TypeSafeJevClient(HttpJevClient):
    """Direct TypeSafe System One adapter using only documented primitives."""

    provider_name = "typesafe"

    def __init__(
        self,
        endpoint: str = DEFAULT_TYPESAFE_ENDPOINT,
        *,
        model: str = DEFAULT_TYPESAFE_MODEL,
        **kwargs: Any,
    ) -> None:
        super().__init__(normalize_typesafe_endpoint(endpoint), **kwargs)
        if not model or len(model) > 128:
            raise ValueError("TypeSafe model is invalid")
        self.model = model

    def decide(self, request: DecisionRequest) -> JevDecision:
        if not self.endpoint:
            raise JevUnavailable("no TypeSafe endpoint configured")
        parameter_question_ids = _typesafe_parameter_question_ids(request)
        questions = _typesafe_questions(request, parameter_question_ids)
        payload = sanitize_for_gateway(
            {
                "model": self.model,
                "state": {
                    "utterance": request.utterance,
                    "language": request.language,
                    "candidates": list(request.candidates),
                    "bounded_context": list(request.bounded_context),
                    "sanitized_state": request.sanitized_state,
                    "profile_revision": request.profile_revision,
                    "policy_revision": request.policy_revision,
                },
                "questions": questions,
            }
        )
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_JEV_REQUEST_BYTES:
            raise JevInvalidResponse("TypeSafe request is too large")
        key = self.api_key if self.api_key is not None else os.environ.get(self.api_key_env, "")
        if len(key) > MAX_PROVIDER_API_KEY:
            raise JevUnavailable("TypeSafe API key is too long")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            raw = _read_provider_response(
                urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST"),
                timeout=self.timeout,
            )
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=jev_http_error provider=typesafe status=%d", exc.code)
            raise JevUnavailable("TypeSafe request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=jev_transport_error provider=typesafe error_type=%s", type(exc).__name__)
            raise JevUnavailable("TypeSafe request failed") from exc
        if len(raw) > MAX_JEV_RESPONSE_BYTES:
            raise JevInvalidResponse("TypeSafe response is too large")
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, Mapping):
                raise TypeError("TypeSafe response is not an object")
            answers = decoded.get("answers")
            if not isinstance(answers, Mapping):
                raise TypeError("TypeSafe response is not an answers object")
            if set(decoded) - {"answers", "model", "provider", "usage"}:
                raise ValueError("TypeSafe response contains unknown fields")
            expected = set(questions)
            if set(answers) != expected:
                raise ValueError("TypeSafe response answers do not match the request")
            route, route_confidence = _typesafe_choice(answers["route"], {item.value for item in RouteKind})
            complexity, _ = _typesafe_choice(answers["complexity"], {item.value for item in Complexity})
            capability, capability_confidence = _typesafe_choice(
                answers["capability"], _typesafe_capability_options(request)
            )
            risk, _ = _typesafe_choice(answers["risk"], {item.value for item in RiskClass})
            ambiguity = _typesafe_score(answers["ambiguity"], maximum=2.0) / 2.0
            confirmation = _typesafe_noul(answers["requires_confirmation"])
            if capability == "none":
                capability_id = None
            else:
                capability_id = capability
            chosen = next(
                (
                    (index, item)
                    for index, item in enumerate(request.candidates)
                    if isinstance(item, Mapping) and item.get("capability_id") == capability_id
                ),
                None,
            )
            parameters: dict[str, Any] = {}
            if chosen is not None:
                index, candidate = chosen
                schema = candidate.get("parameter_schema") or {}
                if isinstance(schema, Mapping) and schema.get("properties"):
                    ids = parameter_question_ids.get(index)
                    if not ids:
                        return JevDecision(
                            route=RouteKind.CLARIFY,
                            complexity=Complexity(complexity),
                            ambiguity=1.0,
                            reason="parameter_extraction_unavailable",
                        )
                    extracted: dict[str, Any] = {}
                    for name, (question_id, kind, values) in ids.items():
                        answer = answers[question_id]
                        if kind == "choice":
                            extracted[name] = _typesafe_choice(answer, set(values))[0]
                        else:
                            extracted[name] = _typesafe_score(answer, maximum=float(values[1]))
                            if extracted[name] < float(values[0]):
                                raise ValueError("numeric parameter is below its declared range")
                    parameters = normalize_typed_parameters(extracted, candidate)
            return JevDecision(
                route=RouteKind(route),
                complexity=Complexity(complexity),
                capability_id=capability_id,
                confidence=min(route_confidence, capability_confidence),
                ambiguity=ambiguity,
                risk=RiskClass(risk),
                requires_confirmation=confirmation >= 0.5,
                reason="typesafe_system_one",
                parameters=parameters,
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise JevInvalidResponse("TypeSafe response did not satisfy the typed contract") from exc


def normalize_typesafe_endpoint(value: str) -> str:
    """Normalize a TypeSafe base URL only to its documented System One path."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("TypeSafe endpoint is required")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("TypeSafe endpoint must be an absolute HTTP(S) URL without userinfo")
    if parsed.fragment:
        raise ValueError("TypeSafe endpoint must not contain a fragment")
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/systemone"):
        normalized = path
    elif path.endswith("/v1") or not path:
        normalized = f"{path}/systemone" if path else "/v1/systemone"
    else:
        raise ValueError("TypeSafe endpoint must use the documented /v1/systemone path")
    return parsed._replace(path=normalized).geturl()


def _typesafe_capability_options(request: DecisionRequest) -> set[str]:
    return {
        str(item.get("capability_id"))
        for item in request.candidates
        if isinstance(item, Mapping) and isinstance(item.get("capability_id"), str)
    } | {"none"}


def _typesafe_parameter_question_ids(
    request: DecisionRequest,
) -> dict[int, dict[str, tuple[str, str, Any]]]:
    """Return bounded question metadata for provider-supported parameters.

    System One supports both choice and score answers. Enumerated strings use
    choice; bounded numeric values use score. Unsupported schemas fail closed.
    """

    result: dict[int, dict[str, tuple[str, str, Any]]] = {}
    for index, candidate in enumerate(request.candidates):
        if not isinstance(candidate, Mapping):
            continue
        schema = candidate.get("parameter_schema")
        if not isinstance(schema, Mapping):
            continue
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
            continue
        if len(required) > 8 or len(set(required)) != len(required):
            continue
        extracted: dict[str, tuple[str, str, Any]] = {}
        supported = True
        for ordinal, name in enumerate(required):
            spec = properties.get(name)
            enum = spec.get("enum") if isinstance(spec, Mapping) else None
            if not isinstance(name, str) or not isinstance(spec, Mapping):
                supported = False
                break
            if spec.get("type") == "string" and isinstance(enum, (list, tuple)) and enum and all(
                isinstance(value, str) and value for value in enum
            ):
                extracted[name] = (f"parameter_{index}_{ordinal}", "choice", list(enum))
            elif spec.get("type") == "number":
                minimum, maximum = spec.get("minimum"), spec.get("maximum")
                if (
                    not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
                    or not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
                    or not math.isfinite(minimum) or not math.isfinite(maximum)
                    or minimum > maximum
                ):
                    supported = False
                    break
                extracted[name] = (f"parameter_{index}_{ordinal}", "score", (float(minimum), float(maximum)))
            else:
                supported = False
                break
        if supported:
            result[index] = extracted
    return result


def _typesafe_questions(
    request: DecisionRequest,
    parameter_question_ids: Mapping[int, Mapping[str, tuple[str, str, Any]]],
) -> dict[str, dict[str, Any]]:
    candidates = {
        str(item.get("capability_id")): str(item.get("display_name") or item.get("capability_id"))[:256]
        for item in request.candidates
        if isinstance(item, Mapping) and isinstance(item.get("capability_id"), str)
    }
    candidates["none"] = "No listed capability clearly matches the request."
    questions: dict[str, dict[str, Any]] = {
        "route": {
            "type": "choice",
            "instructions": "Which bounded outcome is appropriate for this Home Assistant request?",
            "criteria": {item.value: item.value.replace("_", " ") for item in RouteKind},
        },
        "complexity": {
            "type": "choice",
            "instructions": "How complex is the request?",
            "criteria": {item.value: item.value for item in Complexity},
        },
        "capability": {
            "type": "choice",
            "instructions": "Choose exactly one listed opaque capability, or none.",
            "criteria": candidates,
        },
        "ambiguity": {
            "type": "score",
            "instructions": "How ambiguous is the target or requested operation?",
            "criteria": ["clear", "somewhat ambiguous", "highly ambiguous"],
        },
        "risk": {
            "type": "choice",
            "instructions": "Which bounded risk class applies?",
            "criteria": {item.value: item.value.replace("_", " ") for item in RiskClass},
        },
        "requires_confirmation": {
            "type": "noul",
            "instructions": "Does this request require confirmation before any action?",
        },
    }
    for index, fields in parameter_question_ids.items():
        for name, (question_id, kind, values) in fields.items():
            if kind == "choice":
                questions[question_id] = {
                    "type": "choice",
                    "instructions": f"Which value is requested for parameter {name} of listed capability {index}?",
                    "criteria": {value: value for value in values},
                }
            else:
                questions[question_id] = {
                    "type": "score",
                    "instructions": f"What numeric value is requested for parameter {name} of listed capability {index}?",
                    "criteria": [f"bounded from {values[0]} to {values[1]}"],
                    "range": list(values),
                }
    return questions


def _typesafe_choice(answer: Any, allowed: set[str]) -> tuple[str, float]:
    if not isinstance(answer, Mapping) or answer.get("type") != "choice":
        raise ValueError("TypeSafe choice answer is invalid")
    if set(answer) - {"type", "choice", "probabilities", "confidence"}:
        raise ValueError("TypeSafe choice answer contains unknown fields")
    choice = answer.get("choice")
    confidence = answer.get("confidence")
    probabilities = answer.get("probabilities")
    if (
        not isinstance(choice, str)
        or choice not in allowed
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
        or not isinstance(probabilities, Mapping)
        or any(
            not isinstance(key, str)
            or not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for key, value in probabilities.items()
        )
    ):
        raise ValueError("TypeSafe choice answer is not bounded")
    return choice, float(confidence)


def _typesafe_score(answer: Any, *, maximum: float) -> float:
    if not isinstance(answer, Mapping) or answer.get("type") != "score":
        raise ValueError("TypeSafe score answer is invalid")
    if set(answer) - {"type", "score", "legend", "probabilities", "confidence"}:
        raise ValueError("TypeSafe score answer contains unknown fields")
    score = answer.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= maximum:
        raise ValueError("TypeSafe score answer is not bounded")
    return float(score)


def _typesafe_noul(answer: Any) -> float:
    if not isinstance(answer, Mapping) or answer.get("type") != "noul":
        raise ValueError("TypeSafe noul answer is invalid")
    if set(answer) - {"type", "noul", "probabilities", "confidence"}:
        raise ValueError("TypeSafe noul answer contains unknown fields")
    noul = answer.get("noul")
    if not isinstance(noul, (int, float)) or isinstance(noul, bool) or not math.isfinite(noul) or not 0 <= noul <= 1:
        raise ValueError("TypeSafe noul answer is not bounded")
    return float(noul)


class OpenRouterDecisionsClient(HttpJevClient):
    """Translate OpenRouter's typed Decisions answers into a bounded proposal.

    Jev cannot emit arbitrary service JSON or free-form numeric parameters.
    Parameterized capabilities therefore remain fail-closed until a separate
    extractor and validation path is available.
    """

    provider_name = "openrouter"

    def __init__(self, endpoint: str, *, model: str = DEFAULT_OPENROUTER_DECISIONS_MODEL, **kwargs: Any) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname != "openrouter.ai"
            or parsed.path.rstrip("/") != "/api/alpha/decisions"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OpenRouter Jev must use the documented Decisions endpoint")
        super().__init__(endpoint, **kwargs)
        if not model or len(model) > 128:
            raise ValueError("OpenRouter Decisions model is invalid")
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
        if len(body) > MAX_JEV_REQUEST_BYTES:
            raise JevInvalidResponse("OpenRouter Decisions request is too large")
        key = self.api_key if self.api_key is not None else os.environ.get(self.api_key_env, "")
        if len(key) > MAX_PROVIDER_API_KEY:
            raise JevUnavailable("OpenRouter API key is too long")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            raw = _read_provider_response(
                urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST"),
                timeout=self.timeout,
            )
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=jev_http_error provider=openrouter status=%d", exc.code)
            raise JevUnavailable("OpenRouter Decisions request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=jev_transport_error provider=openrouter error_type=%s", type(exc).__name__)
            raise JevUnavailable("OpenRouter Decisions request failed") from exc
        if len(raw) > MAX_JEV_RESPONSE_BYTES:
            raise JevInvalidResponse("OpenRouter Decisions response is too large")
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise JevInvalidResponse("OpenRouter Decisions response is not JSON") from exc
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
        if not isinstance(schema, Mapping) or schema.get("required") or schema.get("properties"):
            return JevDecision(route=RouteKind.CLARIFY, complexity=Complexity.SIMPLE, reason="parameter_extraction_unavailable")
        route_confidence = _choice_probability(route_answer)
        capability_confidence = _choice_probability(capability_answer)
        confidence = min(route_confidence, capability_confidence)
        ambiguity = max(
            1.0 - confidence,
            _highest_competing_probability(route_answer),
            _highest_competing_probability(capability_answer),
        )
        try:
            risk = RiskClass(str(chosen.get("risk_class", "routine")))
        except ValueError as exc:
            raise JevInvalidResponse("OpenRouter capability risk is invalid") from exc
        return JevDecision(
            route=RouteKind.ROUTINE_CONTROL,
            complexity=Complexity.SIMPLE,
            capability_id=capability_id,
            confidence=confidence,
            ambiguity=ambiguity,
            risk=risk,
            requires_confirmation=risk in {RiskClass.CONFIRM, RiskClass.BLOCKED},
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
    provider = os.environ.get("JEV_PROVIDER", "").strip().lower()
    endpoint = os.environ.get("JEV_ENDPOINT", "").strip()
    base_url = os.environ.get("JEV_BASE_URL", "").strip()
    api_key = os.environ.get("JEV_API_KEY") or None
    model = os.environ.get("JEV_MODEL", "").strip()
    if provider in {"", "disabled", "none"} and (endpoint or base_url):
        parsed = urlsplit(endpoint or base_url)
        provider = (
            "openrouter"
            if parsed.hostname == "openrouter.ai" and parsed.path.rstrip("/") == "/api/alpha/decisions"
            else "compatible"
        )
    if provider in {"", "disabled", "none"} and not endpoint and not base_url:
        return StaticJevClient(
            JevDecision(route=RouteKind.REFUSE, complexity=Complexity.SIMPLE, reason="jev_not_configured")
        )
    if provider in {"disabled", "none"}:
        return StaticJevClient(
            JevDecision(route=RouteKind.REFUSE, complexity=Complexity.SIMPLE, reason="jev_not_configured")
        )
    if provider == "typesafe":
        return TypeSafeJevClient(endpoint or base_url or DEFAULT_TYPESAFE_ENDPOINT, api_key=api_key, model=model or DEFAULT_TYPESAFE_MODEL)
    if provider == "openrouter":
        return OpenRouterDecisionsClient(endpoint or DEFAULT_OPENROUTER_DECISIONS_ENDPOINT, api_key=api_key, model=model or DEFAULT_OPENROUTER_DECISIONS_MODEL)
    if provider == "compatible":
        if not endpoint and not base_url:
            raise ValueError("compatible Jev endpoint is required")
        return HttpJevClient(endpoint or base_url, api_key=api_key)
    if provider:
        raise ValueError("unsupported Jev provider")
    if endpoint:
        parsed = urlsplit(endpoint)
        if parsed.hostname == "openrouter.ai" and parsed.path.rstrip("/") == "/api/alpha/decisions":
            return OpenRouterDecisionsClient(endpoint, api_key=api_key, model=model or DEFAULT_OPENROUTER_DECISIONS_MODEL)
        return HttpJevClient(endpoint, api_key=api_key)
    return TypeSafeJevClient(base_url, api_key=api_key, model=model or DEFAULT_TYPESAFE_MODEL)
