"""Check the adapter through Home Assistant's real conversation base class."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.conversation import (  # noqa: E402
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.components.conversation.chat_log import AssistantContent, ChatLog  # noqa: E402
from homeassistant.core import Context  # noqa: E402

from custom_components.ha_switchboard.capabilities import (  # noqa: E402
    CapabilityMap,
    CapabilityTarget,
    operation_spec,
)
from custom_components.ha_switchboard.client import GatewayClientError  # noqa: E402
from custom_components.ha_switchboard.conversation import JevConversationEntity  # noqa: E402
from custom_components.ha_switchboard.execution import (  # noqa: E402
    CoreHomeAssistantExecutor,
    ExecutionBoundary,
)
from custom_components.ha_switchboard.opaque import adapter_ref, capability_id  # noqa: E402


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.payload = None

    async def process(self, payload):
        self.payload = payload
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def status(self):
        return {"profile_revision": "profile-one"}


@pytest.mark.parametrize(
    ("gateway_response", "expected_speech", "expected_continue"),
    [
        ({"kind": "execute", "response_key": "execute"}, "Done.", False),
        (
            {"kind": "clarify", "response_key": "clarification_required"},
            "Please make a new request naming one device and what you want it to do.",
            False,
        ),
        (
            {"kind": "refuse", "response_key": "confirmation_required"},
            "This action requires confirmation, which this conversation flow cannot collect yet.",
            False,
        ),
        (GatewayClientError("unavailable"), "The HA Switchboard gateway is unavailable.", False),
    ],
)
def test_core_async_process_dispatches_to_gateway_and_returns_conversation_result(
    gateway_response, expected_speech, expected_continue
):
    async def run():
        client = FakeClient(gateway_response)
        entity = JevConversationEntity(client, entry_id="entry-one")
        entity.hass = SimpleNamespace(data={})
        chat_log = ChatLog(entity.hass, "conversation-one")
        user_input = ConversationInput(
            text="Turn on the light",
            context=Context(),
            conversation_id="conversation-one",
            device_id=None,
            satellite_id=None,
            language="en",
            agent_id="conversation.ha_switchboard",
        )
        assert "async_process" not in JevConversationEntity.__dict__
        assert entity.async_process.__func__ is ConversationEntity.async_process
        assert entity.unique_id == "entry-one_conversation"

        with (
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_session",
                return_value=nullcontext(),
            ),
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_log",
                return_value=nullcontext(chat_log),
            ),
        ):
            result = await entity.async_process(user_input)

        assert isinstance(result, ConversationResult)
        assert result.conversation_id == "conversation-one"
        assert result.continue_conversation is expected_continue
        assert result.response.as_dict()["speech"]["plain"]["speech"] == expected_speech
        assistant_messages = [
            item for item in chat_log.content if isinstance(item, AssistantContent)
        ]
        assert len(assistant_messages) == 1
        assert assistant_messages[0].agent_id == user_input.agent_id
        assert assistant_messages[0].content == expected_speech
        assert client.payload["utterance"] == user_input.text
        assert client.payload["conversation_id"] == user_input.conversation_id
        assert client.payload["language"] == user_input.language
        assert "device_id" not in client.payload
        assert "context" not in client.payload

    asyncio.run(run())


def test_core_context_reaches_service_call_without_entering_gateway_payload():
    async def run():
        reference = adapter_ref("light.living_room")
        target = CapabilityTarget(
            capability_id(reference, "turn_on"),
            reference,
            "light.living_room",
            "light",
            "turn_on",
            operation_spec("light", "turn_on"),
        )
        mapping = CapabilityMap()
        mapping.replace("profile-one", {target.capability_id: target})
        state = SimpleNamespace(state="off", attributes={})
        calls = []

        async def async_call(domain, service, data, *, blocking, context):
            calls.append((domain, service, data, blocking, context))
            state.state = "on"

        hass = SimpleNamespace(
            data={},
            states=SimpleNamespace(get=lambda entity_id: state),
            services=SimpleNamespace(async_call=async_call),
        )
        client = FakeClient(
            {
                "kind": "execute",
                "response_key": "execute",
                "capability_id": target.capability_id,
                "profile_revision": "profile-one",
                "parameters": {},
            }
        )
        entity = JevConversationEntity(
            client, ExecutionBoundary(CoreHomeAssistantExecutor(hass, mapping))
        )
        entity.hass = hass
        chat_log = ChatLog(hass, "conversation-one")
        user_input = ConversationInput(
            text="Turn on the light",
            context=Context(user_id="user-one"),
            conversation_id="conversation-one",
            device_id="device-local-only",
            satellite_id=None,
            language="en",
            agent_id="conversation.ha_switchboard",
        )

        with (
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_session",
                return_value=nullcontext(),
            ),
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_log",
                return_value=nullcontext(chat_log),
            ),
        ):
            result = await entity.async_process(user_input)

        assert len(calls) == 1
        assert calls[0][:4] == ("light", "turn_on", {"entity_id": "light.living_room"}, True)
        assert calls[0][4] is user_input.context
        assert result.response.as_dict()["speech"]["plain"]["speech"] == "Done."
        assert isinstance(chat_log.content[-1], AssistantContent)
        assert chat_log.content[-1].content == "Done."
        assert "context" not in client.payload
        assert "device_id" not in client.payload
        assert "user-one" not in repr(client.payload)

    asyncio.run(run())
