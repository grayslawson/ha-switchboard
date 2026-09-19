"""Decision gateway: Jev and downstream brokers, never Home Assistant execution."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from .change_monitor import ChangeMonitor
from .handoff import HandoffBroker, HandoffError, HandoffInvalidResponse
from .jev_client import JevClient, JevError
from .policy import PolicyConfig, evaluate_capability, validate_parameters
from .profile import ProfileCompiler, mark_sections_stale
from .protocol import (
    Complexity,
    DecisionRequest,
    DecisionResult,
    HandoffRequest,
    HomeProfile,
    LifecycleStatus,
    PrivacyMode,
    ResultKind,
    ResponseKind,
    RouteKind,
    SectionId,
)
from .redaction import SensitiveDataError, sanitize_for_gateway, sanitize_state
from .route_policy import RoutePolicyError, RouteRegistry, select_route
from .store import ProfileStore


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_ONLY
    max_request_bytes: int = 64_000


class Gateway:
    def __init__(
        self,
        *,
        store: ProfileStore,
        jev: JevClient,
        routes: RouteRegistry | None = None,
        handoff: HandoffBroker | None = None,
        config: GatewayConfig = GatewayConfig(),
    ) -> None:
        self.store = store
        self.jev = jev
        self.routes = routes or RouteRegistry()
        self.handoff = handoff
        self.config = config
        self.compiler = ProfileCompiler()
        self.monitor = ChangeMonitor(compiler=self.compiler)
        self.active_profile: HomeProfile | None = None
        self._seen_requests: dict[str, DecisionResult] = {}
        self._restore_profile()

    def _restore_profile(self) -> None:
        """Restore only a stale profile; a restart must reconcile before writes."""

        stored = self.store.load_profile()
        if stored is None:
            return
        try:
            restored = HomeProfile.from_dict(stored)
            self.active_profile = mark_sections_stale(
                restored,
                set(SectionId),
                "gateway_restart",
            )
            self.monitor.active_profile = self.active_profile
            self.monitor.ingest({"kind": "restart"})
        except (KeyError, TypeError, ValueError):
            # Corrupt or incompatible persisted state is fail-closed. The
            # adapter must provide a complete replacement profile.
            self.active_profile = None

    def health(self) -> dict[str, str]:
        return {"status": "ok", "service": "ha-switchboard-gateway"}

    def ready(self) -> dict[str, Any]:
        profile_ready = self.active_profile is not None and self.active_profile.status is LifecycleStatus.ACTIVE
        monitor = self.monitor.status()
        return {
            "status": "ready" if profile_ready and not monitor["pending_sections"] else "degraded",
            "profile_ready": profile_ready,
            "monitor": monitor,
            "jev_configured": self.jev.__class__.__name__ != "StaticJevClient",
        }

    def reconcile(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        try:
            clean = sanitize_for_gateway(snapshot)
        except SensitiveDataError as exc:
            raise ValueError("profile snapshot contains a forbidden field") from exc
        profile = self.monitor.reconcile(clean)
        self.active_profile = profile
        self.store.save_profile(profile)
        return self.profile_status()

    def invalidate(self, event: Mapping[str, Any]) -> dict[str, Any]:
        sections = self.monitor.ingest(event)
        if self.active_profile is not None and sections:
            self.active_profile = mark_sections_stale(
                self.active_profile,
                set(sections),
                str(event.get("event_type", event.get("kind", "source_changed"))),
            )
            self.monitor.active_profile = self.active_profile
            self.store.save_profile(self.active_profile)
        return self.profile_status()

    def profile_status(self) -> dict[str, Any]:
        profile = self.active_profile
        monitor_status = self.monitor.status()
        return {
            "profile_revision": profile.revision if profile else None,
            "profile_id": profile.profile_id if profile else None,
            "status": profile.status.value if profile else "disabled",
            "last_reconciled_at": profile.last_reconciled_at if profile else None,
            "monitor": monitor_status,
            "sections": monitor_status.get("sections", {}),
            "capability_count": len(profile.capabilities) if profile else 0,
        }

    def process(self, payload: Mapping[str, Any]) -> DecisionResult:
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        if request_id in self._seen_requests:
            return self._seen_requests[request_id]
        try:
            clean_payload = sanitize_for_gateway(payload)
            request = DecisionRequest.from_dict(clean_payload)
        except (ValueError, SensitiveDataError) as exc:
            result = self._refusal(request_id, "invalid_request", str(exc))
            return self._remember(result)
        profile = self.active_profile
        if profile is None:
            return self._remember(self._refusal(request.request_id, "profile_stale", "no active profile"))
        if request.profile_revision != profile.revision:
            return self._remember(self._refusal(request.request_id, "profile_stale", "profile revision mismatch"))
        if profile.status is not LifecycleStatus.ACTIVE or self.monitor.pending_sections:
            return self._remember(self._refusal(request.request_id, "profile_reconciling", "profile is not current"))
        try:
            decision = self.jev.decide(request)
        except JevError as exc:
            return self._remember(self._refusal(request.request_id, exc.code, "Jev decision unavailable"))
        except Exception:
            return self._remember(self._refusal(request.request_id, "jev_invalid_response", "Jev decision failed"))

        if decision.route is RouteKind.CLARIFY:
            return self._remember(self._result(request, ResultKind.CLARIFY, "clarification_required", decision=decision))
        if decision.route is RouteKind.REFUSE:
            return self._remember(self._result(request, ResultKind.REFUSE, "request_refused", decision=decision))
        if decision.route is RouteKind.READ_ONLY:
            return self._remember(self._result(request, ResultKind.ANSWER, "read_only_answer", decision=decision))
        if decision.route is RouteKind.ROUTINE_CONTROL:
            return self._remember(self._evaluate_execution(request, decision))
        if decision.route is RouteKind.DELEGATE:
            return self._remember(self._delegate(request, decision))
        return self._remember(self._refusal(request.request_id, "jev_invalid_response", "unsupported route"))

    def _evaluate_execution(self, request: DecisionRequest, decision) -> DecisionResult:
        assert self.active_profile is not None
        policy = evaluate_capability(
            self.active_profile,
            decision.capability_id,
            confidence=decision.confidence,
            ambiguity=decision.ambiguity,
            confirmed=bool(request.sanitized_state.get("confirmation", False)),
            config=self.config.policy,
        )
        if policy.needs_confirmation:
            return self._result(request, ResultKind.CONFIRM, policy.response_key, decision=decision)
        if not policy.allowed:
            result_kind = ResultKind.CLARIFY if policy.response_key in {"ambiguous_request", "confidence_too_low"} else ResultKind.REFUSE
            return self._result(request, result_kind, policy.response_key, decision=decision)
        return self._result(request, ResultKind.EXECUTE, "execute", decision=decision)

    def _delegate(self, request: DecisionRequest, decision) -> DecisionResult:
        try:
            try:
                route = select_route(
                    self.routes,
                    complexity=decision.complexity,
                    privacy_mode=request.privacy_mode,
                    required_response=ResponseKind.PROSE_RESPONSE,
                    max_latency_ms=self.config.policy.max_latency_ms,
                    max_cost=self.config.policy.max_cost,
                    policy=self.config.policy,
                )
            except RoutePolicyError:
                route = select_route(
                    self.routes,
                    complexity=decision.complexity,
                    privacy_mode=request.privacy_mode,
                    required_response=ResponseKind.TOOL_PROPOSAL,
                    max_latency_ms=self.config.policy.max_latency_ms,
                    max_cost=self.config.policy.max_cost,
                    policy=self.config.policy,
                )
        except RoutePolicyError:
            return self._result(request, ResultKind.REFUSE, "route_not_allowed", decision=decision)
        if request.handoff_depth:
            return self._result(request, ResultKind.REFUSE, "handoff_loop_detected", decision=decision)
        if self.handoff is None:
            return self._result(request, ResultKind.REFUSE, "handoff_unavailable", decision=decision)
        handoff_id = "handoff-" + hashlib.sha256(f"{request.request_id}:{route.route_id}".encode()).hexdigest()[:20]
        handoff_request = HandoffRequest(
            handoff_id=handoff_id,
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            utterance=request.utterance,
            bounded_context=request.bounded_context,
            relevant_facts=tuple(request.candidates[:8]),
            route_id=route.route_id,
            complexity=decision.complexity,
            reason=decision.reason or "jev_delegated",
            allowed_response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL),
            handoff_depth=1,
            route_policy_revision=self.routes.revision,
            privacy_mode=request.privacy_mode,
        )
        try:
            response = self.handoff.dispatch(handoff_request)
        except HandoffInvalidResponse:
            return self._result(request, ResultKind.REFUSE, "handoff_invalid_response", decision=decision, route_id=route.route_id, handoff_id=handoff_id)
        except HandoffError:
            return self._result(request, ResultKind.REFUSE, "handoff_unavailable", decision=decision, route_id=route.route_id, handoff_id=handoff_id)
        if response.kind is ResponseKind.PROSE_RESPONSE:
            return self._result(request, ResultKind.ANSWER, "delegated_prose", decision=decision, route_id=route.route_id, handoff_id=handoff_id, text=response.text)
        proposal = response.proposals[0]
        capability_id = proposal.get("capability_id")
        if not isinstance(capability_id, str):
            return self._result(request, ResultKind.REFUSE, "handoff_invalid_response", decision=decision, route_id=route.route_id, handoff_id=handoff_id)
        policy = evaluate_capability(
            self.active_profile,
            capability_id,
            confidence=1.0,
            ambiguity=0.0,
            confirmed=bool(request.sanitized_state.get("confirmation", False)),
            config=self.config.policy,
        )
        if policy.needs_confirmation:
            return self._result(request, ResultKind.CONFIRM, policy.response_key, decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id)
        if not policy.allowed:
            return self._result(request, ResultKind.REFUSE, policy.response_key, decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id)
        return self._result(request, ResultKind.EXECUTE, "execute", decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id)

    def _result(
        self,
        request: DecisionRequest,
        kind: ResultKind,
        response_key: str,
        *,
        decision=None,
        route_id: str | None = None,
        handoff_id: str | None = None,
        capability_id: str | None = None,
        text: str | None = None,
    ) -> DecisionResult:
        return DecisionResult(
            kind=kind,
            request_id=request.request_id,
            profile_revision=request.profile_revision,
            policy_revision=request.policy_revision,
            response_key=response_key,
            capability_id=capability_id or (decision.capability_id if decision else None),
            route_id=route_id,
            complexity=decision.complexity if decision else None,
            confidence=decision.confidence if decision else None,
            handoff_id=handoff_id,
            text=text,
        )

    def _refusal(self, request_id: str, code: str, reason: str) -> DecisionResult:
        return DecisionResult(
            kind=ResultKind.REFUSE,
            request_id=request_id,
            profile_revision=self.active_profile.revision if self.active_profile else "",
            policy_revision=self.config.policy.revision,
            response_key=code,
            error_code=code,
            text=reason[:256],
        )

    def _remember(self, result: DecisionResult) -> DecisionResult:
        self._seen_requests[result.request_id] = result
        if len(self._seen_requests) > 1_024:
            oldest = next(iter(self._seen_requests))
            del self._seen_requests[oldest]
        return result
