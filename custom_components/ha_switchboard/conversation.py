"""Native ConversationEntity adapter with a strict gateway/execution split."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from .client import GatewayClient, GatewayClientError
from .execution import CoreHomeAssistantExecutor, ExecutionBoundary

try:  # pragma: no cover - exercised in the Home Assistant devcontainer
    from homeassistant.components import conversation
    from homeassistant.components.conversation import ConversationEntity
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

    def payload(self) -> dict[str, Any]:
        return {
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


def _response_text(result: Mapping[str, Any]) -> str:
    if isinstance(result.get("text"), str) and result["text"].strip():
        return str(result["text"])
    return {
        "execute": "Done.",
        "execute_verified": "Done.",
        "clarification_required": "Which device did you mean?",
        "confirmation_required": "Please confirm that action.",
        "profile_stale": "I need to refresh the Home Assistant capability profile first.",
        "gateway_unavailable": "The HA Switchboard gateway is unavailable.",
    }.get(str(result.get("response_key", "")), "I could not safely complete that request.")


class JevConversationEntity(ConversationEntity):
    _attr_name = "HA Switchboard"
    _attr_has_entity_name = True

    def __init__(self, client: GatewayClient, boundary: ExecutionBoundary | None = None) -> None:
        self.client = client
        self.boundary = boundary

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return "*"

    async def async_process(self, request: ConversationRequest) -> dict[str, Any]:
        try:
            result = dict(await self.client.process(request.payload()))
        except GatewayClientError:
            return {"kind": "refuse", "response_key": "gateway_unavailable"}
        if result.get("kind") == "execute" and self.boundary and result.get("capability_id"):
            try:
                status = await self.client.status()
                current_revision = str(status.get("profile_revision", ""))
            except GatewayClientError:
                return {**result, "kind": "refuse", "response_key": "profile_stale"}
            result = {
                **result,
                **await self.boundary.execute_proposal(
                    capability_id=str(result["capability_id"]),
                    parameters={},
                    expected_profile_revision=str(result.get("profile_revision", "")),
                    current_profile_revision=current_revision,
                    confirmed=bool(request.sanitized_state.get("confirmation", False)),
                ),
            }
        return result

    async def _async_handle_message(self, user_input: Any, chat_log: Any) -> Any:
        request = ConversationRequest(
            text=str(getattr(user_input, "text", "")),
            conversation_id=str(getattr(user_input, "conversation_id", "") or uuid.uuid4().hex),
            language=str(getattr(user_input, "language", "en")),
        )
        result = await self.async_process(request)
        if not HA_AVAILABLE:
            return result
        response = intent.IntentResponse(language=request.language)
        response.async_set_speech(_response_text(result))
        return conversation.ConversationResult(
            conversation_id=request.conversation_id,
            response=response,
            continue_conversation=result.get("response_key") in {"clarification_required", "confirmation_required"},
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register one Core-side conversation entity for the config entry."""

    data = dict(getattr(entry, "data", {}))
    client = GatewayClient(data.get("gateway_url", "http://ha-switchboard:8099"), data.get("gateway_token", ""))
    async_add_entities([JevConversationEntity(client, ExecutionBoundary(CoreHomeAssistantExecutor(hass)))])


if HA_AVAILABLE:
    JevConversationEntity._attr_supported_features = conversation.ConversationEntityFeature.CONTROL
