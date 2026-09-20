"""Semantic route registry and policy-constrained route selection."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any, Iterable, Mapping

from .policy import PolicyConfig, route_allowed
from .protocol import Complexity, ModelRoute, PrivacyMode, ResponseKind


ROUTE_REGISTRY_SCHEMA_VERSION = 1
SUPPORTED_ROUTE_SCHEMA_VERSIONS = frozenset({1})


class RoutePolicyError(ValueError):
    """No configured route can satisfy the current envelope."""


@dataclass(slots=True)
class CircuitState:
    """Small in-memory breaker; provider health is never persisted as truth."""

    failures: int = 0
    opened_until: float = 0.0
    threshold: int = 2
    cooldown: float = 30.0

    def available(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) >= self.opened_until

    def failure(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_until = current + self.cooldown

    def success(self) -> None:
        self.failures = 0
        self.opened_until = 0.0


@dataclass(frozen=True, slots=True)
class RouteRegistry:
    routes: tuple[ModelRoute, ...] = ()
    revision: str = "routes-1"
    schema_version: int = ROUTE_REGISTRY_SCHEMA_VERSION
    circuits: dict[str, CircuitState] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RouteRegistry":
        if not isinstance(payload, Mapping):
            raise RoutePolicyError("route registry must be an object")
        schema_version = payload.get("schema_version", ROUTE_REGISTRY_SCHEMA_VERSION)
        if isinstance(schema_version, bool) or schema_version not in SUPPORTED_ROUTE_SCHEMA_VERSIONS:
            raise RoutePolicyError("unsupported route registry schema version")
        revision = payload.get("revision", "routes-1")
        if not isinstance(revision, str) or not revision.strip() or len(revision) > 128:
            raise RoutePolicyError("route registry revision is invalid")
        raw_routes = payload.get("routes", ())
        if not isinstance(raw_routes, (list, tuple)):
            raise RoutePolicyError("route registry routes must be a list")
        values: list[ModelRoute] = []
        route_ids: set[str] = set()
        for item in raw_routes:
            if not isinstance(item, Mapping):
                raise RoutePolicyError("route entry must be an object")
            route_id = item.get("route_id")
            if not isinstance(route_id, str) or not route_id.strip() or len(route_id) > 128:
                raise RoutePolicyError("route id is invalid")
            if route_id in route_ids:
                raise RoutePolicyError("route ids must be unique")
            route_ids.add(route_id)
            route_schema = item.get("schema_version", ROUTE_REGISTRY_SCHEMA_VERSION)
            if isinstance(route_schema, bool) or route_schema not in SUPPORTED_ROUTE_SCHEMA_VERSIONS:
                raise RoutePolicyError("unsupported route schema version")
            try:
                response_kinds = tuple(ResponseKind(value) for value in item.get("response_kinds", ("prose_response",)))
                privacy_modes = tuple(PrivacyMode(value) for value in item.get("privacy_modes", ("local_only",)))
                latency = int(item.get("latency_budget_ms", 2_000))
                cost = float(item.get("cost_ceiling", 0))
                complexity = Complexity(item.get("complexity_ceiling", "simple"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise RoutePolicyError("route capability or budget is invalid") from exc
            if not response_kinds or not privacy_modes:
                raise RoutePolicyError("route must declare response and privacy capabilities")
            if latency < 0 or latency > 120_000 or not math.isfinite(cost) or cost < 0:
                raise RoutePolicyError("route budget is invalid")
            fallbacks = item.get("fallback_route_ids", ())
            if not isinstance(fallbacks, (list, tuple)) or len(fallbacks) > 8:
                raise RoutePolicyError("route failover list is invalid")
            route_revision = item.get("revision", revision)
            if not isinstance(route_revision, str) or not route_revision.strip() or len(route_revision) > 128:
                raise RoutePolicyError("route revision is invalid")
            values.append(
                ModelRoute(
                    route_id=route_id,
                    kind=str(item.get("kind", "local_endpoint")),
                    response_kinds=response_kinds,
                    complexity_ceiling=complexity,
                    privacy_modes=privacy_modes,
                    latency_budget_ms=latency,
                    cost_ceiling=cost,
                    availability=str(item.get("availability", "ready")),
                    fallback_route_ids=tuple(str(value) for value in fallbacks),
                    revision=route_revision,
                    schema_version=int(route_schema),
                )
            )
        if len(values) > 32:
            raise RoutePolicyError("route registry exceeds 32 routes")
        for route in values:
            if any(target not in route_ids for target in route.fallback_route_ids):
                raise RoutePolicyError("route failover references an unknown route")
            if route.route_id in route.fallback_route_ids:
                raise RoutePolicyError("route cannot fail over to itself")
        return cls(
            routes=tuple(values),
            revision=revision,
            schema_version=int(schema_version),
        )

    def get(self, route_id: str) -> ModelRoute | None:
        return next((route for route in self.routes if route.route_id == route_id), None)

    def circuit(self, route_id: str) -> CircuitState:
        return self.circuits.setdefault(route_id, CircuitState())

    def record_failure(self, route_id: str) -> None:
        self.circuit(route_id).failure()

    def record_success(self, route_id: str) -> None:
        self.circuit(route_id).success()

    def circuit_allows(self, route_id: str) -> bool:
        return self.circuit(route_id).available()


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
        and registry.circuit_allows(route.route_id)
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
    # Registry order is the operator's failover order. Cost/latency are
    # eligibility constraints, not permission for the gateway to reorder the
    # configured provider chain.
    return candidates[0]


def ordered_routes(
    registry: RouteRegistry,
    route: ModelRoute,
    *,
    complexity: Complexity,
    privacy_mode: PrivacyMode,
    required_response: ResponseKind | tuple[ResponseKind, ...],
    max_latency_ms: int,
    max_cost: float,
    policy: PolicyConfig = PolicyConfig(),
) -> tuple[ModelRoute, ...]:
    """Return a bounded, declaration-ordered primary/failover chain.

    Failover is an explicit graph, never an implicit provider sweep.  This
    preserves the operator's order and prevents a degraded route from
    silently widening privacy or cost policy.
    """

    result: list[ModelRoute] = []
    required_responses = (required_response,) if isinstance(required_response, ResponseKind) else required_response
    visited: set[str] = set()
    pending = [route]
    while pending and len(result) < 8:
        candidate = pending.pop(0)
        if candidate.route_id in visited:
            continue
        visited.add(candidate.route_id)
        if (
            any(kind in candidate.response_kinds for kind in required_responses)
            and candidate.supports(complexity, privacy_mode)
            and registry.circuit_allows(candidate.route_id)
            and route_allowed(
                privacy_mode=privacy_mode,
                complexity=complexity,
                latency_ms=candidate.latency_budget_ms,
                cost=candidate.cost_ceiling,
                route_privacy_modes=frozenset(candidate.privacy_modes),
                route_complexity=candidate.complexity_ceiling,
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
        ):
            result.append(candidate)
        for route_id in candidate.fallback_route_ids:
            fallback = registry.get(route_id)
            if fallback is not None and fallback.route_id not in visited:
                pending.append(fallback)
    return tuple(result)


def compatible_failovers(
    registry: RouteRegistry,
    route: ModelRoute,
    privacy_mode: PrivacyMode,
    *,
    complexity: Complexity = Complexity.SIMPLE,
    required_response: ResponseKind | tuple[ResponseKind, ...] = ResponseKind.PROSE_RESPONSE,
) -> Iterable[ModelRoute]:
    """Compatibility wrapper yielding explicit failovers in declaration order."""

    for candidate in ordered_routes(
        registry,
        route,
        complexity=complexity,
        privacy_mode=privacy_mode,
        required_response=required_response,
        max_latency_ms=120_000,
        max_cost=float("inf"),
    ):
        if candidate.route_id != route.route_id:
            yield candidate
