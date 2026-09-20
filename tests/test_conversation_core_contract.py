"""Check the adapter through Home Assistant's real conversation base class."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip(
    "homeassistant",
    reason="Home Assistant 2026.9 runtime is required for Assist ConversationEntity contract tests",
)

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
from custom_components.ha_switchboard.conversation import (  # noqa: E402
    JevConversationEntity,
    async_setup_entry,
)
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


def test_conversation_platform_registers_one_selectable_entity_for_config_entry():
    async def run():
        from homeassistant.components import conversation as conversation_component

        entities = []
        runtime_data = SimpleNamespace(
            client=FakeClient({"kind": "refuse", "response_key": "gateway_unavailable"}),
            executor=object(),
            coordinator=None,
            diagnostics=None,
        )
        entry = SimpleNamespace(entry_id="entry-one", runtime_data=runtime_data)

        await async_setup_entry(SimpleNamespace(data={}), entry, entities.extend)

        assert len(entities) == 1
        entity = entities[0]
        assert isinstance(entity, ConversationEntity)
        assert entity.unique_id == "entry-one_conversation"
        assert entity._attr_name == "HA Switchboard"
        assert entity._attr_has_entity_name is True
        assert entity.supported_languages == "*"
        assert entity._attr_supported_features == conversation_component.ConversationEntityFeature.CONTROL

    asyncio.run(run())


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
            "This action needs your confirmation. Say yes to continue or no to cancel.",
            True,
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


def test_native_routine_intent_is_handled_by_home_assistant_without_gateway():
    async def run():
        from unittest.mock import AsyncMock

        from homeassistant.components import conversation as conversation_component
        from homeassistant.helpers import intent

        from custom_components.ha_switchboard.native_path import native_intent_filter

        client = FakeClient({"kind": "refuse", "response_key": "gateway_unavailable"})
        hass = SimpleNamespace(data={conversation_component.DATA_COMPONENT: object()})
        entity = JevConversationEntity(client, entry_id="entry-one")
        entity.hass = hass
        chat_log = ChatLog(hass, "conversation-one")
        user_input = ConversationInput(
            text="turn on the kitchen lights",
            context=Context(),
            conversation_id="conversation-one",
            device_id=None,
            satellite_id=None,
            language="en",
            agent_id="conversation.ha_switchboard",
        )
        native_response = intent.IntentResponse(language="en")
        native_response.async_set_speech("Done natively.")
        native_handler = AsyncMock(return_value=native_response)

        with (
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_session",
                return_value=nullcontext(),
            ),
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_log",
                return_value=nullcontext(chat_log),
            ),
            patch(
                "custom_components.ha_switchboard.conversation.conversation.async_handle_intents",
                native_handler,
            ),
        ):
            result = await entity.async_process(user_input)

        native_handler.assert_awaited_once()
        assert native_handler.await_args.args == (hass, user_input, chat_log)
        assert native_handler.await_args.kwargs["intent_filter"] is native_intent_filter
        assert client.payload is None
        assert result.response is native_response
        assert result.response.as_dict()["speech"]["plain"]["speech"] == "Done natively."
        assert result.continue_conversation is False
        assert any(
            item["code"] == "native_fast_path" and item["outcome"] == "handled"
            for item in entity.diagnostics.list(limit=10)
        )

    asyncio.run(run())


def test_native_miss_continues_to_switchboard_without_false_native_success():
    async def run():
        from unittest.mock import AsyncMock

        from homeassistant.components import conversation as conversation_component

        client = FakeClient({"kind": "refuse", "response_key": "gateway_unavailable"})
        hass = SimpleNamespace(data={conversation_component.DATA_COMPONENT: object()})
        entity = JevConversationEntity(client, entry_id="entry-one")
        entity.hass = hass
        chat_log = ChatLog(hass, "conversation-one")
        user_input = ConversationInput(
            text="what is the status of the house",
            context=Context(),
            conversation_id="conversation-one",
            device_id=None,
            satellite_id=None,
            language="en",
            agent_id="conversation.ha_switchboard",
        )
        native_handler = AsyncMock(return_value=None)

        with (
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_session",
                return_value=nullcontext(),
            ),
            patch(
                "homeassistant.components.conversation.entity.async_get_chat_log",
                return_value=nullcontext(chat_log),
            ),
            patch(
                "custom_components.ha_switchboard.conversation.conversation.async_handle_intents",
                native_handler,
            ),
        ):
            result = await entity.async_process(user_input)

        native_handler.assert_awaited_once()
        assert callable(native_handler.await_args.kwargs["intent_filter"])
        assert client.payload is not None
        assert client.payload["utterance"] == user_input.text
        assert result.response.as_dict()["speech"]["plain"]["speech"] == (
            "The HA Switchboard gateway is unavailable."
        )
        assert any(
            item["code"] == "native_fast_path" and item["outcome"] == "miss"
            for item in entity.diagnostics.list(limit=10)
        )

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


def test_response_language_has_reason_specific_next_steps_and_no_prohibited_generic_sentence():
    from custom_components.ha_switchboard.conversation import _response_text

    prohibited = "I could not safely complete that request."
    for key in (
        "profile_stale", "candidate_not_allowed", "invalid_parameters", "jev_invalid_response",
        "confirmation_required", "post_action_unverified",
    ):
        text = _response_text({"response_key": key})
        assert text and prohibited not in text
        assert any(marker in text.casefold() for marker in ("please", "check", "not", "action", "device", "value"))
