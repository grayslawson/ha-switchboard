"""Native ConversationEntity adapter with a strict gateway/execution split."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping

from .client import GatewayClient, GatewayClientError
from .execution import ExecutionBoundary
from .read_only import read_only_answer

if TYPE_CHECKING:
    from homeassistant.components.conversation import ChatLog, ConversationInput, ConversationResult
    from homeassistant.core import Context

    from .runtime import SwitchboardRuntimeData


_RAW_REFERENCE_KEYS = frozenset({"entity_id", "device_id", "area_id", "unique_id", "config_entry_id"})


def _assert_gateway_safe(value: Any, key: str | None = None) -> None:
    if key and key.lower() in _RAW_REFERENCE_KEYS:
        raise ValueError("raw Home Assistant references are Core-local")
    if isinstance(value, Mapping):
        for item_key, item in value.items():
            _assert_gateway_safe(item, str(item_key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_gateway_safe(item)


try:  # pragma: no cover - exercised in the Home Assistant devcontainer
    from homeassistant.components import conversation
    from homeassistant.components.conversation import ConversationEntity
    from homeassistant.components.conversation.chat_log import AssistantContent
    from homeassistant.helpers import intent
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.core import HomeAssistant

    HA_AVAILABLE = True
except ImportError:
    HA_AVAILABLE = False

    class ConversationEntity:  # type: ignore[no-redef]
        _attr_name = "HA Switchboard"


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

    def payload(self) -> dict[str, Any]:
        payload = {
            "request_id": uuid.uuid4().hex,
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
    if isinstance(result.get("text"), str) and result["text"].strip():
        answer = str(result["text"]).strip()
        if "i could not safely complete that request" not in answer.casefold():
            return answer
    if result.get("response_key") in {"batch_execute_verified", "batch_partial_failure"}:
        verified = int(result.get("verified_count", 0))
        total = int(result.get("total_count", 0))
        if result.get("response_key") == "batch_execute_verified":
            return f"Done. I verified {verified} of {total} exposed devices."
        return f"I verified {verified} of {total} devices before stopping. Some devices may still need attention."
    return {
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
        "fallback_target_unverified": "The fallback model could not match one offered device and action clearly. No device action was taken.",
        "candidate_not_allowed": "That device or action isn't exposed to Switchboard.",
        "privacy_mode_denied": "The App's privacy setting blocks this hosted decision service.",
        "jev_unavailable": "The Jev decision service did not respond. Check the Switchboard App log.",
        "jev_invalid_response": "The Jev decision service returned an unsupported answer. Check the Switchboard App log.",
        "batch_no_targets": "I found no exposed devices matching that group.",
        "batch_too_large": "That group is larger than Switchboard's 32-device safety limit. Please narrow it to a room.",
        "batch_scope_ambiguous": "I couldn't determine one safe device group and action. Please name a room and device type.",
        "batch_target_unavailable": "At least one device in that group is unavailable, so I changed none of them.",
        "batch_confirmation_unsupported": "That group includes an action requiring confirmation, so I changed none of them.",
        "batch_invalid": "The device group failed a safety check, so I changed none of them.",
        "confirmation_required": "This action requires confirmation, which this conversation flow cannot collect yet.",
        "invalid_parameters": "I could not validate the requested value.",
        "post_action_unverified": "Home Assistant did not confirm that action.",
        "profile_stale": "I need to refresh the Home Assistant capability profile first.",
        "profile_reconciling": "The Home Assistant capability profile is updating. Please try again in a few seconds.",
        "invalid_request": "The request could not be validated. Check the Switchboard App log.",
        "gateway_unavailable": "The HA Switchboard gateway is unavailable.",
    }.get(str(result.get("response_key", "")), "Switchboard has no supported result for this request. Check the App log for its decision code.")


class JevConversationEntity(ConversationEntity):
    _attr_name = "HA Switchboard"
    _attr_has_entity_name = True

    def __init__(
        self,
        client: GatewayClient,
        boundary: ExecutionBoundary | None = None,
        coordinator: Any = None,
        entry_id: str | None = None,
    ) -> None:
        self.client = client
        self.boundary = boundary
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_conversation" if entry_id is not None else None

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return "*"

    async def _async_process_gateway(
        self, request: ConversationRequest, *, context: Context | None = None
    ) -> dict[str, Any]:
        """Send a bounded request to the gateway and handle any Core-local action."""
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
            result = dict(await self.client.process(request.payload()))
        except GatewayClientError:
            return {"kind": "refuse", "response_key": "gateway_unavailable"}
        except ValueError:
            return {"kind": "refuse", "response_key": "invalid_request"}

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
                ),
            }
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
                ),
            }
        return result

    async def _async_handle_message(
        self, user_input: ConversationInput, chat_log: ChatLog
    ) -> ConversationResult:
        request = ConversationRequest(
            text=str(getattr(user_input, "text", "")),
            conversation_id=str(getattr(user_input, "conversation_id", "") or uuid.uuid4().hex),
            language=str(getattr(user_input, "language", "en")),
        )
        local_answer = None
        if self.coordinator is not None and self.coordinator.writes_allowed():
            local_answer = read_only_answer(
                self.hass,
                request.text,
                self.coordinator.snapshot,
                self.coordinator.capability_map,
                self.coordinator.read_targets,
            )
        result = (
            {"kind": "answer", "response_key": "read_only_answer", "text": local_answer}
            if local_answer is not None
            else await self._async_process_gateway(request, context=user_input.context)
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
            # A new turn currently does not carry a pending target or confirmation
            # back to the gateway. Do not advertise a follow-up flow we cannot honor.
            continue_conversation=False,
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
                ExecutionBoundary(runtime_data.executor),
                runtime_data.coordinator,
                entry_id=entry.entry_id,
            )
        ]
    )


if HA_AVAILABLE:
    JevConversationEntity._attr_supported_features = conversation.ConversationEntityFeature.CONTROL
