from __future__ import annotations

from ha_switchboard.batch import build_batch_group
from ha_switchboard.gateway import Gateway, GatewayConfig
from ha_switchboard.handoff import HandoffBroker
from ha_switchboard.jev_client import JevUnavailable, StaticJevClient
from ha_switchboard.protocol import Complexity, JevDecision, ModelRoute, PrivacyMode, ResponseKind, ResultKind, RouteKind
from ha_switchboard.route_policy import RouteRegistry, select_route
from ha_switchboard.server import build_gateway
from ha_switchboard.store import ProfileStore


class FailingJev:
    hosted = False

    def decide(self, request):
        raise JevUnavailable("temporary failure")


class RouteAdapter:
    def __init__(self, kind: str, choice: str | None = None):
        self.kind = kind
        self.choice = choice
        self.calls = 0

    def invoke(self, route, request):
        self.calls += 1
        if self.kind == "prose_response":
            return {"handoff_id": request.handoff_id, "kind": "prose_response", "text": "Please name a room."}
        return {
            "handoff_id": request.handoff_id,
            "kind": "tool_proposal",
            "proposals": [{"capability_id": self.choice, "parameter_refs": [], "reason": "bounded match"}],
        }


class ParameterRouteAdapter(RouteAdapter):
    def invoke(self, route, request):
        self.calls += 1
        return {
            "handoff_id": request.handoff_id,
            "route_id": route.route_id,
            "kind": "tool_proposal",
            "proposals": [{
                "capability_id": request.relevant_facts[0]["capability_id"],
                "parameter_refs": [],
                "parameters": {"brightness": 42},
                "reason": "bounded match",
            }],
        }


def _routes(*, hosted: bool = False):
    route = ModelRoute(
        route_id="fallback", kind="typed_http",
        response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
        complexity_ceiling=Complexity.REASONING,
        privacy_modes=(PrivacyMode.HOSTED_ALLOWED,) if hosted else tuple(PrivacyMode),
        latency_budget_ms=1000, cost_ceiling=0,
    )
    return RouteRegistry((route,))


def _request(gateway, utterance: str, request_id: str = "request-batch"):
    return {
        "request_id": request_id, "conversation_id": "conversation-batch", "utterance": utterance,
        "language": "en", "profile_revision": gateway.active_profile.revision,
        "policy_revision": "policy-1", "candidates": [], "sanitized_state": {},
    }


def test_jev_clarification_can_handoff_to_bounded_batch_proposal(tmp_path, sanitized_discovery):
    adapter = RouteAdapter("tool_proposal")
    routes = _routes()
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.CLARIFY, Complexity.SIMPLE)),
        routes=routes, handoff=HandoffBroker(routes, adapter),
    )
    gateway.reconcile(sanitized_discovery)
    adapter.choice = build_batch_group("Turn all the lights on", gateway.active_profile).group_id

    result = gateway.process(_request(gateway, "Turn all the lights on"))

    assert result.kind is ResultKind.EXECUTE
    assert result.response_key == "batch_execute"
    assert len(result.capability_ids) == 2
    assert adapter.calls == 1


def test_jev_failure_handoffs_to_prose_but_hosted_privacy_still_blocks(tmp_path, sanitized_discovery):
    adapter = RouteAdapter("prose_response")
    routes = _routes(hosted=True)
    gateway = Gateway(
        store=ProfileStore(tmp_path), jev=FailingJev(), routes=routes,
        handoff=HandoffBroker(routes, adapter),
        config=GatewayConfig(privacy_mode=PrivacyMode.JEV_HOSTED_ALLOWED),
    )
    gateway.reconcile(sanitized_discovery)

    blocked = gateway.process(_request(gateway, "What can you do?", "blocked"))
    assert blocked.response_key == "route_not_allowed"
    assert adapter.calls == 0

    gateway.config = GatewayConfig(privacy_mode=PrivacyMode.HOSTED_ALLOWED)
    answered = gateway.process(_request(gateway, "What can you do?", "allowed"))
    assert answered.response_key == "delegated_prose"
    assert answered.text == "Please name a room."
    assert adapter.calls == 1


def test_fallback_cannot_invent_a_batch_group(tmp_path, sanitized_discovery):
    adapter = RouteAdapter("tool_proposal", "batch-invented")
    routes = _routes()
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.CLARIFY, Complexity.SIMPLE)),
        routes=routes, handoff=HandoffBroker(routes, adapter),
    )
    gateway.reconcile(sanitized_discovery)

    result = gateway.process(_request(gateway, "Turn all the lights on"))

    assert result.kind is ResultKind.REFUSE
    assert result.response_key == "fallback_target_unverified"


def test_server_builds_configurable_openrouter_or_typed_http_fallback(monkeypatch, tmp_path):
    from ha_switchboard import server
    from ha_switchboard.handoff import HttpRouteAdapter
    from ha_switchboard.openrouter_fallback import OpenRouterFallbackAdapter

    common = {"jev_endpoint": "", "privacy_mode": "local_only"}
    monkeypatch.setattr(server, "_load_options", lambda _path: {
        **common, "fallback_provider": "openrouter", "fallback_model": "test/model",
    })
    openrouter = build_gateway(str(tmp_path))
    assert isinstance(openrouter.handoff.adapter, OpenRouterFallbackAdapter)
    assert openrouter.routes.routes[0].privacy_modes == (PrivacyMode.HOSTED_ALLOWED,)

    monkeypatch.setattr(server, "_load_options", lambda _path: {
        **common, "fallback_provider": "typed_http", "fallback_endpoint": "http://localhost:8090/decide",
    })
    local = build_gateway(str(tmp_path))
    assert isinstance(local.handoff.adapter, HttpRouteAdapter)
    assert PrivacyMode.LOCAL_ONLY in local.routes.routes[0].privacy_modes


def test_open_circuit_skips_primary_route_for_failover() -> None:
    routes = RouteRegistry.from_dict({"routes": [
        {"route_id": "primary", "response_kinds": ["prose_response"], "complexity_ceiling": "reasoning", "privacy_modes": ["local_only"], "latency_budget_ms": 100},
        {"route_id": "secondary", "response_kinds": ["prose_response"], "complexity_ceiling": "reasoning", "privacy_modes": ["local_only"], "latency_budget_ms": 100},
    ]})
    routes.record_failure("primary")
    routes.record_failure("primary")
    selected = select_route(routes, complexity=Complexity.SIMPLE, privacy_mode=PrivacyMode.LOCAL_ONLY,
                            required_response=ResponseKind.PROSE_RESPONSE, max_latency_ms=500, max_cost=1)
    assert selected.route_id == "secondary"


def test_delegated_typed_parameters_reenter_gateway_validation(tmp_path, sanitized_discovery):
    adapter = ParameterRouteAdapter("tool_proposal")
    routes = _routes()
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.CLARIFY, Complexity.SIMPLE)),
        routes=routes,
        handoff=HandoffBroker(routes, adapter),
    )
    gateway.reconcile(sanitized_discovery)
    capability = next(item for item in gateway.active_profile.capabilities if item.operation == "set_brightness")
    result = gateway.process({
        **_request(gateway, "Set the living room lights brightness to 42 percent", "parameterized"),
        "candidates": [{
            "capability_id": capability.capability_id,
            "display_name": capability.display_name,
            "domain": capability.domain,
            "operation": capability.operation,
            "parameter_schema": capability.parameter_schema,
        }],
    })
    assert result.kind is ResultKind.EXECUTE
    assert result.parameters == {"brightness": 42.0}


def test_missing_jev_parameters_use_eligible_fallback(tmp_path, sanitized_discovery):
    adapter = ParameterRouteAdapter("tool_proposal")
    routes = _routes()
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE)),
        routes=routes,
        handoff=HandoffBroker(routes, adapter),
    )
    gateway.reconcile(sanitized_discovery)
    capability = next(item for item in gateway.active_profile.capabilities if item.operation == "set_brightness")
    gateway.jev = StaticJevClient(JevDecision(
        RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, capability.capability_id, 0.99, 0.01,
    ))
    result = gateway.process({
        **_request(gateway, "Set the living room lights brightness to 42 percent", "jev-missing-parameter"),
        "candidates": [{
            "capability_id": capability.capability_id,
            "display_name": capability.display_name,
            "domain": capability.domain,
            "operation": capability.operation,
            "parameter_schema": capability.parameter_schema,
        }],
    })
    assert result.kind is ResultKind.EXECUTE
    assert result.response_key == "execute"
    assert result.parameters == {"brightness": 42.0}
    assert adapter.calls == 1


def test_delegated_out_of_range_parameter_is_refused(tmp_path, sanitized_discovery):
    class BadParameterAdapter(ParameterRouteAdapter):
        def invoke(self, route, request):
            response = super().invoke(route, request)
            response["proposals"][0]["parameters"]["brightness"] = 101
            return response

    adapter = BadParameterAdapter("tool_proposal")
    routes = _routes()
    gateway = Gateway(
        store=ProfileStore(tmp_path),
        jev=StaticJevClient(JevDecision(RouteKind.CLARIFY, Complexity.SIMPLE)),
        routes=routes,
        handoff=HandoffBroker(routes, adapter),
    )
    gateway.reconcile(sanitized_discovery)
    capability = next(item for item in gateway.active_profile.capabilities if item.operation == "set_brightness")
    result = gateway.process({
        **_request(gateway, "Set the living room lights brightness to 101 percent", "parameterized-invalid"),
        "candidates": [{
            "capability_id": capability.capability_id,
            "display_name": capability.display_name,
            "domain": capability.domain,
            "operation": capability.operation,
            "parameter_schema": capability.parameter_schema,
        }],
    })
    assert result.kind is ResultKind.REFUSE
    assert result.response_key == "invalid_parameters"
