"""Unit tests for the Core-local native conversation boundary."""

import ast
import inspect
import textwrap
from types import SimpleNamespace

from custom_components.ha_switchboard.native_path import (
    is_routine_native_intent,
    native_intent_filter,
)


def _recognized(name, **slots):
    return SimpleNamespace(
        intent=SimpleNamespace(name=name),
        entities={key: SimpleNamespace(value=value) for key, value in slots.items()},
    )


def test_routine_turn_intent_requires_a_safe_explicit_domain():
    assert is_routine_native_intent(_recognized("HassTurnOn", domain="light", area="kitchen"))
    assert is_routine_native_intent(_recognized("HassTurnOff", domain=["light", "fan"]))
    assert not is_routine_native_intent(_recognized("HassTurnOn", area="kitchen"))
    assert not is_routine_native_intent(_recognized("HassTurnOn", domain="lock"))


def test_light_set_is_native_but_risky_or_unknown_intents_are_not():
    assert is_routine_native_intent(_recognized("HassLightSet", area="kitchen"))
    assert is_routine_native_intent(_recognized("HassToggle", domain="switch"))
    assert not is_routine_native_intent(_recognized("HassOpenCover", domain="cover"))
    assert not is_routine_native_intent(_recognized("CustomIntent", domain="light"))


def test_home_assistant_filter_rejects_only_non_routine_intents():
    assert not native_intent_filter(_recognized("HassTurnOn", domain="light"))
    assert native_intent_filter(_recognized("HassTurnOn", domain="cover"))


def test_native_miss_falls_through_to_the_normal_gateway_path():
    """Keep a native miss out of the bypass and on the Switchboard route."""

    # A recognized but unsupported native target must be offered to the
    # normal route instead of being treated as a handled native request.
    assert native_intent_filter(_recognized("HassTurnOn", domain="cover"))

    from custom_components.ha_switchboard.conversation import JevConversationEntity

    method = ast.parse(
        textwrap.dedent(inspect.getsource(JevConversationEntity._async_handle_message))
    ).body[0]
    native_call_lines = [
        node.lineno
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_async_native_fast_path"
    ]
    gateway_call_lines = [
        node.lineno
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_async_process_gateway"
    ]
    native_return_guard = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "native_response"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.IsNot)
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value is None
    ]

    assert len(native_call_lines) == 1
    assert gateway_call_lines
    assert len(native_return_guard) == 1
    assert any(isinstance(statement, ast.Return) for statement in native_return_guard[0].body)
    assert any(line > native_return_guard[0].lineno for line in gateway_call_lines)
