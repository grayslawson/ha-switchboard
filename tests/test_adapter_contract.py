from __future__ import annotations

import asyncio

from custom_components.ha_switchboard.client import GatewayClient
from custom_components.ha_switchboard.conversation import ConversationRequest, JevConversationEntity
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


def test_conversation_entity_returns_gateway_result() -> None:
    async def run():
        entity = JevConversationEntity(FakeClient())
        result = await entity.async_process(ConversationRequest("hello", "conversation-one"))
        assert result["response_key"] == "execute"

    asyncio.run(run())


def test_gateway_client_does_not_put_home_assistant_token_in_payload() -> None:
    client = GatewayClient("http://ha-switchboard:8099", "gateway-secret")
    assert client.gateway_token == "gateway-secret"
