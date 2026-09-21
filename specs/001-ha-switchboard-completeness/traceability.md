# HA Switchboard 0.2.0 requirements traceability

**Review date:** 2026-09-20
**Reviewed revision:** `299a5cb384445e109e9d729e98ee33de2d3f8bcd` on
`codex/fix-apparmor-runtime`
**Purpose:** distinguish behavior present in source and focused tests from the
future-completeness target described by `spec.md`, `plan.md`, and the contract
documents.

This report is evidence for requirements quality. It does not mark task or
checklist items complete. “Implemented” means that the behavior is visible in
the named source and has focused test coverage. “Partial” means the boundary
exists but the generated requirement is broader than the current behavior.
“Open” means no claim should be made for 0.2.0.

## Source and test evidence

| Boundary | Current evidence |
| --- | --- |
| App/Core separation and discovery | `app/config.yaml`, `app/ha_switchboard/discovery.py`, `custom_components/ha_switchboard/config_flow.py`; `tests/test_app_discovery.py`, `tests/test_core_integration_lifecycle.py` |
| Gateway safety and lifecycle | `app/ha_switchboard/server.py`, `gateway.py`, `change_monitor.py`, `store.py`; `tests/test_server.py`, `tests/test_change_monitor.py`, `tests/test_gateway.py` |
| Core profile and execution boundary | `custom_components/ha_switchboard/profile_adapter.py`, `coordinator.py`, `capabilities.py`, `execution.py`; `tests/test_core_integration_lifecycle.py`, `tests/test_profile.py`, `tests/test_adapter_contract.py` |
| Conversation behavior and follow-up context | `custom_components/ha_switchboard/conversation.py`, `conversation_context.py`, `read_only.py`; `tests/test_conversation_core_contract.py`, `tests/test_conversation_context.py`, `tests/test_read_only.py` |
| Native Assist fast path | `custom_components/ha_switchboard/native_path.py`, `conversation.py`; `tests/test_native_conversation_gate.py`, `tests/test_conversation_core_contract.py` |
| Bounded batches | `app/ha_switchboard/batch.py`, `custom_components/ha_switchboard/execution.py`; `tests/test_batch_actions.py` |
| Providers and fallback | `app/ha_switchboard/jev_client.py`, `openrouter_fallback.py`, `handoff.py`, `route_policy.py`; `tests/test_openrouter_fallback.py`, `tests/test_fallback_routing.py`, `tests/test_route_policy.py` |
| Web UI and diagnostics | `app/ha_switchboard/web.py`, `server.py`, `app/ha_switchboard/diagnostics.py`, `custom_components/ha_switchboard/sensor.py`; `tests/test_server.py`, `tests/test_web.py`, `tests/test_diagnostics_web.py`, `tests/test_core_diagnostics.py` |
| Packaging and public boundary | `app/config.yaml`, `app/apparmor.txt`, `custom_components/ha_switchboard/manifest.json`, `tools/check_release_boundary.py`; `tests/test_packaging.py`, `tests/test_release_boundary.py`, `tests/test_release_workflows.py` |

## Convergence evidence

The current checkout has focused source/test evidence for these safe boundaries:

- Native OpenRouter Decisions is parameter-free. `tests/test_openrouter_decisions.py`
  proves that its question set omits parameter extraction and that an invented or
  unrecognized parameter answer cannot authorize a write. A compatible typed Jev
  endpoint may supply bounded parameters, which are normalized and validated by
  `app/ha_switchboard/protocol.py` and `tests/test_gateway_parameters.py`.
- The executable capability matrix has 24 rows. Script and scene are not
  Switchboard matrix rows; `tests/test_capabilities_matrix.py` proves that their
  `activate` operation is rejected, while the fixture documentation keeps them
  available only for native Core-service tests.
- Local development is guarded: ordinary commands preserve the existing
  Supervisor/Core volume, destructive reset requires a verified snapshot and
  explicit confirmation, and the behavior is covered by `tests/test_local_dev.py`.
- Supervisor discovery registration uses a bounded retry and the same sanitized
  payload on each attempt; `tests/test_app_discovery.py` and
  `tests/test_server.py::test_supervisor_discovery_retry_is_bounded` cover the
  source-level behavior.

The latest repository test run was `469 passed, 4 skipped`. The skips were
the Home Assistant config-flow/runtime tests because the
`homeassistant` package is not installed in this host worktree; they are not
source-test proof. A separate read-only check of the preserved local
Supervisor harness confirmed Core/Supervisor HTTP 200, App readiness, the
persisted `hassio` integration entry, `conversation.ha_switchboard`, three
Assist pipelines, and fixture entities across the published mock domains. No
provider call or secret was used. No public-release, GHCR/mirror,
HACS/App-catalog, or live-canary evidence was claimed by this pass.

### Final audit refresh

The public-export finding identified during the audit is fixed at the reviewed
revision: `tools/standalone-smoke.sh` is explicitly allowlisted and the
regression test requires it to appear in the export. The full source suite is
`469 passed, 4 skipped`, and the release-boundary and quality checks pass.
This closes the local exporter defect but does not establish public mirror,
GHCR, HACS, multi-architecture, or live-canary acceptance.

The current source still conditionally exports descriptive `assist_surfaces`
when Home Assistant supplies them; a normal runtime with no such source yields
an empty list. The broad requirement for complete Assist-surface discovery is
therefore still partial, as documented below, and no stale documentation was
found claiming that boundary is complete.

## Functional requirements

| Requirement | 0.2.0 assessment | Evidence or requirements-quality note |
| --- | --- | --- |
| FR-001 | Partial | Installation, discovery/manual setup, token roles, Assist placement, and scan are documented. Public HACS/App installation and a complete recovery proof remain external/open. |
| FR-002 | Implemented | The App gateway has no Home Assistant service execution path and does not install Core files; App/Core responsibilities are documented. |
| FR-003 | Implemented at source / runtime proof partial | Core owns raw references, exposure, execution, verification, and the Core-local follow-up context. `ConversationContextStore` binds entries to conversation/user, applies TTL, and consumes once; complete live Assist confirmation proof remains open. |
| FR-004 | Partial, with native-first source behavior implemented | The Core conversation entity delegates supported routine intents to Home Assistant's native handler before the gateway; focused tests cover the gate and native bypass. Read-only, bounded execution, clarification/refusal, verification, and Core-local follow-up paths also exist. Full Home Assistant runtime proof and parameterized end-to-end behavior remain open. |
| FR-005 | Implemented | Response mapping and regression tests reject the prohibited generic phrase and use bounded response keys. |
| FR-006 | Partial | Plural bounded groups for explicit light/switch/fan on/off exist and can be narrowed by one unambiguous known area, floor, label, or validated named Home Assistant group. Atomic/toggle/parameterized batches and unsafe or unsupported group members remain outside the boundary. |
| FR-007 | Implemented | Core executes batches sequentially and reports verified and partial counts; tests cover a failed verification. |
| FR-008 | Implemented | The 32-target bound is enforced before execution and documented. |
| FR-009 | Partial | Typed Jev/Core schemas and validation cover published parameter types, but native OpenRouter Decisions is parameter-free; a typed Jev service or later value-extraction stage must supply action values. |
| FR-010 | Partial | `ConversationContextStore` provides bounded in-memory clarification/parameter/confirmation continuation with TTL, user binding, and one-time consumption, covered by `tests/test_conversation_context.py`. Full live Assist/E2E follow-up coverage is not present. |
| FR-011 | Implemented | `ProfileCoordinator.async_start()` calls health, refreshes options, and reconciles before scheduling periodic refresh. |
| FR-012 | Partial | Registry/reconnect/restart monitoring and bounded discovery are present. The source can carry descriptive Assist-surface data, but complete live Assist-surface coverage is not proven. |
| FR-013 | Implemented at source / local runtime ready | Authenticated `/v1/profile/scan`, UI acknowledgement, bounded progress/result state, and serialized/coalesced Core scans are covered by source tests. Full live scan-button and interruption evidence remains open. |
| FR-014 | Implemented | The monitor/coordinator generation checks and atomic replacement preserve the prior usable profile when a candidate is superseded. |
| FR-015 | Implemented at source / runtime proof partial | Health, readiness, profile status, capability counts, provider configuration, compatibility status, monitor status, and scan outcomes are exposed and tested. Full live provider compatibility evidence remains open. |
| FR-016 | Implemented at source / runtime proof partial | Options have schema, defaults, translations, and documentation. The active schema exposes only `adapter_only`; persisted `supervisor_read_only` values are migrated to `adapter_only` with the `supervisor_read_only_migrated_to_adapter_only` warning. Focused packaging, quality-audit, resilience, and server tests cover the schema boundary and migration; live upgrade evidence remains open. |
| FR-017 | Implemented at source / live provider proof open | OpenRouter chat, typed HTTP, generic OpenAI-compatible routing, ordered multi-route failover, privacy policy, circuits, and one-level handoff are source-tested. Authenticated provider and live failover evidence remains open. |
| FR-018 | Implemented | Sanitization, opaque IDs, redaction, and route payload tests cover the provider boundary; no provider receives Core execution authority. |
| FR-019 | Implemented | Fallback prose is a result and typed proposals re-enter gateway/Core checks; focused fallback tests cover invented batch rejection. |
| FR-020 | Implemented at source / deployment proof partial | Bounded transport/error mapping, endpoint policy, retries, circuits, rate limits, and safe failure codes are source-tested. Image/runtime injection coverage remains a release gate. |
| FR-021 | Implemented at source / browser proof open | The UI has status cards, scan control, setup links, redacted structured diagnostics, filters/pagination, and provider compatibility controls. A browser-level inspection remains open. |
| FR-022 | Partial | Healthy/degraded/stale/unavailable messages exist, but the generated matrix of all state classes and recovery paths is not complete. |
| FR-023 | Implemented at source / browser proof open | App/Core diagnostics provide bounded retention, correlation, redaction, filtering, pagination, safe sensors, and Web UI delivery. Browser-level inspection remains open. |
| FR-024 | Partial | The checked-in UI uses labels, status text, and focusable buttons. Complete accessibility validation and reduced-motion behavior are not proven. |
| FR-025 | Implemented for current boundary | The executable matrix is typed and has 24 fixture-covered rows across the published domains. Script/scene may remain descriptive/native Core surfaces, but `activate` is rejected by `ExecutionBoundary` and is not a Switchboard capability. Broader future compatibility remains out of scope. |
| FR-026 | Implemented | Opaque capability IDs cross the gateway; raw entity IDs remain in the Core target map. |
| FR-027 | Implemented at source, runtime proof open | Manifest, AppArmor, no host networking/devices, and UID 65532 behavior are source-tested. Installed Supervisor permission parity still requires runtime evidence. |
| FR-028 | Implemented | Direct API authentication, content type/body limits, and safe auth failures are covered by `tests/test_server.py`. |
| FR-029 | Partial | Compose uses the same gateway contract and documents its missing Supervisor boundary. A full standalone runtime compatibility canary is not represented by source tests alone. |
| FR-030 | Partial | Restart/profile recovery and token/discovery handling exist. Option migration, rotation, and all outage recovery scenarios are not complete. |
| FR-031 | Partial | Local tooling uses ignored environment inputs, validates provider/fallback options, avoids printing values, and has focused regression tests. A complete live fixture/provider run remains open. |
| FR-032 | Implemented in tooling policy | `tools/local-dev.sh` guards destructive reset and preserves the default volume; live-volume proof is intentionally outside this documentation review. |
| FR-033 | Implemented at source / live Assist proof open | The fixture coverage report proves 24 executable matrix rows, local fixtures are installed across the published domains, and script/scene native-only boundaries are explicit. A complete live Assist acceptance run is not recorded here. |
| FR-034 | Open | The plan names the required matrix, but current focused tests do not establish all runtime, architecture, fallback, security, recovery, and E2E scenarios. |
| FR-035 | Partial | Provider and local scripts have bounded timeouts in key paths. A repository-wide bounded-retry audit remains open. |
| FR-036 | Partial | Version consistency and GHCR/source-label checks are documented and partly tested. Public tag, digest, multi-architecture, and live publication evidence are external release gates. |
| FR-037 | Partial | Packaging/public-export checks exist. HACS, Hassfest, App repository review, and protected-master publication remain external gates. |
| FR-038 | Implemented for current boundary | README, App docs, release docs, and translations now identify responsibilities, setup, privacy, providers, scans, limits, recovery, and unsupported behavior. |
| FR-039 | Implemented for current boundary | The support matrix and release docs separate supported, experimental, compatibility-target, and external-acceptance claims. |
| FR-040 | Partial | `docs/RELEASE.md` has the release/rollback evidence model. A completed candidate run and live canary record are still required. |
| FR-041 | Implemented and live-probed | `native_path.py` restricts native-first handling to the supported routine intent/domain set and `conversation.py` excludes Switchboard recursion; focused tests plus the bounded `native_miss_runtime.py` and `local_api.py native` probes cover native miss continuation, native success, and provider bypass. |

## Success criteria

| Criterion | Assessment | Note |
| --- | --- | --- |
| SC-001 | Open | Requires a clean fixture run proving installation through read-only Assist in ten minutes. |
| SC-002 | Implemented in source / runtime open | Startup reconciliation is explicit and bounded by the coordinator; live timing evidence is not recorded here. |
| SC-003 | Partial | The source suite covers the native-first gate, Core-local continuation, bounded batch behavior, and fallback contracts. A live matrix including native success, native miss, provider fallback, parameter extraction, and full follow-up acceptance remains open. |
| SC-004 | Partial | Redaction fixtures exist, but the full acceptance matrix is not complete. |
| SC-005 | Partial | Core gates revision, allowlist, parameters, confirmation, and verification; complete diagnostics/idempotency evidence is not established. |
| SC-006 | Open | UI scan acknowledgement exists, but completion timing and concurrent coalescing are not proven. |
| SC-007 | Open | Restart preservation is covered in parts; three-cycle App/Core upgrade evidence is absent. |
| SC-008 | Partial | Direct auth and stale-profile rejection are tested; the complete injected security matrix is not. |
| SC-009 | Open | No repository-level bounded-duration acceptance run is recorded in this checkout. |
| SC-010 | Open | Multi-architecture image/tag/digest proof is an external release gate. |
| SC-011 | Implemented by documentation, runtime unproven | A new reader can identify the App/Core boundary, Assist path, privacy, fallback, and recovery limits from the docs. |
| SC-012 | Partial | The documentation now names open boundaries, but several advertised target behaviors still lack acceptance proof. |
| SC-013 | Partial | Focused source tests prove native routine-intent filtering and native success bypasses the gateway. The required real Home Assistant runtime and Assist-pipeline evidence is not recorded. |

## Requirements-quality findings

1. The generated spec describes a complete product while the source is an
   experimental 0.2.0 implementation. The README support matrix and this file
   narrow claims to observed behavior; the spec remains the forward-looking
   completion target.
2. `contracts/profile-reconciliation.md` and the plan describe complete Assist
   surface discovery, while `HomeAssistantProfileAdapter` currently emits an
   empty `assist_surfaces` list. This is a partial implementation, not a docs
   wording issue to hide.
3. The conversation contract requires safe clarification/confirmation context.
   `conversation_context.py` and `conversation.py` now provide a Core-local,
   TTL-bound, user-bound, one-time-consumed store. Full live Assist/E2E proof is
   still absent, so the docs state the implementation boundary rather than
   claiming release acceptance.
4. Native OpenRouter Decisions is documented as parameter-free. Core schemas
   are useful validation boundaries, but they do not make parameter extraction
   end to end; the provider limitation must remain visible.
5. Script and scene routine rows may be visible in sanitized profile data, but
   `ExecutionBoundary` rejects `activate`; they must not be described as
   executable controls until that boundary changes with tests.
6. Public mirror, HACS catalog, App repository, GHCR, and live Supervisor
   results are separate evidence states. Release documentation now requires
   checking each artifact rather than treating a source tag or local test as
   publication proof.
7. The native-first conversation path is now represented explicitly in the
   spec, plan, execution contract, quickstart, checklist, and this traceability
   report. Its source behavior is implemented, but live Home Assistant proof
   remains separate.

## Recommended next traceability pass

Before calling the feature complete, run the focused and runtime scenarios for
FR-009/010/013/015/017/021/023/024/033–040, record sanitized results in the
release evidence, and update this report from “partial/open” only when the
named source and test evidence exist. Do not mark task or checklist boxes from
this report alone.
