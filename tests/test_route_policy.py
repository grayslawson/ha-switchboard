from __future__ import annotations

import pytest

from ha_switchboard.route_policy import RoutePolicyError, RouteRegistry, ordered_routes, select_route
from ha_switchboard.protocol import Complexity, PrivacyMode, ResponseKind


def test_local_only_route_is_selected() -> None:
    registry = RouteRegistry.from_dict(
        {
            "routes": [
                {
                    "route_id": "local",
                    "kind": "local_endpoint",
                    "response_kinds": ["prose_response"],
                    "complexity_ceiling": "reasoning",
                    "privacy_modes": ["local_only"],
                    "latency_budget_ms": 100,
                    "cost_ceiling": 0,
                },
                {
                    "route_id": "hosted",
                    "kind": "openai_compatible",
                    "response_kinds": ["prose_response"],
                    "complexity_ceiling": "reasoning",
                    "privacy_modes": ["hosted_allowed"],
                    "latency_budget_ms": 100,
                    "cost_ceiling": 0.01,
                },
            ]
        }
    )
    route = select_route(
        registry,
        complexity=Complexity.COMPLEX,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        required_response=ResponseKind.PROSE_RESPONSE,
        max_latency_ms=500,
        max_cost=1,
    )
    assert route.route_id == "local"


def test_incompatible_privacy_mode_has_no_silent_fallback() -> None:
    registry = RouteRegistry.from_dict(
        {
            "routes": [
                {
                    "route_id": "hosted",
                    "kind": "openai_compatible",
                    "response_kinds": ["prose_response"],
                    "complexity_ceiling": "reasoning",
                    "privacy_modes": ["hosted_allowed"],
                    "latency_budget_ms": 100,
                    "cost_ceiling": 0.01,
                }
            ]
        }
    )
    with pytest.raises(RoutePolicyError):
        select_route(
            registry,
            complexity=Complexity.SIMPLE,
            privacy_mode=PrivacyMode.LOCAL_ONLY,
            required_response=ResponseKind.PROSE_RESPONSE,
            max_latency_ms=500,
            max_cost=1,
        )


def test_disabled_route_is_not_selected_even_when_its_budget_matches() -> None:
    registry = RouteRegistry.from_dict({
        "routes": [{
            "route_id": "disabled",
            "availability": "disabled",
            "response_kinds": ["prose_response"],
            "complexity_ceiling": "reasoning",
            "privacy_modes": ["local_only"],
        }]
    })
    with pytest.raises(RoutePolicyError):
        select_route(
            registry,
            complexity=Complexity.SIMPLE,
            privacy_mode=PrivacyMode.LOCAL_ONLY,
            required_response=ResponseKind.PROSE_RESPONSE,
            max_latency_ms=500,
            max_cost=1,
        )


def test_declared_route_order_is_preserved_over_cost() -> None:
    registry = RouteRegistry.from_dict(
        {
            "schema_version": 1,
            "routes": [
                {
                    "route_id": "primary",
                    "response_kinds": ["prose_response"],
                    "complexity_ceiling": "reasoning",
                    "privacy_modes": ["local_only"],
                    "latency_budget_ms": 100,
                    "cost_ceiling": 0.50,
                },
                {
                    "route_id": "cheap-secondary",
                    "response_kinds": ["prose_response"],
                    "complexity_ceiling": "reasoning",
                    "privacy_modes": ["local_only"],
                    "latency_budget_ms": 100,
                    "cost_ceiling": 0.01,
                },
            ],
        }
    )
    selected = select_route(
        registry,
        complexity=Complexity.SIMPLE,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        required_response=ResponseKind.PROSE_RESPONSE,
        max_latency_ms=500,
        max_cost=1,
    )
    assert selected.route_id == "primary"


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "routes": []},
        {"routes": [{"route_id": "duplicate"}, {"route_id": "duplicate"}]},
        {"routes": [{"route_id": "bad", "cost_ceiling": float("inf")}]},
        {"routes": [{"route_id": "bad", "fallback_route_ids": ["missing"]}]},
    ],
)
def test_route_registry_rejects_incompatible_or_unsafe_definitions(payload) -> None:
    with pytest.raises(RoutePolicyError):
        RouteRegistry.from_dict(payload)


def test_route_registry_rejects_unknown_schema_duplicate_and_failover_targets() -> None:
    with pytest.raises(RoutePolicyError, match="schema version"):
        RouteRegistry.from_dict({"schema_version": 99, "routes": []})
    with pytest.raises(RoutePolicyError, match="unique"):
        RouteRegistry.from_dict({"routes": [{"route_id": "same"}, {"route_id": "same"}]})
    with pytest.raises(RoutePolicyError, match="unknown route"):
        RouteRegistry.from_dict({"routes": [{"route_id": "primary", "fallback_route_ids": ["missing"]}]})


def test_ordered_routes_preserves_explicit_failover_chain_and_skips_open_circuit() -> None:
    registry = RouteRegistry.from_dict({
        "routes": [
            {"route_id": "primary", "response_kinds": ["prose_response"], "complexity_ceiling": "reasoning", "privacy_modes": ["local_only"], "fallback_route_ids": ["secondary"]},
            {"route_id": "secondary", "response_kinds": ["prose_response"], "complexity_ceiling": "reasoning", "privacy_modes": ["local_only"], "fallback_route_ids": ["tertiary"]},
            {"route_id": "tertiary", "response_kinds": ["prose_response"], "complexity_ceiling": "reasoning", "privacy_modes": ["local_only"]},
        ]
    })
    registry.record_failure("primary")
    registry.record_failure("primary")
    ordered = ordered_routes(
        registry,
        registry.get("primary"),
        complexity=Complexity.SIMPLE,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        required_response=ResponseKind.PROSE_RESPONSE,
        max_latency_ms=10_000,
        max_cost=1,
    )
    assert [route.route_id for route in ordered] == ["secondary", "tertiary"]


def test_ordered_routes_skips_failovers_outside_latency_and_cost_budgets() -> None:
    registry = RouteRegistry.from_dict({
        "routes": [
            {
                "route_id": "primary",
                "response_kinds": ["prose_response"],
                "complexity_ceiling": "reasoning",
                "privacy_modes": ["local_only"],
                "latency_budget_ms": 100,
                "cost_ceiling": 0.01,
                "fallback_route_ids": ["too-slow", "too-expensive", "eligible"],
            },
            {
                "route_id": "too-slow",
                "response_kinds": ["prose_response"],
                "complexity_ceiling": "reasoning",
                "privacy_modes": ["local_only"],
                "latency_budget_ms": 2_000,
                "cost_ceiling": 0,
            },
            {
                "route_id": "too-expensive",
                "response_kinds": ["prose_response"],
                "complexity_ceiling": "reasoning",
                "privacy_modes": ["local_only"],
                "latency_budget_ms": 100,
                "cost_ceiling": 2,
            },
            {
                "route_id": "eligible",
                "response_kinds": ["prose_response"],
                "complexity_ceiling": "reasoning",
                "privacy_modes": ["local_only"],
                "latency_budget_ms": 500,
                "cost_ceiling": 0.1,
            },
        ]
    })

    ordered = ordered_routes(
        registry,
        registry.get("primary"),
        complexity=Complexity.SIMPLE,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        required_response=ResponseKind.PROSE_RESPONSE,
        max_latency_ms=500,
        max_cost=0.5,
    )

    assert [route.route_id for route in ordered] == ["primary", "eligible"]


def test_ordered_routes_accepts_any_allowed_response_kind() -> None:
    registry = RouteRegistry.from_dict({
        "routes": [{
            "route_id": "proposal-only",
            "response_kinds": ["tool_proposal"],
            "complexity_ceiling": "reasoning",
            "privacy_modes": ["local_only"],
        }]
    })
    ordered = ordered_routes(
        registry,
        registry.get("proposal-only"),
        complexity=Complexity.SIMPLE,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        required_response=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
        max_latency_ms=10_000,
        max_cost=1,
    )
    assert [route.route_id for route in ordered] == ["proposal-only"]
