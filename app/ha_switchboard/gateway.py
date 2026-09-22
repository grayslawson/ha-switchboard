"""Decision gateway: Jev and downstream brokers, never Home Assistant execution."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .batch import BatchGroup, BatchRequestError, build_batch_group
from .change_monitor import ChangeMonitor
from .diagnostics import DiagnosticLog
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
    JevDecision,
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
        self.diagnostics = DiagnosticLog()
        self.active_profile: HomeProfile | None = None
        self._seen_requests: dict[str, DecisionResult] = {}
        self._provider_state: dict[str, dict[str, Any]] = {
            "jev": {
                "status": "configured" if self._jev_configured() else "disabled",
                "failures": 0,
                "error_code": None,
            }
        }
        self.configuration_warnings: tuple[str, ...] = ()
        self._restore_profile()

    def _jev_configured(self) -> bool:
        return self.jev.__class__.__name__ != "StaticJevClient"

    def _provider_event(self, status: str, *, error_code: str | None = None) -> None:
        state = self._provider_state["jev"]
        previous = state["status"]
        if status == "healthy":
            state["failures"] = 0
        elif status in {"unavailable", "degraded"}:
            state["failures"] = int(state.get("failures", 0)) + 1
        state["status"] = status
        state["error_code"] = error_code
        if status == previous and status not in {"healthy", "unavailable", "degraded"}:
            return
        event_code = (
            "provider_recovered"
            if status == "healthy" and previous in {"unavailable", "degraded"}
            else "provider_failed"
            if status in {"unavailable", "degraded"}
            else "provider_state"
        )
        summary = (
            "Provider recovered"
            if status == "healthy"
            else "Provider unavailable"
            if status == "unavailable"
            else "Provider state changed"
        )
        self.diagnostics.record(
            event_code,
            level="info" if status == "healthy" else "warning",
            route_class="jev",
            outcome=status,
            error_code=error_code or "none",
            summary=summary,
        )

    def _restore_profile(self) -> None:
        """Restore only a stale profile; a restart must reconcile before writes."""

        try:
            stored = self.store.load_profile()
        except (OSError, TypeError, ValueError):
            self.diagnostics.record(
                "profile_restore_failed", level="warning", outcome="discarded",
                summary="Persisted profile was not usable",
            )
            stored = None
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
        provider = self.provider_status()
        configured = provider["configured_count"]
        provider_degraded = provider["status"] != "ready"
        reasons: list[str] = []
        if not profile_ready or monitor["pending_sections"]:
            reasons.append("profile_not_current")
        if configured == 0:
            reasons.append("provider_not_configured")
        elif provider_degraded:
            reasons.append("provider_degraded")
        return {
            "status": "ready" if not reasons else "degraded",
            "profile_ready": profile_ready,
            "monitor": monitor,
            "jev_configured": self._jev_configured(),
            "provider_status": provider["status"],
            "degraded_reasons": reasons,
        }

    def reconcile(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        try:
            clean = sanitize_for_gateway(snapshot)
        except SensitiveDataError as exc:
            raise ValueError("profile snapshot contains a forbidden field") from exc
        profile = self.monitor.reconcile(clean)
        self.active_profile = profile
        self.store.save_profile(profile)
        self.diagnostics.record(
            "profile_reconciled",
            correlation_id=profile.revision,
            outcome="active",
            capability_count=len(profile.capabilities),
            summary="Profile reconciled",
        )
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
        self.diagnostics.record(
            "profile_invalidated",
            level="warning" if sections else "info",
            outcome="stale" if sections else "unchanged",
            section_count=len(sections),
            summary="Profile invalidation recorded",
        )
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

    def provider_status(self) -> dict[str, Any]:
        """Return provider/circuit state without endpoint or credential data."""

        jev_hosted = bool(getattr(self.jev, "hosted", False))
        jev_configured = self._jev_configured()
        routes: list[dict[str, Any]] = []
        for route in self.routes.routes:
            circuit_open = not self.routes.circuit_allows(route.route_id)
            routes.append(
                {
                    "route_class": route.kind,
                    "route_id": route.route_id,
                    "status": "cooldown" if circuit_open else route.availability,
                    "reachability": "not_checked",
                    "response_kinds": [item.value for item in route.response_kinds],
                }
            )
        route_ready = any(item["status"] in {"ready", "available", "degraded"} for item in routes)
        jev_status = self._provider_state["jev"]["status"]
        if jev_configured and jev_status in {"configured", "healthy"}:
            overall = "ready"
        elif route_ready:
            overall = "degraded"
        else:
            overall = "unavailable" if jev_status in {"unavailable", "degraded"} else "disabled"
        return {
            "status": overall,
            "configured_count": int(jev_configured) + len(routes),
            "providers": {
                "jev": {
                    "status": jev_status,
                    "hosted": jev_hosted,
                    "reachability": "not_checked" if jev_configured else "not_configured",
                    "failures": self._provider_state["jev"]["failures"],
                    "error_code": self._provider_state["jev"]["error_code"],
                },
                "fallback": {
                    "status": "configured" if routes else "disabled",
                    "routes": routes,
                },
            }
        }

    def provider_compatibility(self, *, probe: bool = False) -> dict[str, Any]:
        """Return secret-safe provider compatibility state.

        A probe is opt-in because it consumes provider quota. When requested,
        it sends only a synthetic utterance and an opaque fixture capability;
        it never uses the active profile, user text, entity IDs, or state.
        The HTTP caller is responsible for authentication.
        """

        result: dict[str, Any] = {
            "status": "not_checked" if not probe else "checked",
            "providers": {},
        }
        if not probe:
            result["providers"]["jev"] = {
                "status": "not_checked" if self._jev_configured() else "not_configured",
                "error_code": None,
            }
            result["providers"]["fallback"] = {
                "status": "not_checked" if self.routes.routes else "not_configured",
                "routes": [route.route_id for route in self.routes.routes],
            }
            return result

        if self._jev_configured():
            probe_request = DecisionRequest(
                request_id="compatibility-probe",
                conversation_id="compatibility-probe",
                utterance="compatibility probe; do not control a device",
                language="en",
                profile_revision="compatibility-probe",
                policy_revision=self.config.policy.revision,
                candidates=(),
                bounded_context=(),
                sanitized_state={},
                privacy_mode=self.config.privacy_mode,
            )
            try:
                decision = self.jev.decide(probe_request)
                if not isinstance(decision, JevDecision):
                    raise ValueError("invalid decision")
                result["providers"]["jev"] = {"status": "compatible", "error_code": None}
            except JevError as exc:
                result["providers"]["jev"] = {"status": "unavailable", "error_code": getattr(exc, "code", "jev_unavailable")}
            except (AttributeError, KeyError, TypeError, ValueError):
                result["providers"]["jev"] = {"status": "incompatible", "error_code": "jev_invalid_response"}
        else:
            result["providers"]["jev"] = {"status": "not_configured", "error_code": None}

        fallback_status: dict[str, Any] = {"status": "not_configured", "routes": []}
        for route in self.routes.routes[:8]:
            fallback_status["routes"].append(route.route_id)
            if self.handoff is None:
                continue
            handoff_request = HandoffRequest(
                handoff_id=f"compatibility-{route.route_id}",
                request_id="compatibility-probe",
                conversation_id="compatibility-probe",
                utterance="compatibility probe; do not control a device",
                bounded_context=(),
                relevant_facts=({
                    "capability_id": "compatibility-probe-capability",
                    "display_name": "Compatibility probe (no device)",
                    "domain": "light",
                    "operation": "turn_on",
                    "parameter_schema": {"properties": {}, "required": []},
                },),
                route_id=route.route_id,
                complexity=Complexity.SIMPLE,
                reason="compatibility_probe",
                allowed_response_kinds=(ResponseKind.PROSE_RESPONSE,),
                handoff_depth=1,
                route_policy_revision=self.routes.revision,
                privacy_mode=self.config.privacy_mode,
            )
            try:
                response = self.handoff.dispatch(handoff_request)
                fallback_status["status"] = "compatible"
                fallback_status["last_route"] = route.route_id
                fallback_status["response_kind"] = response.kind.value
                break
            except HandoffInvalidResponse:
                fallback_status["status"] = "incompatible"
                fallback_status["error_code"] = "handoff_invalid_response"
            except HandoffError:
                fallback_status["status"] = "unavailable"
                fallback_status["error_code"] = "handoff_unavailable"
        result["providers"]["fallback"] = fallback_status
        result["status"] = "compatible" if any(
            item.get("status") == "compatible" for item in result["providers"].values() if isinstance(item, Mapping)
        ) else "incompatible"
        return result

    def diagnostics_page(self, **filters: Any) -> dict[str, Any]:
        return self.diagnostics.query(**filters)

    def process(self, payload: Mapping[str, Any]) -> DecisionResult:
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        if request_id in self._seen_requests:
            return self._seen_requests[request_id]
        try:
            clean_payload = sanitize_for_gateway(payload)
            request = DecisionRequest.from_dict(clean_payload)
            privacy_order = {
                PrivacyMode.LOCAL_ONLY: 0,
                PrivacyMode.JEV_HOSTED_ALLOWED: 1,
                PrivacyMode.HOSTED_ALLOWED: 2,
            }
            requested_privacy = request.privacy_mode if "privacy_mode" in clean_payload else self.config.privacy_mode
            effective_privacy = min(
                (requested_privacy, self.config.privacy_mode),
                key=privacy_order.__getitem__,
            )
            request = replace(request, privacy_mode=effective_privacy)
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
        if request.privacy_mode is PrivacyMode.LOCAL_ONLY and getattr(self.jev, "hosted", False):
            return self._remember(self._refusal(request.request_id, "privacy_mode_denied", "hosted Jev is disabled by privacy mode"))
        try:
            batch = build_batch_group(request.utterance, profile)
        except BatchRequestError as exc:
            return self._remember(self._result(request, ResultKind.REFUSE, exc.code))
        if batch is not None:
            # Jev chooses one bounded group option, never arbitrary members.
            # The gateway expands and validates the group only after selection.
            request = replace(request, candidates=(batch.candidate(),))
        try:
            decision = self.jev.decide(request)
            self._provider_event("healthy")
        except JevError as exc:
            self._provider_event("unavailable", error_code=getattr(exc, "code", "jev_unavailable"))
            if self.routes.routes:
                return self._remember(self._delegate(request, JevDecision(RouteKind.DELEGATE, Complexity.SIMPLE, reason=exc.code), batch=batch))
            return self._remember(self._result(request, ResultKind.REFUSE, exc.code))
        except Exception:
            self._provider_event("degraded", error_code="jev_invalid_response")
            if self.routes.routes:
                return self._remember(self._delegate(request, JevDecision(RouteKind.DELEGATE, Complexity.SIMPLE, reason="jev_invalid_response"), batch=batch))
            return self._remember(self._result(request, ResultKind.REFUSE, "jev_invalid_response"))

        if decision.route is RouteKind.CLARIFY:
            if self.routes.routes:
                return self._remember(self._delegate(request, decision, batch=batch))
            return self._remember(self._result(request, ResultKind.CLARIFY, "clarification_required", decision=decision))
        if decision.route is RouteKind.REFUSE:
            if self.routes.routes:
                return self._remember(self._delegate(request, decision, batch=batch, allow_proposal=False))
            return self._remember(self._result(request, ResultKind.REFUSE, "request_refused", decision=decision))
        if decision.route is RouteKind.READ_ONLY:
            return self._remember(self._result(request, ResultKind.ANSWER, "read_only_answer", decision=decision))
        if decision.route is RouteKind.ROUTINE_CONTROL:
            if batch is not None:
                result = self._evaluate_batch(request, decision, batch)
            else:
                result = self._evaluate_execution(request, decision)
            if result.response_key in {"confidence_too_low", "ambiguous_request", "invalid_parameters"} and self.routes.routes:
                return self._remember(self._delegate(request, decision, batch=batch))
            return self._remember(result)
        if decision.route is RouteKind.DELEGATE:
            return self._remember(self._delegate(request, decision, batch=batch))
        return self._remember(self._refusal(request.request_id, "jev_invalid_response", "unsupported route"))

    def _evaluate_execution(self, request: DecisionRequest, decision) -> DecisionResult:
        assert self.active_profile is not None
        if decision.capability_id not in {item.get("capability_id") for item in request.candidates}:
            return self._result(request, ResultKind.REFUSE, "candidate_not_allowed", decision=decision)
        policy = evaluate_capability(
            self.active_profile,
            decision.capability_id,
            confidence=decision.confidence,
            ambiguity=decision.ambiguity,
            confirmed=bool(request.sanitized_state.get("confirmation", False)),
            config=self.config.policy,
        )
        capability = next(
            (item for item in self.active_profile.capabilities if item.capability_id == decision.capability_id),
            None,
        )
        parameters: dict[str, Any] = {}
        if capability is not None:
            try:
                parameters = validate_parameters(capability, decision.parameters)
            except ValueError:
                return self._result(
                    request,
                    ResultKind.REFUSE,
                    "invalid_parameters",
                    decision=decision,
                )
        if policy.needs_confirmation:
            return self._result(
                request,
                ResultKind.CONFIRM,
                policy.response_key,
                decision=decision,
                parameters=parameters,
            )
        if not policy.allowed:
            result_kind = ResultKind.CLARIFY if policy.response_key in {"ambiguous_request", "confidence_too_low"} else ResultKind.REFUSE
            return self._result(request, result_kind, policy.response_key, decision=decision)
        return self._result(
            request,
            ResultKind.EXECUTE,
            "execute",
            decision=decision,
            parameters=parameters,
        )

    def _evaluate_batch(self, request: DecisionRequest, decision, batch: BatchGroup) -> DecisionResult:
        assert self.active_profile is not None
        if decision.capability_id != batch.group_id or decision.parameters:
            return self._result(request, ResultKind.REFUSE, "candidate_not_allowed")
        # The parser has already fixed the domain, verb, scope and exact set
        # of members. Jev's confidence measures its own interpretation, not
        # uncertainty about those deterministic bounds. It must still select
        # the sole group candidate; policy is then checked for every member.
        for capability_id in batch.members:
            policy = evaluate_capability(
                self.active_profile,
                capability_id,
                confidence=1.0,
                ambiguity=0.0,
                confirmed=False,
                config=self.config.policy,
            )
            if policy.needs_confirmation:
                return self._result(request, ResultKind.REFUSE, "batch_confirmation_unsupported")
            if not policy.allowed:
                kind = ResultKind.CLARIFY if policy.response_key in {"ambiguous_request", "confidence_too_low"} else ResultKind.REFUSE
                return self._result(request, kind, policy.response_key, decision=decision)
            capability = next(item for item in self.active_profile.capabilities if item.capability_id == capability_id)
            try:
                validate_parameters(capability, {})
            except ValueError:
                return self._result(request, ResultKind.REFUSE, "invalid_parameters")
        return self._result(request, ResultKind.EXECUTE, "batch_execute", decision=decision, capability_ids=batch.members)

    def _delegate(self, request: DecisionRequest, decision, *, batch: BatchGroup | None = None, allow_proposal: bool = True) -> DecisionResult:
        try:
            if allow_proposal:
                try:
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
                    route = select_route(
                        self.routes,
                        complexity=decision.complexity,
                        privacy_mode=request.privacy_mode,
                        required_response=ResponseKind.PROSE_RESPONSE,
                        max_latency_ms=self.config.policy.max_latency_ms,
                        max_cost=self.config.policy.max_cost,
                        policy=self.config.policy,
                    )
            else:
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
            relevant_facts=tuple(request.candidates[:16]),
            route_id=route.route_id,
            complexity=decision.complexity,
            reason=decision.reason or "jev_delegated",
            allowed_response_kinds=(ResponseKind.PROSE_RESPONSE, ResponseKind.TOOL_PROPOSAL) if allow_proposal else (ResponseKind.PROSE_RESPONSE,),
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
        if batch is not None:
            if capability_id != batch.group_id:
                return self._result(request, ResultKind.REFUSE, "fallback_target_unverified", decision=decision, route_id=route.route_id, handoff_id=handoff_id)
            candidate = JevDecision(RouteKind.ROUTINE_CONTROL, Complexity.SIMPLE, batch.group_id, 1.0, 0.0, reason="bounded_fallback_group")
            return replace(self._evaluate_batch(request, candidate, batch), route_id=route.route_id, handoff_id=handoff_id)
        candidate = next((item for item in request.candidates if item.get("capability_id") == capability_id), None)
        if not isinstance(candidate, Mapping) or not self._fallback_single_matches(request.utterance, candidate):
            return self._result(request, ResultKind.REFUSE, "fallback_target_unverified", decision=decision, route_id=route.route_id, handoff_id=handoff_id)
        capability = next((item for item in self.active_profile.capabilities if item.capability_id == capability_id), None)
        if capability is None:
            return self._result(request, ResultKind.REFUSE, "candidate_not_allowed", decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id)
        try:
            # Delegated proposals re-enter the same parameter gate as Jev
            # proposals. Parameter references are descriptive only.
            parameters = validate_parameters(capability, proposal.get("parameters", {}))
        except (TypeError, ValueError):
            return self._result(request, ResultKind.REFUSE, "invalid_parameters", decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id)
        policy = evaluate_capability(
            self.active_profile,
            capability_id,
            confidence=1.0,
            ambiguity=0.0,
            confirmed=bool(request.sanitized_state.get("confirmation", False)),
            config=self.config.policy,
        )
        if policy.needs_confirmation:
            return self._result(request, ResultKind.CONFIRM, policy.response_key, decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id, parameters=parameters)
        if not policy.allowed:
            return self._result(request, ResultKind.REFUSE, policy.response_key, decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id)
        return self._result(request, ResultKind.EXECUTE, "execute", decision=decision, route_id=route.route_id, handoff_id=handoff_id, capability_id=capability_id, parameters=parameters)

    @staticmethod
    def _fallback_single_matches(utterance: str, candidate: Mapping[str, Any]) -> bool:
        """A fallback cannot control a device absent an explicit name and verb."""

        text = " ".join(utterance.casefold().split())
        operation = str(candidate.get("operation", ""))
        operation_terms = {
            "turn_on": (r"\b(?:turn|switch)\s+on\b",),
            "turn_off": (r"\b(?:turn|switch)\s+off\b",),
            "toggle": (r"\btoggle\b",),
            "lock": (r"\block\b",),
            "unlock": (r"\bunlock\b",),
            "open_cover": (r"\b(?:open|raise)\b",),
            "close_cover": (r"\b(?:close|lower|shut)\b",),
            "set_brightness": (r"\b(?:set|change)\b", r"\bbrightness\b", r"\b(?:percent|%)\b"),
            "set_temperature": (r"\b(?:set|change)\b", r"\b(?:temperature|degrees?)\b"),
            "set_volume": (r"\b(?:set|change)\b", r"\bvolume\b"),
        }
        terms = operation_terms.get(operation)
        if terms is None:
            return False
        if any(re.search(term, text) is None for term in terms):
            return False
        name = str(candidate.get("display_name", "")).split(":", 1)[0].casefold().strip()
        return len(name) >= 3 and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None

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
        capability_ids: tuple[str, ...] = (),
        text: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> DecisionResult:
        return DecisionResult(
            kind=kind,
            request_id=request.request_id,
            profile_revision=request.profile_revision,
            policy_revision=request.policy_revision,
            response_key=response_key,
            capability_id=None if capability_ids else capability_id or (decision.capability_id if decision else None),
            capability_ids=capability_ids,
            route_id=route_id,
            complexity=decision.complexity if decision else None,
            confidence=decision.confidence if decision else None,
            handoff_id=handoff_id,
            text=text,
            parameters=dict(parameters or (decision.parameters if decision else {})),
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
        self.diagnostics.record(
            "conversation_result",
            level="warning" if result.kind.value in {"clarify", "confirm", "refuse"} else "info",
            correlation_id=result.request_id,
            outcome=result.response_key,
            route_class=result.route_id or "jev",
            summary="Conversation request completed",
        )
        return result
