"""Native ConversationEntity adapter with a strict gateway/execution split."""

from __future__ import annotations

import uuid
import inspect
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping

from .client import GatewayClient, GatewayClientError
from .execution import ExecutionBoundary
from .conversation_context import ConversationContextStore
from .diagnostics import CoreDiagnosticLog
from .native_path import native_intent_filter
from .read_only import read_only_answer

if TYPE_CHECKING:
    from homeassistant.components.conversation import ChatLog, ConversationInput, ConversationResult
    from homeassistant.core import Context

    from .runtime import SwitchboardRuntimeData


_RAW_REFERENCE_KEYS = frozenset({"entity_id", "device_id", "area_id", "unique_id", "config_entry_id"})
_PROHIBITED_RESPONSE_PATTERN = re.compile(
    r"\bi\s+could(?:\s+not|n['’]?t)\s+(?:safely\s+)?complete\s+that\s+request\b",
    re.IGNORECASE,
)
_CONTINUATION_KEYS = frozenset(
    {
        "confirmation_required",
        "clarification_required",
        "confidence_too_low",
        "ambiguous_request",
        "parameter_required",
    }
)
_AFFIRMATIVE_REPLIES = frozenset(
    {"yes", "y", "yeah", "yep", "yes please", "confirm", "do it", "okay", "ok", "sure"}
)
_NEGATIVE_REPLIES = frozenset(
    {"no", "n", "nope", "cancel", "cancel that", "never mind", "never mind that"}
)

_RESPONSE_TEXT = {
    "execute": "Done.",
    "execute_verified": "Done.",
    "clarification_required": "Please make a new request naming one device and what you want it to do.",
    "confidence_too_low": "I couldn't identify one device confidently. Please name its room or exact device name and the action.",
    "ambiguous_request": "More than one device or action may match. Please name one device and action.",
    "request_refused": "I can't handle that request with the capabilities currently available to Switchboard.",
    "route_not_allowed": "No fallback route is eligible under the current privacy, latency, and cost policy. Check the App fallback settings.",
    "handoff_unavailable": "The configured fallback model did not respond. Check the App log and fallback settings.",
    "handoff_invalid_response": "The fallback model returned an unsupported answer. No device action was taken.",
    "handoff_loop_detected": "A second model handoff is not allowed for this request.",
    "execution_failed": "Home Assistant did not complete that action. Check the Switchboard log and try again.",
    "fallback_target_unverified": "The fallback model could not match one offered device and action clearly. No device action was taken.",
    "candidate_not_allowed": "That device or action is not exposed to Switchboard. Choose an exposed device from the offered choices.",
    "privacy_mode_denied": "The App's privacy setting blocks this hosted decision service.",
    "jev_unavailable": "The Jev decision service did not respond. Check the Switchboard App log.",
    "jev_invalid_response": "The Jev decision service returned an unsupported answer. Check the Switchboard App log.",
    "batch_no_targets": "I found no exposed devices matching that group.",
    "batch_too_large": "That group is larger than Switchboard's 32-device safety limit. Please narrow it to a room.",
    "batch_scope_ambiguous": "I couldn't determine one safe device group and action. Please name a room and device type.",
    "batch_target_unavailable": "At least one device in that group is unavailable, so I changed none of them.",
    "batch_confirmation_unsupported": "That group includes an action requiring confirmation, so I changed none of them.",
    "batch_invalid": "The device group failed a safety check, so I changed none of them.",
    "confirmation_required": "This action needs your confirmation; I cannot collect yet without your yes. Say yes to continue or no to cancel.",
    "parameter_required": "I need one more value before I can do that. Please provide the requested value.",
    "invalid_parameters": "That value is outside the supported range. Please provide a value within the range shown in the request.",
    "post_action_unverified": "Home Assistant did not confirm that action.",
    "profile_stale": "I need to refresh the Home Assistant capability profile first.",
    "profile_reconciling": "The Home Assistant capability profile is updating. Please try again in a few seconds.",
    "invalid_request": "The request could not be validated. Check the Switchboard App log.",
    "gateway_unavailable": "The HA Switchboard gateway is unavailable.",
    "policy_denied": "That action is blocked by the current safety policy. Try a supported routine action.",
    "read_only_answer": "I found the current state locally.",
    "confirmation_cancelled": "Okay, I did not change anything.",
}


def _normalized_reply(value: str) -> str:
    """Normalize a short Assist continuation without accepting free-form IDs."""

    value = re.sub(r"[.,!?;:]+", " ", value.strip().casefold())
    return re.sub(r"\s+", " ", value).strip()


def _confirmation_reply(value: str) -> bool | None:
    """Return True/False for an explicit confirmation, otherwise None."""

    normalized = _normalized_reply(value)
    if normalized in _AFFIRMATIVE_REPLIES:
        return True
    if normalized in _NEGATIVE_REPLIES:
        return False
    return None


def _candidate_reply(value: str) -> str:
    """Normalize a numbered or display-name clarification answer."""

    normalized = _normalized_reply(value)
    return re.sub(r"^#?(\d+)[.)]?$", r"\1", normalized)


def _assert_gateway_safe(value: Any, key: str | None = None) -> None:
    if key and key.lower() in _RAW_REFERENCE_KEYS:
        raise ValueError("raw Home Assistant references are Core-local")
    if isinstance(value, Mapping):
        for item_key, item in value.items():
            _assert_gateway_safe(item, str(item_key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_gateway_safe(item)


def _optional_request_id(boundary_method: Any, request_id: str) -> dict[str, str]:
    """Pass idempotency metadata only to boundaries that support it.

    The Core execution boundary gained ``request_id`` in 0.2.0. Keeping this
    keyword optional preserves compatibility with older adapters and small
    test doubles while the native boundary still receives the idempotency key.
    """

    try:
        parameters = inspect.signature(boundary_method).parameters.values()
    except (TypeError, ValueError):
        return {"request_id": request_id}
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return {"request_id": request_id}
    if any(parameter.name == "request_id" for parameter in parameters):
        return {"request_id": request_id}
    return {}


try:  # pragma: no cover - exercised in the Home Assistant devcontainer
    from homeassistant.components import conversation
    from homeassistant.components.conversation import ConversationEntity
    from homeassistant.components.conversation.chat_log import AssistantContent
    from homeassistant.helpers import intent
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.core import HomeAssistant
    from homeassistant.exceptions import HomeAssistantError

    HA_AVAILABLE = True
except ImportError:
    HA_AVAILABLE = False

    class ConversationEntity:  # type: ignore[no-redef]
        _attr_name = "HA Switchboard"

    class HomeAssistantError(Exception):  # type: ignore[no-redef]
        """Fallback marker used when Home Assistant is not installed."""


@dataclass(slots=True)
class ConversationRequest:
    text: str
    conversation_id: str
    language: str = "en"
    profile_revision: str = ""
    candidates: tuple[Mapping[str, Any], ...] = ()
    bounded_context: tuple[Mapping[str, Any], ...] = ()
    sanitized_state: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def payload(self) -> dict[str, Any]:
        if self.request_id is None:
            self.request_id = uuid.uuid4().hex
        payload = {
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "utterance": self.text,
            "language": self.language,
            "profile_revision": self.profile_revision,
            "policy_revision": "policy-1",
            "candidates": list(self.candidates),
            "bounded_context": list(self.bounded_context),
            "sanitized_state": dict(self.sanitized_state),
        }
        _assert_gateway_safe(payload)
        return payload


def _response_text(result: Mapping[str, Any]) -> str:
    response_key = str(result.get("response_key", ""))
    if isinstance(result.get("text"), str) and result["text"].strip():
        answer = str(result["text"]).strip()
        if not _PROHIBITED_RESPONSE_PATTERN.search(answer):
            return answer
    if response_key in {"batch_execute_verified", "batch_partial_failure"}:
        verified = int(result.get("verified_count", 0))
        total = int(result.get("total_count", 0))
        if response_key == "batch_execute_verified":
            return f"Done. I verified {verified} of {total} exposed devices."
        return f"I verified {verified} of {total} devices before stopping. Some devices may still need attention."
    return _RESPONSE_TEXT.get(response_key, "Switchboard could not match that request to a supported action. Try naming the room and device.")


class JevConversationEntity(ConversationEntity):
    _attr_name = "HA Switchboard"
    _attr_has_entity_name = True

    def __init__(
        self,
        client: GatewayClient,
        boundary: ExecutionBoundary | None = None,
        coordinator: Any = None,
        entry_id: str | None = None,
        context_store: ConversationContextStore | None = None,
        diagnostics: CoreDiagnosticLog | None = None,
    ) -> None:
        self.client = client
        self.boundary = boundary
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_conversation" if entry_id is not None else None
        self.context_store = context_store or ConversationContextStore()
        self.diagnostics = diagnostics or CoreDiagnosticLog()

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return "*"

    async def _async_process_gateway(
        self, request: ConversationRequest, *, context: Context | None = None
    ) -> dict[str, Any]:
        """Send a bounded request to the gateway and handle any Core-local action."""
        if request.request_id is None:
            request.request_id = uuid.uuid4().hex
        self.diagnostics.record(
            "gateway_request_started",
            correlation_id=request.request_id,
            operation="process",
        )
        try:
            if self.coordinator is not None:
                profile_context = self.coordinator.request_context()
                if not request.profile_revision:
                    request.profile_revision = str(profile_context.get("profile_revision", ""))
                if not request.candidates:
                    request.candidates = tuple(profile_context.get("candidates", ()))
                if not request.bounded_context:
                    request.bounded_context = tuple(profile_context.get("bounded_context", ()))
                if not request.sanitized_state:
                    request.sanitized_state = dict(profile_context.get("sanitized_state", {}))
            payload = request.payload()
            result = dict(await self.client.process(payload))
        except GatewayClientError as exc:
            self.diagnostics.record_exception(
                exc,
                correlation_id=request.request_id,
                operation="gateway_request",
            )
            return {"kind": "refuse", "response_key": "gateway_unavailable"}
        except ValueError as exc:
            self.diagnostics.record_exception(
                exc,
                correlation_id=request.request_id,
                operation="gateway_request",
            )
            return {"kind": "refuse", "response_key": "invalid_request"}

        self.diagnostics.record(
            "conversation_result",
            correlation_id=request.request_id,
            kind=str(result.get("kind", "unknown")),
            response_key=str(result.get("response_key", "unknown")),
        )

        if result.get("kind") == "execute" and self.boundary and result.get("capability_ids"):
            ids = result["capability_ids"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 32 or any(not isinstance(item, str) for item in ids):
                return {**result, "kind": "refuse", "response_key": "batch_invalid"}
            try:
                current_revision = (
                    str(self.coordinator.profile_revision)
                    if self.coordinator is not None and self.coordinator.profile_revision
                    else str((await self.client.status()).get("profile_revision", ""))
                )
            except GatewayClientError:
                return {**result, "kind": "refuse", "response_key": "profile_stale"}
            execution_context: dict[str, Any] = {"context": context} if context is not None else {}
            result = {
                **result,
                **await self.boundary.execute_batch_proposal(
                    capability_ids=tuple(ids),
                    expected_profile_revision=str(result.get("profile_revision", request.profile_revision)),
                    current_profile_revision=current_revision,
                    **execution_context,
                    **_optional_request_id(
                        self.boundary.execute_batch_proposal,
                        str(payload.get("request_id")),
                    ),
                ),
            }
            self.diagnostics.record(
                "batch_outcome",
                correlation_id=request.request_id,
                level="info" if result.get("ok") else "warning",
                outcome=str(result.get("response_key", "unknown")),
                verified_count=result.get("verified_count", 0),
                total_count=result.get("total_count", len(ids)),
            )
        elif result.get("kind") == "execute" and self.boundary and result.get("capability_id"):
            try:
                current_revision = (
                    str(self.coordinator.profile_revision)
                    if self.coordinator is not None and self.coordinator.profile_revision
                    else str((await self.client.status()).get("profile_revision", ""))
                )
            except GatewayClientError:
                return {**result, "kind": "refuse", "response_key": "profile_stale"}
            returned_parameters = result.get("parameters", {})
            if not isinstance(returned_parameters, Mapping):
                returned_parameters = {}
            execution_context: dict[str, Any] = {"context": context} if context is not None else {}
            result = {
                **result,
                **await self.boundary.execute_proposal(
                    capability_id=str(result["capability_id"]),
                    parameters=returned_parameters,
                    expected_profile_revision=str(result.get("profile_revision", request.profile_revision)),
                    current_profile_revision=current_revision,
                    confirmed=bool(request.sanitized_state.get("confirmation", False)),
                    **execution_context,
                    **_optional_request_id(
                        self.boundary.execute_proposal,
                        str(payload.get("request_id")),
                    ),
                ),
            }
            self.diagnostics.record(
                "execution_outcome",
                correlation_id=request.request_id,
                level="info" if result.get("ok") else "warning",
                outcome=str(result.get("response_key", "unknown")),
            )
        else:
            self.diagnostics.record(
                "gateway_request_completed",
                correlation_id=request.request_id,
                outcome=str(result.get("response_key", "unknown")),
            )
        return result

    async def _async_native_fast_path(
        self, user_input: ConversationInput, chat_log: ChatLog, request_id: str
    ) -> Any | None:
        """Let Home Assistant handle a bounded routine intent locally.

        Home Assistant owns native entity/area/domain resolution. This calls
        the public strict-intent helper, which delegates to the default agent
        rather than invoking a conversation agent and therefore cannot recurse
        back into this entity. A missing Core conversation setup is treated as
        a clean miss and continues to the existing local/gateway routes.
        """

        if not HA_AVAILABLE:
            return None
        hass = getattr(self, "hass", None)
        data = getattr(hass, "data", None)
        component_key = getattr(conversation, "DATA_COMPONENT", None)
        handler = getattr(conversation, "async_handle_intents", None)
        if not isinstance(data, Mapping) or component_key is None or component_key not in data:
            return None
        if not callable(handler):
            return None

        try:
            native_response = await handler(
                hass,
                user_input,
                chat_log,
                intent_filter=native_intent_filter,
            )
        except (HomeAssistantError, RuntimeError, ValueError, TypeError, OSError) as exc:
            self.diagnostics.record_exception(
                exc,
                correlation_id=request_id,
                operation="native_fast_path",
            )
            return None
        self.diagnostics.record(
            "native_fast_path",
            correlation_id=request_id,
            outcome="handled" if native_response is not None else "miss",
        )
        return native_response

    async def _async_handle_message(
        self, user_input: ConversationInput, chat_log: ChatLog
    ) -> ConversationResult:
        request = ConversationRequest(
            text=str(getattr(user_input, "text", "")),
            conversation_id=str(getattr(user_input, "conversation_id", "") or uuid.uuid4().hex),
            language=str(getattr(user_input, "language", "en")),
        )
        request.request_id = uuid.uuid4().hex
        conversation_id = request.conversation_id
        user_id = getattr(getattr(user_input, "context", None), "user_id", None)
        pending = self.context_store.peek(conversation_id, user_id)
        if pending is not None:
            self.diagnostics.record(
                "continuation_received",
                correlation_id=str(pending.request.get("request_id", "")) or None,
                kind=pending.kind,
            )
            answer = _normalized_reply(request.text)
            if pending.kind == "confirmation":
                confirmation = _confirmation_reply(request.text)
                if confirmation is False:
                    self.context_store.consume(conversation_id, user_id)
                    self.diagnostics.record(
                        "continuation_cancelled",
                        correlation_id=str(pending.request.get("request_id", "")) or None,
                        kind=pending.kind,
                    )
                    result = {"kind": "answer", "response_key": "confirmation_cancelled", "text": "Okay, I did not change anything."}
                elif confirmation is True:
                    self.context_store.consume(conversation_id, user_id)
                    self.diagnostics.record(
                        "continuation_accepted",
                        correlation_id=str(pending.request.get("request_id", "")) or None,
                        kind=pending.kind,
                    )
                    original = dict(pending.request)
                    request = ConversationRequest(
                        text=str(original.get("utterance", "")), conversation_id=conversation_id,
                        language=str(original.get("language", "en")), profile_revision=str(original.get("profile_revision", "")),
                        candidates=tuple(original.get("candidates", ())), bounded_context=tuple(original.get("bounded_context", ())),
                        sanitized_state={**dict(original.get("sanitized_state", {})), "confirmation": True},
                        request_id=str(original.get("request_id", "")) or None,
                    )
                    result = await self._async_process_gateway(request, context=user_input.context)
                else:
                    self.diagnostics.record(
                        "continuation_rejected",
                        correlation_id=str(pending.request.get("request_id", "")) or None,
                        kind=pending.kind,
                    )
                    result = {"kind": "confirm", "response_key": "confirmation_required"}
            elif pending.kind == "clarification":
                # A numbered answer or exact offered display name selects an
                # opaque candidate; arbitrary IDs are never accepted from speech.
                original = dict(pending.request)
                candidates = tuple(original.get("candidates", ()))
                candidate_answer = _candidate_reply(request.text)
                index = int(candidate_answer) - 1 if candidate_answer.isdigit() else -1
                selected = candidates[index:index + 1] if 0 <= index < len(candidates) else tuple(
                    item for item in candidates
                    if isinstance(item, Mapping)
                    and _normalized_reply(str(item.get("display_name", ""))) == candidate_answer
                )
                if len(selected) == 1:
                    self.context_store.consume(conversation_id, user_id)
                    self.diagnostics.record(
                        "continuation_accepted",
                        correlation_id=str(pending.request.get("request_id", "")) or None,
                        kind=pending.kind,
                    )
                    request = ConversationRequest(
                        text=str(original.get("utterance", "")), conversation_id=conversation_id,
                        language=str(original.get("language", "en")), profile_revision=str(original.get("profile_revision", "")),
                        candidates=selected, bounded_context=tuple(original.get("bounded_context", ())),
                        sanitized_state=dict(original.get("sanitized_state", {})), request_id=str(original.get("request_id", "")) or None,
                    )
                    result = await self._async_process_gateway(request, context=user_input.context)
                else:
                    self.diagnostics.record(
                        "continuation_rejected",
                        correlation_id=str(pending.request.get("request_id", "")) or None,
                        kind=pending.kind,
                    )
                    result = {"kind": "clarify", "response_key": "clarification_required"}
            elif pending.kind == "parameter":
                # Keep the original bounded request and pass the user's
                # value back as sanitized continuation context. The gateway
                # remains responsible for interpreting and validating it;
                # Core never turns spoken text into service data locally.
                self.context_store.consume(conversation_id, user_id)
                original = dict(pending.request)
                request = ConversationRequest(
                    text=str(original.get("utterance", "")),
                    conversation_id=conversation_id,
                    language=str(original.get("language", "en")),
                    profile_revision=str(original.get("profile_revision", "")),
                    candidates=tuple(original.get("candidates", ())),
                    bounded_context=tuple(original.get("bounded_context", ())),
                    sanitized_state={
                        **dict(original.get("sanitized_state", {})),
                        "follow_up_value": answer,
                    },
                    request_id=str(original.get("request_id", "")) or None,
                )
                result = await self._async_process_gateway(request, context=user_input.context)
                self.diagnostics.record(
                    "parameter_continuation",
                    correlation_id=request.request_id,
                    kind=pending.kind,
                )
            else:
                self.diagnostics.record(
                    "continuation_rejected",
                    correlation_id=str(pending.request.get("request_id", "")) or None,
                    kind=pending.kind,
                )
                result = {"kind": "clarify", "response_key": "invalid_parameters"}
        else:
            result = None

        if result is None and HA_AVAILABLE:
            native_response = await self._async_native_fast_path(
                user_input,
                chat_log,
                request.request_id or uuid.uuid4().hex,
            )
            if native_response is not None:
                speech = native_response.speech.get("plain", {}).get("speech", "")
                chat_log.async_add_assistant_content_without_tools(
                    AssistantContent(agent_id=user_input.agent_id, content=speech)
                )
                return conversation.ConversationResult(
                    conversation_id=request.conversation_id,
                    response=native_response,
                )

        local_answer = None
        if result is None and self.coordinator is not None and self.coordinator.writes_allowed():
            local_answer = read_only_answer(
                self.hass,
                request.text,
                self.coordinator.snapshot,
                self.coordinator.capability_map,
                self.coordinator.read_targets,
            )
        result = result or (
            {"kind": "answer", "response_key": "read_only_answer", "text": local_answer}
            if local_answer is not None
            else await self._async_process_gateway(request, context=user_input.context)
        )
        if result.get("response_key") in _CONTINUATION_KEYS:
            kind = "confirmation" if result.get("response_key") == "confirmation_required" else "clarification"
            if result.get("response_key") == "parameter_required":
                kind = "parameter"
            self.context_store.put(request.conversation_id, user_id, kind, request.payload())
            self.diagnostics.record(
                "continuation_requested",
                correlation_id=request.request_id,
                kind=kind,
                response_key=str(result.get("response_key")),
            )
        if not HA_AVAILABLE:
            return result
        speech = _response_text(result)
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=speech)
        )
        response = intent.IntentResponse(language=request.language)
        response.async_set_speech(speech)
        return conversation.ConversationResult(
            conversation_id=request.conversation_id,
            response=response,
            continue_conversation=result.get("response_key") in _CONTINUATION_KEYS,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "Any",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register the Conversation entity against the entry's runtime data."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None and hasattr(hass, "data"):
        runtime_data = hass.data.get("ha_switchboard", {}).get(entry.entry_id)
    if runtime_data is None:
        raise RuntimeError("HA Switchboard runtime data is unavailable")
    async_add_entities(
        [
            JevConversationEntity(
                runtime_data.client,
                ExecutionBoundary(runtime_data.executor, getattr(runtime_data, "diagnostics", None)),
                runtime_data.coordinator,
                entry_id=entry.entry_id,
                diagnostics=getattr(runtime_data, "diagnostics", None),
            )
        ]
    )


if HA_AVAILABLE:
    JevConversationEntity._attr_supported_features = conversation.ConversationEntityFeature.CONTROL
