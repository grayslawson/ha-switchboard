from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.ha_switchboard.client import GatewayClient
from custom_components.ha_switchboard.conversation import (
    ConversationRequest,
    JevConversationEntity,
    async_setup_entry,
)
from custom_components.ha_switchboard.execution import ExecutionBoundary


class FakeClient:
    async def process(self, payload):
        assert "entity_id" not in str(payload)
        return {"kind": "execute", "response_key": "execute", "request_id": payload["request_id"]}


def test_conversation_request_contains_only_gateway_contract_fields() -> None:
    payload = ConversationRequest("turn on the light", "conversation-one").payload()
    assert payload["utterance"] == "turn on the light"
    assert "token" not in payload
    assert "entity_id" not in payload


def test_conversation_gateway_helper_returns_gateway_result() -> None:
    async def run():
        entity = JevConversationEntity(FakeClient())
        result = await entity._async_process_gateway(
            ConversationRequest("hello", "conversation-one")
        )
        assert result["response_key"] == "execute"

    asyncio.run(run())


def test_conversation_unique_id_is_stable_for_config_entry() -> None:
    async def run():
        entities = []
        runtime_data = SimpleNamespace(client=FakeClient(), executor=object(), coordinator=None)
        for entry_id in ("entry-one", "entry-one", "entry-two"):
            entry = SimpleNamespace(entry_id=entry_id, runtime_data=runtime_data)
            await async_setup_entry(SimpleNamespace(data={}), entry, entities.extend)

        assert [entity._attr_unique_id for entity in entities] == [
            "entry-one_conversation",
            "entry-one_conversation",
            "entry-two_conversation",
        ]

    asyncio.run(run())


def test_gateway_helper_without_core_context_accepts_existing_boundary_double() -> None:
    class FakeGateway:
        async def process(self, _payload):
            return {
                "kind": "execute",
                "capability_id": "opaque-one",
                "profile_revision": "profile-one",
            }

        async def status(self):
            return {"profile_revision": "profile-one"}

    class FakeBoundary:
        async def execute_proposal(
            self,
            *,
            capability_id,
            parameters,
            expected_profile_revision,
            current_profile_revision,
            confirmed,
        ):
            assert capability_id == "opaque-one"
            return {"response_key": "execute_verified"}

    async def run():
        entity = JevConversationEntity(FakeGateway(), FakeBoundary())
        request = ConversationRequest("turn on the light", "conversation-one")
        result = await entity._async_process_gateway(request)
        assert result["response_key"] == "execute_verified"

    asyncio.run(run())


def test_gateway_client_does_not_put_home_assistant_token_in_payload() -> None:
    client = GatewayClient("http://ha-switchboard:8099", "gateway-secret")
    assert client.gateway_token == "gateway-secret"
