"""Semantic route registry and policy-constrained route selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .policy import PolicyConfig, route_allowed
from .protocol import Complexity, ModelRoute, PrivacyMode, ResponseKind


class RoutePolicyError(ValueError):
    """No configured route can satisfy the current envelope."""


@dataclass(frozen=True, slots=True)
class RouteRegistry:
    routes: tuple[ModelRoute, ...] = ()
    revision: str = "routes-1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RouteRegistry":
        values: list[ModelRoute] = []
        for item in payload.get("routes", ()):
            if not isinstance(item, Mapping):
                continue
            values.append(
                ModelRoute(
                    route_id=str(item["route_id"]),
                    kind=str(item.get("kind", "local_endpoint")),
                    response_kinds=tuple(ResponseKind(value) for value in item.get("response_kinds", ("prose_response",))),
                    complexity_ceiling=Complexity(item.get("complexity_ceiling", "simple")),
                    privacy_modes=tuple(PrivacyMode(value) for value in item.get("privacy_modes", ("local_only",))),
                    latency_budget_ms=int(item.get("latency_budget_ms", 2_000)),
                    cost_ceiling=float(item.get("cost_ceiling", 0)),
                    availability=str(item.get("availability", "ready")),
                    fallback_route_ids=tuple(str(value) for value in item.get("fallback_route_ids", ())),
                    revision=str(item.get("revision", payload.get("revision", "routes-1"))),
                )
            )
        if len(values) > 32:
            raise RoutePolicyError("route registry exceeds 32 routes")
        return cls(routes=tuple(values), revision=str(payload.get("revision", "routes-1")))

    def get(self, route_id: str) -> ModelRoute | None:
        return next((route for route in self.routes if route.route_id == route_id), None)


def select_route(
    registry: RouteRegistry,
    *,
    complexity: Complexity,
    privacy_mode: PrivacyMode,
    required_response: ResponseKind,
    max_latency_ms: int,
    max_cost: float,
    policy: PolicyConfig = PolicyConfig(),
) -> ModelRoute:
    """Choose the least costly eligible route; never accept a provider name from Jev."""

    candidates = [
        route
        for route in registry.routes
        if required_response in route.response_kinds
        and route_allowed(
            privacy_mode=privacy_mode,
            complexity=complexity,
            latency_ms=route.latency_budget_ms,
            cost=route.cost_ceiling,
            route_privacy_modes=frozenset(route.privacy_modes),
            route_complexity=route.complexity_ceiling,
            config=PolicyConfig(
                revision=policy.revision,
                allowed_domains=policy.allowed_domains,
                allowed_operations=policy.allowed_operations,
                high_risk_domains=policy.high_risk_domains,
                confidence_threshold=policy.confidence_threshold,
                ambiguity_threshold=policy.ambiguity_threshold,
                max_latency_ms=max_latency_ms,
                max_cost=max_cost,
            ),
        )
    ]
    if not candidates:
        raise RoutePolicyError("no compatible downstream route")
    return min(candidates, key=lambda route: (route.cost_ceiling, route.latency_budget_ms, route.route_id))


def compatible_failovers(registry: RouteRegistry, route: ModelRoute, privacy_mode: PrivacyMode) -> Iterable[ModelRoute]:
    for route_id in route.fallback_route_ids:
        candidate = registry.get(route_id)
        if candidate and privacy_mode in candidate.privacy_modes and candidate.availability in {"ready", "degraded"}:
            yield candidate
