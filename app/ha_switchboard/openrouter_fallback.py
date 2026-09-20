"""Bounded OpenRouter chat-completions adapter for one-level handoff.

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
from .redaction import SensitiveDataError, open_provider_url, sanitize_for_gateway


DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
MAX_COMPLETION_TOKENS = 512
MAX_RESPONSE_BYTES = 32_000
MAX_CHOICES = 64
MAX_CHOICE_TEXT = 512
MAX_PROSE = 4_000

_LOG = logging.getLogger("ha_switchboard.openrouter")


class OpenRouterFallbackError(HandoffError):
    """Base error for a bounded fallback request."""


class OpenRouterFallbackUnavailable(OpenRouterFallbackError):
    """The provider could not be reached."""


class OpenRouterFallbackInvalidResponse(HandoffInvalidResponse):
    """The provider response did not satisfy the typed fallback contract."""


class OpenRouterFallbackAdapter:
    """Invoke one bounded OpenRouter chat-completions handoff.

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
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        api_key_env: str = "JEV_API_KEY",
        timeout: float = 8.0,
        max_tokens: int = 384,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("OpenRouter fallback endpoint must use HTTPS")
        if not model or len(model) > 128:
            raise ValueError("OpenRouter fallback model is invalid")
        if not 0.2 <= timeout <= 15.0:
            raise ValueError("OpenRouter fallback timeout is outside its bound")
        if not 1 <= max_tokens <= MAX_COMPLETION_TOKENS:
            raise ValueError("OpenRouter fallback max_tokens is outside its bound")
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._seen_handoffs: deque[str] = deque(maxlen=256)
        self._seen_lock = threading.Lock()

    def invoke(self, route: Any, request: HandoffRequest) -> Mapping[str, Any]:
        """Return one validated handoff response, without provider tool access."""

        del route  # Route selection and privacy policy belong to the parent.
        if request.handoff_depth != 1:
            raise OpenRouterFallbackError("fallback handoff depth is not permitted")
        with self._seen_lock:
            if request.handoff_id in self._seen_handoffs:
                raise OpenRouterFallbackError("fallback handoff was already attempted")
            self._seen_handoffs.append(request.handoff_id)

        choices = self._choices(request)
        payload = self._request_payload(request, choices)
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
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            _LOG.warning("event=provider_http_error provider=openrouter status=%d", exc.code)
            raise OpenRouterFallbackUnavailable("OpenRouter fallback request failed") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            _LOG.warning("event=provider_transport_error provider=openrouter error_type=%s", type(exc).__name__)
            raise OpenRouterFallbackUnavailable("OpenRouter fallback request failed") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            _LOG.warning("event=provider_invalid_response provider=openrouter reason=response_too_large")
            raise OpenRouterFallbackInvalidResponse("OpenRouter fallback response is too large")
        try:
            decoded = json.loads(raw)
            content = decoded["choices"][0]["message"]["content"]
            result = json.loads(content) if isinstance(content, str) else content
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            _LOG.warning("event=provider_invalid_response provider=openrouter reason=malformed")
            raise OpenRouterFallbackInvalidResponse("OpenRouter fallback response is malformed") from exc
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
            raise OpenRouterFallbackInvalidResponse("fallback result is not an object")
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
