---

description: "Implementation tasks for HA Switchboard feature completeness"
---

# Tasks: HA Switchboard Feature Completeness

**Input**: Design documents from specs/001-ha-switchboard-completeness/

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Organization**: Tasks are grouped by user story. Tests are included because
the specification explicitly requires contract, runtime, security, fixture, and
release validation for every boundary.

## Phase 1: Setup and baseline

**Purpose**: Establish traceability and safe test scaffolding without touching
the existing local Home Assistant volume.

- [x] T001 [P] Add feature acceptance markers and focused pytest configuration in ./pyproject.toml
- [x] T002 [P] Add sanitized provider, profile, conversation, and diagnostic fixtures in tests/fixtures/jev-decisions.json
- [x] T003 [P] Add fallback prose/proposal and provider-failure fixtures in tests/fixtures/downstream-responses.json
- [x] T004 [P] Add capability-matrix fixture coverage for all current domains in tests/fixtures/home-assistant-discovery.json
- [x] T005 Add a versioned feature-completeness baseline and current 0.2.0 limitation inventory in specs/001-ha-switchboard-completeness/research.md
- [x] T006 Add explicit ignored local-secret and local-runtime patterns in .gitignore and tools/local-dev.sh

## Phase 2: Foundational contracts, limits, security, and diagnostics

**Purpose**: Blocking prerequisites for every user story. No story implementation
is complete until these contracts are stable and tested.

- [x] T007 [P] Implement shared bounded limits and size constants in app/ha_switchboard/limits.py
- [x] T008 [P] Implement versioned typed wire models and strict validators in app/ha_switchboard/contracts.py
- [x] T009 [P] Implement redacted structured diagnostic events, retention, correlation, and safe error codes in app/ha_switchboard/diagnostics.py
- [x] T010 [P] Implement Core-local diagnostic event helpers and safe exception mapping in custom_components/ha_switchboard/diagnostics.py
- [x] T011 Implement request authentication, content-type checks, body limits, method routing, and stable error envelopes in app/ha_switchboard/server.py
- [x] T012 Implement safe endpoint, redirect, timeout, retry, and circuit policy in app/ha_switchboard/http_security.py
- [x] T013 Update persisted App state schema, atomic writes, bounded retention, and migration hooks in app/ha_switchboard/store.py
- [x] T014 Implement provider route registry validation and schema-version negotiation in app/ha_switchboard/route_policy.py
- [x] T015 Add App option validation, migration, secret handling, and runtime status fields in app/ha_switchboard/server.py and app/config.yaml
- [x] T016 Replace inert supervisor_read_only configuration with migration to adapter_only and an explicit upgrade warning in app/config.yaml and app/ha_switchboard/server.py
- [x] T017 [P] Add contract tests for gateway authentication, limits, error envelopes, and redaction in tests/test_gateway_contracts.py
- [x] T018 [P] Add contract tests for persistence migration, crash-safe writes, retention, and secret omission in tests/test_store_and_diagnostics.py
- [x] T019 [P] Add provider route policy tests for privacy, timeout, circuit, handoff, and endpoint validation in tests/test_route_policy.py
- [x] T020 Add foundational contract coverage for all new wire schemas in tests/test_protocol.py and tests/test_adapter_contract.py

**Checkpoint**: Shared contracts, security boundaries, diagnostics, and
migration behavior are stable; user stories may proceed in priority order or
in parallel where their files do not overlap.

## Phase 3: User Story 1 - Install and connect Switchboard (Priority: P1) MVP

**Goal**: A user can install App and Core integration, accept discovery or use
manual setup, select Switchboard in Assist, and reconnect without losing state.

**Independent Test**: Install the App and integration in a disposable fixture,
complete discovery/manual config flow, select the agent, reconcile a profile,
restart both sides, and verify the config entry and profile remain active.

### Tests for User Story 1

- [x] T021 [P] [US1] Add Supervisor discovery and config-flow acceptance tests in tests/test_app_discovery.py and tests/test_core_integration_lifecycle.py
- [x] T022 [P] [US1] Add manual URL/token validation and secret-omission tests in tests/test_core_integration_lifecycle.py
- [x] T023 [P] [US1] Add Assist conversation-agent registration and selectable-agent runtime tests in tests/test_conversation_core_contract.py
- [x] T024 [US1] Add restart, upgrade, duplicate-discovery, and token-mismatch runtime scenarios in tests/test_core_integration_lifecycle.py

### Implementation for User Story 1

- [x] T025 [US1] Version and document the App discovery payload and scoped Supervisor authorization in app/ha_switchboard/discovery.py and app/config.yaml
- [x] T026 [US1] Harden discovered endpoint normalization, UUID preservation, and duplicate protection in custom_components/ha_switchboard/config_flow.py
- [x] T027 [US1] Complete manual setup validation, gateway health verification, and actionable error translations in custom_components/ha_switchboard/config_flow.py and custom_components/ha_switchboard/translations/en.json
- [x] T028 [US1] Register the conversation entity with complete Home Assistant metadata and setup lifecycle in custom_components/ha_switchboard/conversation.py and custom_components/ha_switchboard/manifest.json
- [x] T029 [US1] Add config-entry migration, token rotation, and reconnect handling without deleting valid profile state in custom_components/ha_switchboard/__init__.py and custom_components/ha_switchboard/runtime.py
- [x] T030 [US1] Add truthful startup/readiness and setup guidance to the App status contract in app/ha_switchboard/server.py and custom_components/ha_switchboard/client.py
- [x] T031 [US1] Add the exact Assist pipeline selection and first-use flow to README.md and app/DOCS.md
- [x] T032 [US1] Add installation/upgrade evidence capture and config-entry verification to tools/local-fixtures/local_api.py and tools/local-fixtures/README.md

**Checkpoint**: A user can complete the installation journey and select the
conversation agent; failure states are specific and no secret is displayed.

## Phase 4: User Story 2 - Use Assist for ordinary home control (Priority: P1)

**Goal**: Read-only, single-device, clarification, confirmation, and verified
ordinary controls produce useful, honest responses.

**Independent Test**: Run the US2 acceptance matrix through the fixture Assist
pipeline and compare typed results, Core service calls, and post-action state.

### Tests for User Story 2

- [x] T033 [P] [US2] Add read-only state-answer tests with local-state and unavailable-state cases in tests/test_read_only.py
- [x] T034 [P] [US2] Add single-device control and verification tests for every current routine operation in tests/test_core_integration_lifecycle.py
- [x] T035 [P] [US2] Add specific reason/next-action response tests and prohibited-phrase regression tests in tests/test_conversation_core_contract.py
- [x] T036 [US2] Add stale-revision, unknown-capability, invalid-parameter, and provider-invalid-response E2E scenarios in tests/test_e2e_harness.py

### Implementation for User Story 2

- [x] T037 [US2] Expand Core-local read-only state normalization and user-facing labels in custom_components/ha_switchboard/read_only.py
- [x] T038 [US2] Implement reason-specific result mapping for stale, ambiguous, unavailable, unsupported, blocked, and verification outcomes in custom_components/ha_switchboard/conversation.py
- [x] T039 [US2] Align gateway result kinds, safe reasons, and next actions with the conversation response map in app/ha_switchboard/gateway.py and app/ha_switchboard/protocol.py
- [x] T040 [US2] Add verified success/failure/partial response templates to custom_components/ha_switchboard/translations/en.json
- [x] T041 [US2] Add bounded read-only and ordinary control examples, failure explanations, and privacy notes to README.md and app/DOCS.md
- [x] T042 [US2] Add correlation and execution outcome diagnostics around each Core conversation request in custom_components/ha_switchboard/conversation.py and custom_components/ha_switchboard/execution.py
- [x] T043 [US2] Verify that no user-facing response uses the prohibited generic refusal phrase across source, fixtures, and generated translations in tests/test_conversation_core_contract.py

**Checkpoint**: Basic Assist use is useful without fallback and every failure is
honest, bounded, and actionable.

## Phase 5: User Story 3 - Control groups and multiple devices (Priority: P1)

**Goal**: Plural, area, label, and group requests support bounded multi-device
actions with per-target verification and honest partial results.

**Independent Test**: Use fixture lights, switches, fans, areas, labels, groups,
unavailable members, high-risk members, and a mid-batch failure.

### Tests for User Story 3

- [x] T044 [P] [US3] Add area, label, group, plural-resolution, and 32-target-bound tests in tests/test_batch_actions.py
- [x] T045 [P] [US3] Add mixed-domain, unavailable-member, confirmation-member, and preflight-no-write tests in tests/test_batch_actions.py
- [x] T046 [P] [US3] Add partial-failure and per-target-verification response tests in tests/test_core_integration_lifecycle.py
- [x] T047 [US3] Add duplicate-request/idempotency and toggle-retry tests in tests/test_batch_actions.py and tests/test_gateway.py

### Implementation for User Story 3

- [x] T048 [US3] Expand sanitized profile context for areas, labels, groups, and safe plural selection in custom_components/ha_switchboard/profile_adapter.py
- [x] T049 [US3] Add batch target resolution and explicit maximum-size policy in custom_components/ha_switchboard/capabilities.py and custom_components/ha_switchboard/execution.py
- [x] T050 [US3] Implement preflight partitioning for safe, unavailable, unsupported, and confirmation-required members in custom_components/ha_switchboard/execution.py
- [x] T051 [US3] Implement per-target result collection, verification, partial completion, and retry-safe summaries in custom_components/ha_switchboard/execution.py
- [x] T052 [US3] Extend gateway batch decision normalization and bounded proposal handling in app/ha_switchboard/batch.py and app/ha_switchboard/gateway.py
- [x] T053 [US3] Add request identity/idempotency storage and toggle replay protection in custom_components/ha_switchboard/execution.py and app/ha_switchboard/store.py
- [x] T054 [US3] Add batch outcome diagnostics with safe display labels and counts in custom_components/ha_switchboard/diagnostics.py and app/ha_switchboard/diagnostics.py
- [x] T055 [US3] Document supported multi-device selection, 32-target safety bound, partial results, and unsupported batch operations in README.md and app/DOCS.md

**Checkpoint**: Multi-device on/off flows work through Assist without silent
skips or false all-success claims.

## Phase 6: User Story 4 - Understand values and continue a conversation (Priority: P1)

**Goal**: Parameterized controls and clarification/confirmation follow-ups work
as safe, short-lived, user-bound conversation state.

**Independent Test**: Run brightness, volume, temperature, HVAC mode, missing
value, invalid value, clarification, confirmation, expiration, and cross-user
scenarios through a fixture pipeline.

### Tests for User Story 4

- [x] T056 [P] [US4] Add parameter schema/range/enum extraction and normalization tests in tests/test_gateway_parameters.py
- [x] T057 [P] [US4] Add missing, invalid, conflicting, and overflow parameter tests in tests/test_gateway_parameters.py and tests/test_execution.py
- [x] T058 [P] [US4] Add clarification/confirmation context lifecycle tests in tests/test_conversation_context.py
- [ ] T059 [US4] Complete live follow-up Assist runtime verification for same conversation, different user, expiry, cancellation, and replay in tests/test_e2e_harness.py (the installed provider-backed probe now proves same-conversation confirmation, cancellation, and one-shot replay with the existing 28-entity fixture; deterministic tests cover user binding/TTL, while second-user and natural-expiry live gates remain explicitly unavailable)

### Implementation for User Story 4

- [x] T060 [US4] Extend typed parameter schemas and normalized service data for all published parameterized operations in custom_components/ha_switchboard/capabilities.py and custom_components/ha_switchboard/execution.py
- [x] T061 [US4] Add bounded value-extraction questions and response parsing to app/ha_switchboard/jev_client.py and app/ha_switchboard/protocol.py
- [x] T062 [US4] Implement Core-local pending clarification/confirmation context with TTL, user binding, and one-time consumption in custom_components/ha_switchboard/conversation_context.py
- [x] T063 [US4] Integrate context resolution before provider calls and context creation after clarify/confirm results in custom_components/ha_switchboard/conversation.py
- [x] T064 [US4] Add explicit affirmative/negative parsing and safe handling of bare confirmations in custom_components/ha_switchboard/conversation.py
- [x] T065 [US4] Add parameter, pending-context, expiry, and confirmation diagnostics in custom_components/ha_switchboard/diagnostics.py and app/ha_switchboard/diagnostics.py
- [x] T066 [US4] Document parameter ranges, follow-up behavior, expiration, and confirmation wording in README.md, app/DOCS.md, and custom_components/ha_switchboard/translations/en.json

**Checkpoint**: A user can say “set”, answer a clarification, or confirm a
risky action without repeating the entire request or authorizing stale state.

## Phase 7: User Story 5 - Fall back to a capable model safely (Priority: P1)

**Goal**: OpenRouter chat and typed HTTP fallback routes handle eligible
delegation without bypassing the Core execution boundary.

**Independent Test**: Run prose, one-proposal, malformed, unauthorized,
privacy-blocked, timeout, route-failover, and no-route scenarios with sanitized
provider fixtures.

### Tests for User Story 5

- [x] T067 [P] [US5] Add OpenRouter fallback request/response schema and bounded-prose tests in tests/test_openrouter_fallback.py
- [x] T068 [P] [US5] Add typed HTTP fallback adapter contract tests in tests/test_typed_http_fallback.py
- [x] T069 [P] [US5] Add sanitized payload/no-raw-ID/no-secret provider tests in tests/test_handoff.py and tests/test_redaction.py
- [x] T070 [P] [US5] Add malformed proposal, invented capability, arbitrary-service-data, and confirmation-bypass tests in tests/test_fallback_routing.py
- [x] T071 [US5] Add ordered-route, privacy, timeout, circuit, and one-level-handoff E2E tests in tests/test_fallback_routing.py and tests/test_e2e_harness.py

### Implementation for User Story 5

- [x] T072 [US5] Implement a strict OpenRouter chat-completions adapter returning bounded prose or one typed proposal in app/ha_switchboard/openrouter_fallback.py
- [x] T073 [US5] Implement the typed HTTP fallback adapter against the normalized provider contract in app/ha_switchboard/typed_http_fallback.py
- [x] T074 [US5] Extend handoff parsing and proposal validation for typed parameters, route identity, size, and handoff depth in app/ha_switchboard/handoff.py
- [x] T075 [US5] Implement ordered fallback eligibility, route failover, privacy policy, and circuit transitions in app/ha_switchboard/route_policy.py
- [x] T076 [US5] Add fallback option loading, validation, and secret-safe status reporting in app/ha_switchboard/server.py and app/config.yaml
- [x] T077 [US5] Add authenticated synthetic provider compatibility checks in app/ha_switchboard/server.py and app/ha_switchboard/web.py
- [x] T078 [US5] Route delegated results through the same gateway/Core proposal, freshness, confirmation, execution, and verification checks in app/ha_switchboard/gateway.py and custom_components/ha_switchboard/conversation.py
- [x] T079 [US5] Document OpenRouter chat, typed HTTP, privacy modes, route configuration, fallback limits, and arbitrary-HA-agent exclusion in README.md and app/DOCS.md

**Checkpoint**: Unsupported Jev requests can receive bounded fallback help or a
specific configuration explanation; no fallback response can directly control HA.

## Phase 8: User Story 6 - Keep the capability profile current (Priority: P1)

**Goal**: Startup, event, timer, reconnect, and manual scans produce complete
atomic profile generations.

**Independent Test**: Start Core/App in either order, mutate registries and
exposure, run a manual scan during reconciliation, interrupt a scan, restart the
App, and inspect status/revision/write behavior.

### Tests for User Story 6

- [x] T080 [P] [US6] Add startup-first reconciliation tests that prove no wait for the refresh timer in tests/test_core_integration_lifecycle.py
- [x] T081 [P] [US6] Add every registry/exposure/state/reconnect/restart invalidation test in tests/test_change_monitor.py
- [x] T082 [P] [US6] Add manual-scan authentication, coalescing, progress, failure, and stale-profile tests (implemented in tests/test_manual_scan_acceptance.py with bounded live scan evidence)
- [x] T083 [P] [US6] Add generation-race, malformed-snapshot, oversized-snapshot, and atomic-replacement tests in tests/test_profile.py and tests/test_adapter_contract.py
- [x] T084 [US6] Complete authorized live local startup/scan/restart verification in tools/local-fixtures/local_api.py and tests/test_e2e_harness.py (preserve-first volume identity/profile/fixture guards, startup/scan, and the event-driven App/Core restart cycle now pass; the watcher subscribes before mutation and waits for App `/readyz` or Core HTTP readiness without repeated Supervisor polling)

### Implementation for User Story 6

- [x] T085 [US6] Expand Core discovery of entities, services, areas, floors, labels, groups, routines, and Assist exposure in custom_components/ha_switchboard/profile_adapter.py
- [x] T086 [US6] Add service capability and integration-specific shape handling with bounded warnings in custom_components/ha_switchboard/profile_adapter.py
- [x] T087 [US6] Add startup reconciliation and App-generation detection before periodic scheduling in custom_components/ha_switchboard/coordinator.py
- [x] T088 [US6] Complete registry, exposure, state, reconnect, and restart subscriptions and event coalescing in custom_components/ha_switchboard/coordinator.py and custom_components/ha_switchboard/const.py
- [x] T089 [US6] Add authenticated manual scan endpoint and bounded reconcile-run state in app/ha_switchboard/server.py and app/ha_switchboard/gateway.py
- [x] T090 [US6] Add Core scan request plumbing and serialized scan handling in custom_components/ha_switchboard/client.py and custom_components/ha_switchboard/coordinator.py
- [x] T091 [US6] Add profile/reconcile diagnostics, status fields, startup recovery guidance, and scan outcome documentation in app/ha_switchboard/diagnostics.py, custom_components/ha_switchboard/sensor.py, and README.md

**Checkpoint**: The active profile is current after startup or a requested scan,
and stale/incomplete replacements never silently authorize writes.

## Phase 9: User Story 7 - See and manage Switchboard state in the Web UI (Priority: P2)

**Goal**: The ingress Web UI becomes an accessible operator console for status,
scan, setup help, provider state, and redacted logs.

**Independent Test**: Exercise healthy, stale, unavailable, scanning, provider
failure, and fallback-disabled states and inspect the UI and its JSON contracts.

### Tests for User Story 7

- [x] T092 [P] [US7] Add Web UI rendering/status endpoint tests for all state classes in tests/test_web.py
- [x] T093 [P] [US7] Add scan action, bounded polling, concurrent-scan, and error-state tests in tests/test_web.py and tests/test_server.py
- [x] T094 [P] [US7] Add diagnostic filtering, pagination, retention, and redaction tests in tests/test_diagnostics_web.py
- [x] T095 [US7] Add static accessibility and secret-safe browser payload checks in tests/test_web.py

### Implementation for User Story 7

- [x] T096 [US7] Build the status dashboard with liveness, readiness, profile, Core, Jev, fallback, version, and scan cards in app/ha_switchboard/web.py
- [x] T097 [US7] Add manual scan control with queued/running/active/failed state and bounded polling in app/ha_switchboard/web.py
- [x] T098 [US7] Add configuration-help, Assist setup, privacy, token-role, and recovery content in app/ha_switchboard/web.py and app/DOCS.md
- [x] T099 [US7] Add redacted diagnostic event endpoint, filter parameters, pagination, and safe summaries in app/ha_switchboard/server.py and app/ha_switchboard/diagnostics.py
- [x] T100 [US7] Add provider compatibility/test-route status without exposing endpoint credentials in app/ha_switchboard/server.py and app/ha_switchboard/web.py
- [x] T101 [US7] Add accessible labels, keyboard focus, text-plus-icon status, loading states, and reduced-motion behavior in app/ha_switchboard/web.py
- [x] T102 [US7] Add Web UI troubleshooting screenshots/flow descriptions and operator log interpretation to README.md and app/DOCS.md

**Checkpoint**: An operator can explain and recover the common App/Core/provider
failure states from ingress without reading raw logs or guessing at options.

## Phase 10: User Story 8 - Support the advertised Home Assistant capability surface (Priority: P2)

**Goal**: The documented support matrix and actual profile/execution behavior
agree across domains, operations, parameters, exposure, and verification.

**Independent Test**: Populate every supported mock domain, reconcile, invoke
each documented operation, and verify unsupported surfaces are explicit.

### Tests for User Story 8

- [x] T103 [P] [US8] Add operation-matrix coverage tests for light, switch, fan, media, climate, cover, lock, script, and scene in tests/test_capabilities_matrix.py
- [x] T104 [P] [US8] Add profile support/exposure/unknown-attribute tests in tests/test_profile.py and tests/test_adapter_contract.py
- [x] T105 [P] [US8] Add fixture entities, areas, labels, groups, services, and Assist exposure for every matrix row in tools/local-fixtures/switchboard.yaml and tools/local-fixtures/local_api.py
- [x] T106 [US8] Add runtime operation matrix and unsupported-surface E2E scenarios in tests/test_e2e_harness.py

### Implementation for User Story 8

- [x] T107 [US8] Finalize the published domain/operation/parameter/risk/verification matrix in custom_components/ha_switchboard/capabilities.py
- [x] T108 [US8] Add domain-specific discovery and safe context for every supported matrix row in custom_components/ha_switchboard/profile_adapter.py
- [x] T109 [US8] Add verification rules and unavailable/unknown-state handling for every supported operation in custom_components/ha_switchboard/execution.py
- [x] T110 [US8] Add bounded scene/script/routine handling or explicitly migrate unsupported rows out of the matrix in custom_components/ha_switchboard/capabilities.py and conversation.py
- [x] T111 [US8] Keep unknown integration-specific attributes as bounded warnings instead of profile-fatal values in custom_components/ha_switchboard/profile_adapter.py
- [x] T112 [US8] Publish the support matrix and unsupported-surface table in README.md, app/DOCS.md, and docs/PUBLIC_REPOSITORY.md
- [x] T113 [US8] Add a fixture coverage report that compares exposed mock entities to the published matrix in tools/local-fixtures/local_api.py and tests/test_capabilities_matrix.py

**Checkpoint**: Users and maintainers see the same supported/unsupported behavior
in the profile, execution path, fixture, tests, and documentation.

## Phase 11: User Story 9 - Run safely in supported deployment modes (Priority: P2)

**Goal**: App and standalone deployments enforce least privilege, bounded
requests, persistence, and recoverable provider/network failure.

**Independent Test**: Inspect/build both deployment modes, inject auth/provider/
filesystem/network failures, restart, rotate tokens, and verify recovery.

### Tests for User Story 9

- [x] T114 [P] [US9] Add App manifest, non-root, ingress-source, Supervisor-scope, and AppArmor assertions in tests/test_app_security.py and tests/test_app_image_smoke_harness.py
- [x] T115 [P] [US9] Add direct API auth, body-limit, content-type, method, redirect, timeout, and rate-limit tests in tests/test_gateway_security.py
- [x] T116 [P] [US9] Add standalone Compose token/network/persistence checks in tests/test_packaging.py and tests/test_standalone_runtime.py
- [x] T117 [P] [US9] Add empty-options, provider-outage, restart, token-rotation, and migration recovery tests in tests/test_server.py and tests/test_core_integration_lifecycle.py

### Implementation for User Story 9

- [x] T118 [US9] Harden AppArmor rules, runtime filesystem access, shared-library permissions, and non-root entrypoint in app/apparmor.txt, app/Dockerfile, and app/run.sh (source/image validated; live AppArmor enforcement remains a release gate)
- [x] T119 [US9] Finalize least-privilege App manifest, discovery scope, ingress restriction, presentation, and option schema in app/config.yaml
- [x] T120 [US9] Add request rate/size limits, safe browser request protection, and bounded dependency handling in app/ha_switchboard/server.py and app/ha_switchboard/http_security.py
- [x] T121 [US9] Align standalone Compose environment validation, token enforcement, network exposure, and persistent data behavior in standalone/compose.yaml
- [x] T122 [US9] Add empty-provider/degraded/readiness state and recovery logging without crash loops in app/ha_switchboard/server.py and app/ha_switchboard/diagnostics.py
- [x] T123 [US9] Add restart-safe profile/options persistence and coordinated App/Core migration behavior in app/ha_switchboard/store.py and custom_components/ha_switchboard/__init__.py (source and recovery tests pass; live restart-cycle evidence remains open)
- [x] T124 [US9] Add deployment security, threat boundaries, token rotation, backup, and recovery guidance to app/DOCS.md, README.md, and docs/RELEASE.md

**Checkpoint**: Both deployment modes fail closed under bad input/provider
failure and recover without losing the local configuration or profile.

## Phase 12: User Story 10 - Develop, validate, publish, and update Switchboard (Priority: P2)

**Goal**: Local development, fixtures, CI, packaging, public publication, and
coordinated updates provide reproducible evidence without destructive resets.

**Independent Test**: Run the local workflow on the existing harness, execute
the fixture Assist matrix, run release gates, and inspect version/image/mirror
consistency.

### Tests for User Story 10

- [x] T125 [P] [US10] Add local-dev environment parsing, secret omission, bounded wait, and no-reset regression tests in tests/test_local_dev.py
- [x] T126 [P] [US10] Add idempotent mock-entity, area/label/group, Assist-pipeline, and production-host refusal tests in tests/test_local_fixtures.py
- [x] T127 [P] [US10] Add bounded App image E2E failure/retry and architecture-selection tests in tests/test_app_image_e2e.py and tools/app-image-e2e.sh
- [x] T128 [P] [US10] Add workflow path, actionlint, public-export, HACS, Hassfest, and release-evidence checks in tests/test_release_workflows.py
- [x] T129 [US10] Add full release-candidate acceptance orchestration and sanitized evidence assertions in tests/test_release_acceptance.py

### Implementation for User Story 10

- [x] T130 [US10] Add an explicit local environment health check and safe .env.local loading for every provider/fallback option in tools/local-dev.sh
- [x] T131 [US10] Make local rebuild/start/sync commands preserve the existing Supervisor/Core volume and refuse implicit fresh-environment creation in tools/local-dev.sh
- [x] T132 [US10] Add verified snapshot guidance and a separate explicit destructive reset command path in tools/local-dev.sh and tools/local-fixtures/README.md
- [x] T133 [US10] Expand idempotent fixture creation for all supported mock domains, states, areas, labels, groups, services, and Assist pipeline setup in tools/local-fixtures/install.py, tools/local-fixtures/local_api.py, and tools/local-fixtures/switchboard.yaml
- [x] T134 [US10] Add provider stubs and deterministic fallback/parameter failure modes to tests/fixtures/downstream-responses.json and tools/local-fixtures/local_api.py
- [x] T135 [US10] Bound all local E2E retry loops, dependency probes, cleanup, and failure evidence in tools/app-image-e2e.sh and tools/local-dev.sh
- [x] T136 [US10] Extend CI to run contract, security, runtime, fixture, Web UI, release, and bounded E2E gates in .forgejo/workflows/ci.yml, .forgejo/workflows/validation.yml, and .forgejo/workflows/hacs.yml
- [x] T137 [US10] Add version/source-revision/architecture/public-mirror evidence gates and coordinated App/Core release checks in .forgejo/workflows/mirror-public.yml and tools/verify-ghcr-image.py
- [x] T138 [US10] Add update migration, rollback, artifact provenance, and live-canary evidence checks in docs/RELEASE.md and tests/test_release_acceptance.py (checks implemented; candidate canary execution remains T149)
- [x] T139 [US10] Update release metadata, changelog, App/Core versions, and public repository metadata for the first feature-complete release in app/CHANGELOG.md, README.md, hacs.json, repository.yaml, and docs/PUBLIC_REPOSITORY.md

**Checkpoint**: A maintainer can reproduce local validation, publish a
coordinated release, and prove the artifact installed by users matches the
tested source revision.

## Phase 13: Polish and cross-cutting completion

**Purpose**: Close traceability, documentation, quality, and release gaps after
all user stories are implemented.

- [x] T140 [P] Reconcile every FR/SC/acceptance scenario to implementation and test files in specs/001-ha-switchboard-completeness/traceability.md
- [x] T141 [P] Run a repository-wide placeholder, dead-option, broad-exception, secret, and unbounded-retry audit in tools/check_release_boundary.py and tests/test_quality_audit.py
- [x] T142 [P] Rewrite the primary installation, App-versus-integration, Assist placement, token, privacy, fallback, scan, and troubleshooting guide in ./README.md
- [x] T143 [P] Rewrite App option descriptions, security model, Web UI, logs, backups, local development, and failure recovery in app/DOCS.md
- [x] T144 [P] Update standalone deployment and HACS integration guidance in docs/PUBLIC_REPOSITORY.md and standalone/compose.yaml
- [x] T145 [P] Update release acceptance, rollback, live-proof, artifact-provenance, App security, and external-acceptance guidance in docs/RELEASE.md
- [x] T146 Add final App/Core contract compatibility check and version policy in app/config.yaml, custom_components/ha_switchboard/manifest.json, pyproject.toml, and app/ha_switchboard/__init__.py
- [x] T147 Add final static checks for response-language prohibition, secret redaction, raw-ID boundary, and documentation drift in tests/test_quality_audit.py
- [ ] T148 Run the complete quickstart acceptance guide and record sanitized evidence in specs/001-ha-switchboard-completeness/quickstart.md (source, provider, preserve-first lifecycle, public mirror, HACS, Hassfest, GHCR, and exact published-image runtime evidence are recorded in `evidence/release-v0.2.1-2026-09-22.md`; installed-pair migration/rollback and AppArmor portions remain)
- [ ] T149 Complete source, image, runtime, HACS, Hassfest, mirror, GHCR, and live-canary release gates from specs/001-ha-switchboard-completeness/contracts/release-validation.md (the source, workflow, public mirror, GitHub Release, HACS, Hassfest, exact multi-architecture GHCR provenance, and isolated published-image runtime gates pass for `v0.2.1`; the installed public App/Core migration/rollback pair and AppArmor enforcement remain)
- [x] T150 Review all external HACS/App repository/provider dependencies and record pending acceptance separately in docs/RELEASE.md (external acceptance remains a release gate)
- [ ] T151 Publish the feature-complete release only after protected-master ancestry, public mirror, tag, image digest, architecture, and live App/Core evidence agree in .forgejo/workflows/mirror-public.yml (`v0.2.1` is published and its public artifact gates pass; the checklist remains open until the installed public App/Core migration, rollback, and AppArmor evidence also agree)

## Phase 14: Native Assist architecture alignment

- [x] T152 [US2] Add the Core native Assist/Conversation fast path for supported routine intents before Jev/fallback routing, with recursion exclusion and focused source tests in custom_components/ha_switchboard/native_path.py, custom_components/ha_switchboard/conversation.py, tests/test_native_conversation_gate.py, and tests/test_conversation_core_contract.py
- [x] T153 [US2] Verify native intent delegation, no provider call on native success, native misses continuing to Switchboard, and Assist-pipeline behavior inside the Home Assistant 2026.9 devcontainer with the real runtime dependency

## Historical validation snapshot (through 2026-09-20)

- Ledger state: **148 of 153 tasks checked; 5 remain open**. The checked
  tasks represent implemented source/artifacts with focused evidence; they do
  not imply that the public release gates are complete.
- Source evidence: the latest `python3 -m pytest -q` passes **474 tests with 4
  expected skips**. Two skips require the Home Assistant 2026.9
  runtime/config-flow dependency; the other two are opt-in live follow-up and
  native-miss probes. The focused provider/Web UI hardening suite passes **48
  tests**; the current release/quality/provider regression subset passes **39
  tests**; the expanded release/provenance suite passes **46 tests**; and the
  focused restart/follow-up/provenance suite passes **54
  tests with 2 opt-in skips**. The opt-in live follow-up probe passes with its
  unavailable second-user/natural-TTL gates reported explicitly. Compile, quality,
  release-boundary, shell-syntax, and whitespace checks pass.
- Release-source evidence: the focused release/boundary/local-dev/workflow
  suite passes (**24 tests**), the broader release/provenance checks pass
  (**46 tests**), and the sanitized public export contains **207 tracked / 119
  regular files** and passes its boundary check. The release workflows now
  enforce the `app/CHANGELOG.md` version marker, Hassfest-compatible
  conversation-agent translations, and the bounded App-image E2E gate before
  tag publication. These checks do not close the external publication gates.
- Preserved local runtime: the existing Supervisor/Core volume remains intact;
  the read-only startup and restart-cycle checks see the `hassio` entry,
  conversation agent, 28 fixture entities, 28 active capabilities, and no
  pending profile sections. A preserve-first App-only rebuild was performed;
  no reset, volume removal, or Core restart was performed in this pass.
- Live fixture evidence: the bounded profile scan settled, the operation
  matrix verified 24 of 24 rows, native script/scene surfaces stayed outside
  the Switchboard capability set, and the native `Switchboard` Assist pipeline
  changed/restored a fixture light with a zero Jev diagnostic delta. The
  bounded native-miss probe completed one Assist run through exactly one
  Switchboard gateway result without recursion.
- Follow-up evidence: deterministic tests now cover same-conversation,
  cross-user, TTL, cancellation, and one-shot replay boundaries. The live
  fixture proves same-conversation reuse, cancellation, and replay safety;
  a second user token and natural TTL expiry remain intentionally unrun.
- T148 now has separate sanitized local evidence records at
  `specs/001-ha-switchboard-completeness/evidence/local-quickstart-2026-09-20.md`
  and `specs/001-ha-switchboard-completeness/evidence/local-checks-2026-09-20.md`,
  plus the live-gate readiness record at
  `specs/001-ha-switchboard-completeness/evidence/live-gate-readiness-2026-09-20.md`,
  plus the external validation record at
  `specs/001-ha-switchboard-completeness/evidence/external-validation-2026-09-20.md`,
  `specs/001-ha-switchboard-completeness/evidence/provenance-checks-2026-09-20.md`,
  and `specs/001-ha-switchboard-completeness/evidence/t149-t151-provenance-gate-audit-2026-09-20.md`.
  It remains open because the complete matrix, restart/rotation, AppArmor,
  provider, and external-release portions were not all run.
- Remaining gates are intentionally not checked: T059 lacks a second live HA
  user and natural TTL-expiry run; T084 lacks the explicitly authorized
  App/Core restart cycle; T148 lacks complete quickstart lifecycle/provider
  acceptance; T149 and T151 require public mirror, GHCR, HACS, protected-master,
  and live-canary proof. Hassfest is now proven locally against the pinned
  container and scoped public export; that does not establish public-mirror
  or release acceptance. HACS remains credential- and public-repository-gated.
  The read-only provenance check in
  `specs/001-ha-switchboard-completeness/evidence/provenance-checks-2026-09-20.md`
  also found the public `v0.2.0`/GHCR revision differs from this local
  candidate, so no publication claim is made from the existing public artifact.
- Delegated-agent rule: workers return on completion, failure, or attention;
  the coordinator uses one event-driven watcher per group and does not poll
  repeatedly or reset the local Home Assistant environment to unblock work.
- Latest follow-up hardening: the opt-in native-miss harness now accepts only
  the disposable local gateway root (no production host, alternate port,
  path, credentials, query, or fragment), and its regression test is included
  in the current source result. T059 now also supports explicitly supplied
  second-user and natural-TTL opt-ins without changing the safe default or
  persisting credentials. The current source result is 512 tests with 4
  expected skips; the preserve-first/local-acceptance focused suite passes
  32 tests with one opt-in live skip.
- Latest multi-target/UI hardening: explicit light, switch, and fan on/off
  batches can target the whole exposed domain, one unambiguous known area,
  floor, or label, or one validated named Home Assistant group while retaining
  the 32-target, preflight, availability, and sequential-execution bounds. The
  App dashboard now includes keyboard landmarks, live status announcements,
  diagnostic-log semantics, and busy/disabled state. Atomic, toggle, and
  parameterized batches remain unsupported; browser-level accessibility
  inspection remains open.
- Latest acceptance hardening: the legacy `supervisor_read_only` value is
  covered as migration-only, named fixture-group selection has a sanitized
  deterministic acceptance path, and local development/image helpers now fail
  closed when bounded timeout support is unavailable. Live restart, provider,
  and external-release evidence remains intentionally open.
- Latest provider/deployment hardening: invalid Jev parameters now enter the
  configured bounded OpenAI-compatible fallback path, fallback proposals may
  supply bounded typed scalar parameters for gateway validation, the
  standalone Compose model has a credential-free bounded smoke validator, and
  Core diagnostics expose the last reconcile trigger (`startup`, `manual`,
  `invalidation`, `recovery`, or `periodic`). The current source result is
  **512 passed, 4 skipped**; these changes do not close the live provider or
  external-release gates.
- Latest recovery hardening: the authorized restart path now requires a
  strict boolean opt-in, rejects malformed or unsuccessful non-empty Core
  restart evidence, and has preserve-first regression coverage. The protected
  App/Core cycle itself remains intentionally unrun.
- Latest provenance hardening: GHCR verification now requires exact
  descriptor/child-manifest and config-blob response digests, and release
  workflow tests enforce GHCR verification before App E2E and publication.
  External registry, mirror, and canary evidence remains open.
- Latest App/UI hardening: the App entrypoint rejects non-canonical listener
  ports outside `1..65535` without shell integer overflow, and the dashboard
  diagnostics view now provides redacted guidance, counts, explicit empty/error
  states, and a clear-filters action. AppArmor remains unproven on WSL.
- Requirements-quality status is separate from implementation status:
  `checklists/completeness.md` is now **57 of 57 checked**. The final five
  criteria were closed against the current migration behavior, reviewed
  bounds, supported-domain exclusions, and user-facing App configuration
  descriptions.

## Current validation snapshot (2026-09-21)

- Reviewed source candidate: coordinated v0.2.1 metadata across the App,
  gateway, Core integration, packaging, and documentation authorities.
- Full source validation passes: **512 passed, 4 expected skips**. The focused
  provider/release/preflight regression slice passes **48 tests**.
- `check_release_boundary.py --versions`, `check_release_boundary.py
  --quality`, the release boundary check, the
  coordinated source-version check, compilation, shell syntax, and whitespace
  checks all pass.
- The latest hardening wave adds fail-closed HTTP fallback endpoint/body/
  response validation, bounded structured-output compatibility retry,
  malformed typed-proposal handling, coordinated release version enforcement,
  exact GHCR index/child/config media-type and digest checks, an event-driven
  preserve-first restart watcher, and a read-only live-gate preflight for
  T059/T148.
- T059, T148, T149, and T151 remain unchecked. The bounded local closeout is
  recorded in `evidence/local-closeout-2026-09-21.md`; the published v0.2.1
  readback is recorded in `evidence/release-v0.2.1-2026-09-22.md`. The
  published artifact and isolated image canary do not substitute for the
  installed public App/Core migration, rollback, or AppArmor gates.

- Latest local acceptance: the preserve-first App/Core restart cycle completed
  with the existing Supervisor volume, config entry, Conversation agent, 28
  fixture entities, options, and settled profile unchanged. The local App was
  updated through Supervisor to source candidate `0.2.1`; its installed
  low-risk Assist control and bounded multi-device control both completed.
  This is installed disposable-canary evidence, not public image or AppArmor
  evidence.
- Latest provider acceptance: the OpenAI-compatible adapter now retries once
  without the optional JSON-schema hint after a bounded HTTP 400, accepts only
  the offered opaque capability ID, discards bounded typed-proposal
  explanations, and the Gateway confirmation boundary is covered for lock and
  cover operations. Jev refusals can use one eligible fallback proposal, which
  re-enters the same validation and confirmation gates. The installed
  provider-backed Assist probe proved same-conversation confirmation,
  cancellation, and one-shot replay; shallow continuation metadata avoids the
  Core nested-state limit. A second live user and natural-TTL expiry remain
  explicitly open.

## Dependencies and Execution Order

### Phase dependencies

- Phase 1 has no implementation dependency and establishes baseline/fixtures.
- Phase 2 depends on Phase 1 and blocks every user-story phase.
- P1 stories US1-US6 depend on Phase 2. US1 and US6 establish lifecycle
  integration; US2-US5 can be developed in parallel after their contract
  fixtures exist, but final integration follows US1/US6.
- P2 stories US7-US10 depend on the relevant P1 contracts. US7 can proceed
  alongside US8/US9; US10 consumes the final interfaces from every story.
- Phase 13 depends on all required user stories and is the publication gate.

### User-story dependencies

- US1 depends on foundational auth, discovery, config, and compatibility
  contracts; it is the MVP installation slice.
- US2 depends on US1's conversation registration and US6's active-profile
  contract, but its unit/contract tests are independently runnable.
- US3 depends on US2's execution response model and US6's context discovery.
- US4 depends on US2's result kinds and US3's bounded target model.
- US5 depends on foundational provider contracts and can be developed in
  parallel with US3/US4, but end-to-end delegation integrates with US4.
- US6 depends on foundational profile contracts and must be live before
  write-path acceptance is declared.
- US7 depends on the status/diagnostic contracts from Phase 2 and the scan
  contract from US6.
- US8 depends on the final capability contract from US3/US6.
- US9 depends on foundational security and the runtime behavior of US1/US5.
- US10 depends on the final contracts and fixture behavior of US1-US9.

### Parallel execution opportunities

- T007-T010 and T017-T020 can run in parallel after baseline setup.
- US1 discovery/config-flow tests, US2 response tests, and US5 provider-schema
  tests can run in parallel once shared contracts are stable.
- US3 batch implementation, US4 conversation-context implementation, and US7
  static Web UI work use mostly separate files and can run in parallel.
- US8 fixture/matrix work and US9 deployment/security tests can run in parallel.
- Documentation tasks T142-T145 can run in parallel after the final behavior
  matrix is settled; each must be reviewed against the source contracts.

## MVP scope

The MVP is User Story 1 plus the Phase 2 foundation and the already-supported
read-only/single-device path from User Story 2. It is only demo-ready when the
installation/config-flow, active-profile, Assist selection, safe read-only
answer, and one verified low-risk control pass. User Stories 3-6 are required
for the feature-complete release; User Stories 7-10 are required for a
supportable, publishable release.

## Implementation strategy

1. Preserve the current local Supervisor/Core volume and capture the 0.2.0
   baseline.
2. Implement and test contracts/security/diagnostics before expanding behavior.
3. Deliver US1 and the active-profile lifecycle as the first live slice.
4. Add ordinary controls, batches, parameters, and follow-up context while
   keeping all writes behind Core validation.
5. Add provider adapters and Web UI observability only through typed contracts.
6. Expand fixtures and capability matrix before rewriting final documentation.
7. Run the full release contract, then publish a coordinated App/Core artifact
   set with independent live proof.

## Notes

- Every task uses the required checklist format, has a sequential ID, and names
  at least one exact repository path.
- [P] means the task can be worked in parallel without editing an incomplete
  dependency's file.
- Test tasks are included because the feature specification explicitly requires
  acceptance, security, runtime, and release validation.
- No task authorizes destructive local-environment reset; any task touching
  volume removal must preserve the explicit guard and verified snapshot rule.
