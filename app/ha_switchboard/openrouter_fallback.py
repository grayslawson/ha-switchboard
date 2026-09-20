"""Bounded OpenAI-compatible chat-completions adapter for one-level handoff.

The adapter deliberately exposes no provider tools.  The model may select one
opaque capability (including a precomputed group capability) from the offered
choices, or return bounded prose.  Home Assistant execution and all final
policy checks remain outside this module.
"""

from __future__ import annotations

from collections import deque
import json
import logging
import os
import socket
import threading
import urllib.error
import urllib.request
from typing import Any, Mapping
from urllib.parse import urlsplit

from .handoff import HandoffError, HandoffInvalidResponse
from .protocol import HandoffRequest, ResponseKind
from .redaction import (
    SensitiveDataError,
    endpoint_is_hosted,
    open_provider_url,
    require_secure_provider_endpoint,
    sanitize_for_gateway,
)


DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
MAX_COMPLETION_TOKENS = 512
MAX_RESPONSE_BYTES = 32_000
MAX_CHOICES = 64
MAX_CHOICE_TEXT = 512
MAX_PROSE = 4_000
MAX_REQUEST_BYTES = 64_000
MAX_API_KEY = 512

_LOG = logging.getLogger("ha_switchboard.openai_compatible")


class OpenRouterFallbackError(HandoffError):
    """Base error for a bounded fallback request."""


class OpenRouterFallbackUnavailable(OpenRouterFallbackError):
    """The provider could not be reached."""


class OpenRouterFallbackInvalidResponse(HandoffInvalidResponse):
    """The provider response did not satisfy the typed fallback contract."""


class OpenAICompatibleFallbackAdapter:
    """Invoke one bounded OpenAI-compatible chat-completions handoff.

    ``invoke`` has the same shape as :class:`ha_switchboard.handoff.RouteAdapter`:
    it returns a handoff response mapping ready for ``validate_response``.
    ``request.relevant_facts`` must contain already-sanitized opaque choices.
    Each choice needs ``capability_id`` and may include ``display_name``,
    ``domain``, ``operation``, ``area``, or ``kind``.  A ``group_action`` is
    treated exactly like any other offered opaque capability.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        api_key_env: str = "FALLBACK_API_KEY",
        timeout: float = 8.0,
        max_tokens: int = 384,
    ) -> None:
        if base_url is not None:
            if endpoint != DEFAULT_ENDPOINT:
                raise ValueError("fallback endpoint and base_url are mutually exclusive")
            endpoint = base_url
        endpoint = normalize_chat_completions_endpoint(endpoint)
        if len(endpoint) > 2_048:
            raise ValueError("fallback endpoint is too long")
        if not model or len(model) > 128:
            raise ValueError("fallback model is invalid")
        if api_key is not None and len(api_key) > MAX_API_KEY:
            raise ValueError("fallback API key is too long")
        if not 0.2 <= timeout <= 15.0:
            raise ValueError("OpenRouter fallback timeout is outside its bound")
        if not 1 <= max_tokens <= MAX_COMPLETION_TOKENS:
            raise ValueError("OpenRouter fallback max_tokens is outside its bound")
        require_secure_provider_endpoint(
            endpoint,
            has_credentials=bool(api_key),
            has_context=True,
        )
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._seen_handoffs: deque[str] = deque(maxlen=256)
        self._seen_lock = threading.Lock()

    @property
    def hosted(self) -> bool:
        return endpoint_is_hosted(self.endpoint)

    def invoke(self, route: Any, request: HandoffRequest) -> Mapping[str, Any]:
        """Return one validated handoff response, without provider tool access."""

        if request.handoff_depth != 1:
            raise OpenRouterFallbackError("fallback handoff depth is not permitted")
        route_id = str(getattr(route, "route_id", "") or request.route_id)
        if not route_id:
            raise OpenRouterFallbackError("fallback route identity is missing")
        # A failover is a new provider attempt under the same bounded
        # handoff. Scope replay protection by route so a failed primary does
        # not poison the explicitly declared secondary route.
        seen_key = f"{request.handoff_id}:{route_id}"
        with self._seen_lock:
            if seen_key in self._seen_handoffs:
                raise OpenRouterFallbackError("fallback handoff was already attempted")
            self._seen_handoffs.append(seen_key)

        choices = self._choices(request)
        payload = self._request_payload(request, choices)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise OpenRouterFallbackInvalidResponse("fallback request is too large")
        key = self.api_key if self.api_key is not None else os.environ.get(self.api_key_env, "")
        if len(key) > MAX_API_KEY:
            raise OpenRouterFallbackError("fallback API key is too long")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            with open_provider_url(
                urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST"),
                timeout=self.timeout,
            ) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=provider_http_error provider=openai_compatible status=%d", exc.code)
            raise OpenRouterFallbackUnavailable("OpenAI-compatible fallback request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=provider_transport_error provider=openai_compatible error_type=%s", type(exc).__name__)
            raise OpenRouterFallbackUnavailable("OpenAI-compatible fallback request failed") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            _LOG.warning("event=provider_invalid_response provider=openai_compatible reason=response_too_large")
            raise OpenRouterFallbackInvalidResponse("OpenAI-compatible fallback response is too large")
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, Mapping):
                raise TypeError("completion response is not an object")
            choices_response = decoded["choices"]
            if not isinstance(choices_response, list) or not choices_response:
                raise TypeError("completion choices are invalid")
            first_choice = choices_response[0]
            if not isinstance(first_choice, Mapping):
                raise TypeError("completion choice is invalid")
            message = first_choice["message"]
            if not isinstance(message, Mapping) or "tool_calls" in message or "function_call" in message:
                raise TypeError("provider tool calls are not accepted")
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise TypeError("completion content is not text")
            stripped = content.strip()
            if stripped.startswith(("{", "[")):
                result = json.loads(stripped)
            else:
                result = stripped
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            _LOG.warning("event=provider_invalid_response provider=openai_compatible reason=malformed")
            raise OpenRouterFallbackInvalidResponse("OpenAI-compatible fallback response is malformed") from exc
        return self._response(request, result, choices)

    @staticmethod
    def _choices(request: HandoffRequest) -> dict[str, dict[str, Any]]:
        if len(request.relevant_facts) > MAX_CHOICES:
            raise OpenRouterFallbackInvalidResponse("fallback choices exceed the bound")
        result: dict[str, dict[str, Any]] = {}
        try:
            facts = sanitize_for_gateway(list(request.relevant_facts))
        except SensitiveDataError as exc:
            raise OpenRouterFallbackInvalidResponse("fallback choices are not sanitized") from exc
        for item in facts:
            if not isinstance(item, Mapping):
                raise OpenRouterFallbackInvalidResponse("fallback choice is not an object")
            capability_id = item.get("capability_id")
            if not isinstance(capability_id, str) or not capability_id or len(capability_id) > 128:
                raise OpenRouterFallbackInvalidResponse("fallback choice has no opaque capability")
            if capability_id in result:
                raise OpenRouterFallbackInvalidResponse("fallback choices are not unique")
            result[capability_id] = {
                "capability_id": capability_id,
                "name": str(item.get("display_name") or capability_id)[:MAX_CHOICE_TEXT],
                "kind": str(item.get("kind") or "capability")[:64],
                "domain": str(item.get("domain") or "")[:64],
                "operation": str(item.get("operation") or "")[:64],
                "area": str(item.get("area") or "")[:128],
            }
        return result

    def _request_payload(self, request: HandoffRequest, choices: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {"type": "string", "enum": ["prose_response", "tool_proposal"]},
                "choice": {"type": ["string", "null"], "enum": [*choices, None]},
                "text": {"type": "string", "maxLength": MAX_PROSE},
                "reason": {"type": "string", "maxLength": 512},
            },
            "required": ["kind", "choice", "text", "reason"],
        }
        safe = sanitize_for_gateway(
            {
                "utterance": request.utterance,
                "choices": list(choices.values()),
                "bounded_context": list(request.bounded_context),
            }
        )
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a bounded Home Assistant fallback. Select one offered choice only, "
                        "or return concise prose. Never invent IDs, call tools, emit service JSON, "
                        "or claim an action was executed. For unsupported or ambiguous requests use prose."
                    ),
                },
                {"role": "user", "content": json.dumps(safe, separators=(",", ":"))},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ha_switchboard_fallback", "strict": True, "schema": schema},
            },
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "stream": False,
        }

    @staticmethod
    def _response(
        request: HandoffRequest,
        result: Any,
        choices: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        if not isinstance(result, Mapping):
            if isinstance(result, str) and result.strip() and len(result) <= MAX_PROSE:
                return {"handoff_id": request.handoff_id, "kind": ResponseKind.PROSE_RESPONSE.value, "text": result.strip()}
            raise OpenRouterFallbackInvalidResponse("fallback result is not an object")
        if set(result) - {"kind", "choice", "text", "reason"}:
            raise OpenRouterFallbackInvalidResponse("fallback result contains unsupported fields")
        kind = result.get("kind")
        if kind == ResponseKind.PROSE_RESPONSE.value:
            text = result.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROSE:
                raise OpenRouterFallbackInvalidResponse("fallback prose is invalid")
            return {"handoff_id": request.handoff_id, "kind": kind, "text": text.strip()}
        if kind != ResponseKind.TOOL_PROPOSAL.value:
            raise OpenRouterFallbackInvalidResponse("fallback response kind is invalid")
        choice = result.get("choice")
        if not isinstance(choice, str) or choice not in choices:
            raise OpenRouterFallbackInvalidResponse("fallback selected an unoffered choice")
        reason = result.get("reason", "fallback selection")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
            raise OpenRouterFallbackInvalidResponse("fallback proposal reason is invalid")
        if result.get("text") not in (None, ""):
            raise OpenRouterFallbackInvalidResponse("fallback proposal contains prose")
        return {
            "handoff_id": request.handoff_id,
            "kind": kind,
            "proposals": [{"capability_id": choice, "parameter_refs": [], "reason": reason.strip()}],
        }


def normalize_chat_completions_endpoint(value: str) -> str:
    """Accept either a compatible base URL or its complete chat path."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("fallback endpoint is required")
    endpoint = value.strip()
    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("fallback endpoint must be an absolute HTTP(S) URL without userinfo")
    if parsed.fragment:
        raise ValueError("fallback endpoint must not contain a fragment")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions" if path else "/chat/completions"
    return parsed._replace(path=path).geturl()


# Compatibility names retained for callers and existing configurations.
OpenRouterFallbackAdapter = OpenAICompatibleFallbackAdapter
