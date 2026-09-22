import asyncio
from types import SimpleNamespace

from custom_components.ha_switchboard.conversation_context import ConversationContextStore
from custom_components.ha_switchboard.conversation import (
    ConversationRequest,
    _candidate_reply,
    _confirmation_reply,
    _pending_request_payload,
    _response_text,
)


def test_context_is_user_bound_and_consumed_once():
    store = ConversationContextStore(ttl=10, clock=lambda: 100.0)
    store.put("conversation", "user-a", "confirmation", {"utterance": "unlock"})
    assert store.peek("conversation", "user-b") is None
    item = store.consume("conversation", "user-a")
    assert item is not None and item.kind == "confirmation"
    assert store.consume("conversation", "user-a") is None


def test_expired_context_cannot_authorize_follow_up():
    now = [100.0]
    store = ConversationContextStore(ttl=5, clock=lambda: now[0])
    store.put("conversation", "user-a", "clarification", {"utterance": "turn on lamp"})
    now[0] = 106.0
    assert store.peek("conversation", "user-a") is None


def test_context_store_evicts_oldest_entry_at_bound():
    now = [100.0]
    store = ConversationContextStore(ttl=10, max_entries=1, clock=lambda: now[0])
    store.put("first", "user", "parameter", {})
    now[0] += 1
    store.put("second", "user", "parameter", {})
    assert store.peek("first", "user") is None
    assert store.peek("second", "user") is not None


def test_context_store_rejects_raw_references_and_unbounded_nested_state():
    store = ConversationContextStore()
    try:
        store.put("conversation", "user", "confirmation", {"entity_id": "light.private"})
    except ValueError as exc:
        assert "Core-local" in str(exc)
    else:
        raise AssertionError("raw entity references must never enter continuation state")

    try:
        store.put("conversation", "user", "confirmation", {"nested": {"value": "x" * 2001}})
    except ValueError as exc:
        assert "too long" in str(exc)
    else:
        raise AssertionError("continuation text must be bounded")


def test_pending_request_payload_compacts_nested_profile_schemas():
    request = ConversationRequest(
        text="Set the fixture brightness",
        conversation_id="conversation",
        profile_revision="profile-1",
        candidates=(
            {
                "capability_id": "opaque-light",
                "display_name": "Fixture light: set brightness",
                "domain": "light",
                "operation": "set_brightness",
                "parameter_schema": {
                    "type": "object",
                    "properties": {
                        "brightness": {"type": "number", "minimum": 0, "maximum": 100},
                    },
                    "required": ["brightness"],
                },
            },
        ),
        bounded_context=({"organization": {"name": "local"}},),
        sanitized_state={"opaque-light": {"state": "on", "attributes": {"brightness": 50}}},
    )

    payload = _pending_request_payload(request)
    ConversationContextStore().put("conversation", None, "parameter", payload)

    assert payload["candidates"] == [{
        "capability_id": "opaque-light",
        "display_name": "Fixture light: set brightness",
        "domain": "light",
        "operation": "set_brightness",
    }]
    assert payload["bounded_context"] == []
    assert payload["sanitized_state"] == {}


def test_confirmation_and_clarification_replies_accept_voice_punctuation_only():
    assert _confirmation_reply("Yes, please.") is True
    assert _confirmation_reply("NO!") is False
    assert _confirmation_reply("maybe") is None
    assert _candidate_reply("#2.") == "2"
    assert _candidate_reply("Kitchen lights") == "kitchen lights"


def test_response_text_never_returns_the_prohibited_generic_refusal():
    for value in (
        "I could not safely complete that request.",
        "I couldn't safely complete that request because of a provider error.",
        "Before that, I could not complete that request.",
    ):
        rendered = _response_text({"text": value, "response_key": "execution_failed"})
        assert "could not safely complete that request" not in rendered.casefold()
        assert "couldn't safely complete that request" not in rendered.casefold()


def test_response_mapping_replaces_prohibited_generic_failure_text():
    prohibited = "I could not safely complete that request."
    for response_key in ("execution_failed", "batch_partial_failure", "candidate_not_allowed"):
        text = _response_text({"response_key": response_key, "text": prohibited})
        assert prohibited.casefold() not in text.casefold()
    assert _response_text({"response_key": "confirmation_required"}).startswith("This action needs your confirmation")


def test_confirmation_continuation_is_user_bound_and_consumed_before_gateway_retry():
    class Client:
        def __init__(self):
            self.payload = None

        async def process(self, payload):
            self.payload = payload
            return {"kind": "answer", "response_key": "execute_verified"}

    from custom_components.ha_switchboard.conversation import JevConversationEntity

    async def run():
        client = Client()
        store = ConversationContextStore()
        store.put(
            "conversation",
            "user-a",
            "confirmation",
            {
                "request_id": "request-1",
                "conversation_id": "conversation",
                "utterance": "unlock the front door",
                "language": "en",
                "profile_revision": "profile-1",
                "candidates": [{"capability_id": "opaque-lock", "display_name": "Front door"}],
                "bounded_context": [],
                "sanitized_state": {},
            },
        )
        entity = JevConversationEntity(client, context_store=store)
        result = await entity._async_handle_message(
            SimpleNamespace(
                text="yes please",
                conversation_id="conversation",
                language="en",
                context=SimpleNamespace(user_id="user-a"),
            ),
            SimpleNamespace(),
        )
        assert result["response_key"] == "execute_verified"
        assert client.payload["request_id"] == "request-1"
        assert client.payload["sanitized_state"]["confirmation"] is True
        assert store.peek("conversation", "user-a") is None
        assert any(event["code"] == "continuation_accepted" for event in entity.diagnostics.list())

    asyncio.run(run())


def test_clarification_continuation_accepts_only_an_offered_display_name():
    class Client:
        def __init__(self):
            self.payload = None

        async def process(self, payload):
            self.payload = payload
            return {"kind": "execute", "response_key": "execute_verified"}

    from custom_components.ha_switchboard.conversation import JevConversationEntity

    async def run():
        client = Client()
        store = ConversationContextStore()
        store.put(
            "conversation",
            "user-a",
            "clarification",
            {
                "request_id": "request-2",
                "conversation_id": "conversation",
                "utterance": "turn on the lamp",
                "language": "en",
                "profile_revision": "profile-1",
                "candidates": [
                    {"capability_id": "opaque-kitchen", "display_name": "Kitchen lamp"},
                    {"capability_id": "opaque-office", "display_name": "Office lamp"},
                ],
                "bounded_context": [],
                "sanitized_state": {},
            },
        )
        entity = JevConversationEntity(client, context_store=store)
        result = await entity._async_handle_message(
            SimpleNamespace(
                text="Kitchen lamp",
                conversation_id="conversation",
                language="en",
                context=SimpleNamespace(user_id="user-a"),
            ),
            SimpleNamespace(),
        )
        assert result["response_key"] == "execute_verified"
        assert client.payload["candidates"] == [{"capability_id": "opaque-kitchen", "display_name": "Kitchen lamp"}]
        assert store.peek("conversation", "user-a") is None

    asyncio.run(run())
