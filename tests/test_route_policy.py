from __future__ import annotations

import pytest

from ha_switchboard.route_policy import RoutePolicyError, RouteRegistry, select_route
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
