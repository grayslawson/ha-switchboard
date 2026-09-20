# Implementation Plan: HA Switchboard Feature Completeness

**Branch**: `codex/fix-apparmor-runtime` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-ha-switchboard-completeness/spec.md`

## Summary

Complete the documented HA Switchboard journey across the Supervisor App, Core
integration, Assist conversation entity, profile lifecycle, provider routing,
Web UI, local fixture, security boundary, release automation, and user-facing
documentation. The implementation keeps Home Assistant Core as the only
execution authority. The App remains a redacted decision gateway and profile
store; Home Assistant's native Conversation/Assist intent handler is the first
path for clear routine requests; Jev and fallback providers handle only the
remaining bounded routing, policy, and open-ended cases. Providers return
typed decisions or bounded prose; the Core integration maps opaque
capabilities to raw Home Assistant targets and performs validation, execution,
and verification.

The work is organized around one versioned contract set rather than independent
App and integration features. Foundational work establishes bounded request,
provider, profile, conversation-context, and diagnostic contracts. User-story
phases then add parameterized and multi-device conversation behavior, real
fallback adapters, current-profile reconciliation, operator UX, capability
coverage, and release-grade local validation. Existing local Supervisor/Core
data is preserved throughout implementation and testing.

## Technical Context

**Language/Version**: Python 3.12+ for the App gateway, Core integration, tools,
and tests; HTML/CSS/vanilla JavaScript embedded in the App Web UI.

**Primary Dependencies**: Home Assistant Core/Supervisor runtime contracts,
Supervisor App manifest and AppArmor, Python standard library, Home Assistant's
runtime `aiohttp` session, pytest, Docker/Podman, Home Assistant devcontainer,
HACS action, Hassfest, and Forgejo Actions.

**Storage**: Home Assistant config entries/entity registries remain Core-owned;
the App persists bounded redacted profile, provider-safe state, and diagnostic
events under `/data`; pending conversation context is bounded and owned by the
Core integration or its approved short-lived store. No raw Home Assistant
credentials or raw entity IDs are stored in App state.

**Testing**: pytest unit/contract tests, Home Assistant runtime tests in the
local Supervisor harness, App image smoke and E2E scripts, fixture setup and
Assist pipeline scenarios, AppArmor/manifest checks, workflow lint,
release-boundary/public-export checks, HACS validation, Hassfest, and protected
master/release artifact verification.

**Target Platform**: Home Assistant OS/Supervised App on `amd64` and `aarch64`
(`linux/amd64` and `linux/arm64` container platforms), plus standalone Docker
Compose connected to Home Assistant Container.

**Project Type**: A Python App gateway plus a Home Assistant custom integration,
standalone deployment, local fixture tooling, and release automation.

**Performance Goals**: First complete profile reconciliation within 60 seconds
of App and Core availability; standard-fixture manual scan completes or fails
with a visible result within 30 seconds; every provider request has a bounded
timeout and retry budget; local validation completes within 10 minutes.

**Constraints**: Fail closed for stale or ambiguous writes; no App-side Home
Assistant service execution; no raw IDs or secrets in hosted payloads/logs;
bounded profile/request/log sizes; least-privilege Supervisor access; no
unbounded retry loops; preserve the local Supervisor/Core volume; support a
conservative default batch bound of 32 targets unless a reviewed policy change
raises it.

**Scale/Scope**: One household per gateway, with a bounded profile of up to 512
capability rows and up to 32 targets per batch in the first complete release.
The provider contract is replaceable, but OpenRouter hosted fallback and one
typed HTTP fallback are the initial complete adapters. Official HACS/App
repository acceptance remains an external dependency.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Home Assistant owns authority and execution — PASS.** The plan keeps
  raw entity mapping, credentials, exposure policy, service calls, and
  verification in the Core integration. The App contract contains proposals and
  sanitized profiles only.
- **II. Safety and privacy are fail-closed — PASS.** Every write path includes
  profile revision, opaque allowlist, exposure, parameter, risk/confirmation,
  idempotency, and verification gates. Provider routes receive explicit
  privacy-eligible payloads and cannot bypass the Core boundary.
- **III. Contracts before adapters — PASS.** Phase 1 documents and tests the
  gateway, profile, decision/provider, conversation, diagnostics, and release
  contracts before provider and UI implementation.
- **IV. Evidence-driven testing and safe local development — PASS.** The plan
  adds focused contract tests and a disposable Home Assistant canary while
  preserving the existing Supervisor/Core volume. Reset remains guarded.
- **V. Observable, recoverable, and honest operations — PASS.** Diagnostic
  events distinguish liveness/readiness/freshness/provider/fallback/verification
  state; startup scan, manual scan, recovery, and partial batch results are
  explicit and redacted.
- **Security and Product Boundaries — PASS.** AppArmor, identity, ingress,
  redirect/request bounds, token auth, CSRF-safe browser boundaries, and secret
  handling are release-gated design inputs.
- **Development and Release Workflow — PASS.** Each user-visible change has
  documentation and fixture/live validation, with version, image, mirror, tag,
  and architecture checks before publication.

No constitutional exception or complexity waiver is required.

## Design Decisions

1. **Core-owned execution boundary**: the gateway never calls Home Assistant
   services. This preserves the established security model and lets a hosted
   provider see only opaque, bounded context.
2. **One typed proposal pipeline**: Jev, OpenRouter fallback, and typed HTTP
   fallback normalize into the same decision/proposal schema. Fallback cannot
   become an alternate tool executor.
3. **Atomic profile generations**: invalidation marks a generation stale;
   complete replacement snapshots are validated and activated as one unit. A
   failed replacement leaves the previous profile available for reads but
   blocks unsafe writes when freshness is not proven.
4. **Short-lived Core conversation context**: clarification and confirmation
   state is keyed to conversation/user identity, expires, and is consumed once.
   It is never sent to a provider as an authorization token.
5. **Bounded partial-batch reporting**: Home Assistant service calls are not
   assumed transactional. Preflight prevents known unsafe members; execution
   reports per-target verified outcomes and idempotency prevents duplicate
   retries for non-toggle actions.
6. **Explicit route registry**: provider type, endpoint, model, privacy
   eligibility, timeout, request/response bounds, and health are represented as
   one route contract. Secrets remain in runtime secret storage.
7. **Ingress Web UI plus authenticated API**: Supervisor ingress is the browser
   boundary; Core and other direct callers use bearer-token protected endpoints.
   Browser actions use same-origin protections and do not expose the gateway
   token to page scripts.
8. **Remove dead configuration**: the complete configuration contract exposes
   only options with real behavior. Existing `supervisor_read_only` values are
   migrated at option load to `adapter_only` and surfaced with the visible
   `supervisor_read_only_migrated_to_adapter_only` compatibility warning. There
   is no active `supervisor_read_only` schema choice or separate read-only
   adapter.
9. **Native Assist before provider routing**: the Core conversation entity
   gives Home Assistant's native intent handler the first opportunity for clear
   routine intents. A native result bypasses Jev and fallback; only requests
   not claimed by that handler enter Switchboard's local, Jev, or fallback
   routes. The native call uses a filter that excludes Switchboard itself so it
   cannot recurse.

## Implementation Phases

### Phase 0 — Research and baseline

- Map every requirement to current App, Core, tool, fixture, and workflow files.
- Record the current 0.2.0 behavior and known limitations as the baseline; do
  not treat prior local proof as proof of new behavior.
- Resolve the provider payload, Home Assistant conversation-context,
  Supervisor/App security, and HACS/App publishing decisions in `research.md`.
- Inventory placeholders, inert options, broad exception handlers, missing
  logging, and unbounded retry behavior for task generation.

### Phase 1 — Contracts, state, and safety foundation

- Add versioned schemas/validators for provider decisions, fallback proposals,
  profile snapshots, pending conversation context, diagnostic events, and
  release evidence.
- Harden request authentication, content types, size bounds, timeout/retry
  policy, safe endpoint validation, redaction, and bounded diagnostics.
- Add migration/validation for App options; normalize legacy
  `supervisor_read_only` to `adapter_only`, preserve the compatibility warning,
  and keep the legacy value out of the active schema.
- Add contract tests before changing story-specific behavior.

### Phase 2 — Profile and capability completeness

- Complete Core discovery of exposed entities, services, areas, floors, labels,
  groups, routines, Assist surfaces, availability, and operation metadata.
- Reconcile at startup, on all relevant registry/state/reconnect/restart events,
  and through a serialized manual scan command.
- Make profile generations, invalidation races, persistence, stale handling,
  and diagnostics observable and recoverable.
- Expand and document the supported domain/operation/parameter matrix.

### Phase 3 — Conversation and execution completeness

- Give Home Assistant's native Conversation/Assist handler the first
  opportunity for supported clear routine intents, record whether it handled
  the request, and route only misses into Switchboard without recursive agent
  calls. Verify this in the Home Assistant devcontainer.
- Add natural-language value extraction and typed parameter validation for every
  advertised parameterized operation.
- Add short-lived clarification/confirmation continuation across Assist turns.
- Expand safe area/label/group/multi-device selection with a 32-target bound,
  per-target verification, partial-result reporting, and idempotency.
- Replace generic refusal copy with reason-specific, actionable responses and
  add the full acceptance matrix.

### Phase 4 — Provider and fallback completeness

- Keep Jev focused on gray-area typed routing and policy decisions after native
  Home Assistant handling; use generic OpenAI-compatible fallback only for
  unresolved/open-ended requests or an explicit eligible delegation.
- Implement the OpenRouter chat fallback and typed HTTP adapter against the
  route contract, with bounded prose/one-proposal responses.
- Add route eligibility, ordered fallback, privacy/cost/size limits, circuit
  behavior, and one-level handoff protection.
- Add provider compatibility tests using sanitized fixtures and failure
  injection; ensure native OpenRouter Decisions limitations are either removed
  or accurately represented in the final support matrix.

### Phase 5 — Operator UX and deployment hardening

- Replace the minimal Web UI with status, scan, configuration-help,
  integration-setup, provider-health, and redacted diagnostic-log views.
- Add accessible state indicators, loading/error states, bounded polling, and
  scan concurrency feedback.
- Harden AppArmor/manifest/identity/ingress and standalone Compose behavior;
  test empty options, token rotation, restart persistence, and provider outage.

### Phase 6 — Local fixtures, documentation, and release

- Make local environment loading safe and explicit, and make all rebuild/reset
  paths volume-preserving by default with guarded snapshot instructions.
- Expand the fixture to all supported entities, areas, labels, groups, registry
  changes, provider stubs, and a dedicated Assist pipeline.
- Rewrite README, App docs, integration setup/help, release docs, and
  troubleshooting around the actual App/Core/fallback journey.
- Add final CI/release gates, run source and live canaries, publish only after
  tag/image/mirror/manifest evidence agrees, and document rollback/update.

## Rollback and Recovery

- Keep contract changes backward-compatible for one release where feasible;
  version provider/profile/diagnostic schemas and reject unknown unsafe fields.
- Migrate old App options without deleting the existing `/data`; preserve a
  backup before changing persisted schema.
- Keep the last valid profile until a new snapshot is complete, but disable
  writes when revision/freshness/authorization cannot be proved.
- Roll back App image and Core integration as a coordinated versioned set; do
  not roll back only one side of the App/Core contract.
- For local development, snapshot the Supervisor/Core Docker volume before any
  intentional removal and never use the guarded reset path as a normal rebuild.

## Project Structure

### Documentation (this feature)

```text
specs/001-ha-switchboard-completeness/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── gateway-api.md
│   ├── profile-reconciliation.md
│   ├── provider-routing.md
│   ├── conversation-execution.md
│   ├── diagnostics-webui.md
│   └── release-validation.md
├── checklists/
│   ├── requirements.md
│   └── completeness.md
└── tasks.md
```

### Source Code (repository root)

```text
app/
├── config.yaml                 # App options, Supervisor permissions, presentation
├── Dockerfile                  # versioned runtime image
├── apparmor.txt                # least-privilege runtime profile
├── run.sh                      # unprivileged process entrypoint
└── ha_switchboard/
    ├── server.py               # authenticated gateway and lifecycle endpoints
    ├── gateway.py              # decision/proposal orchestration
    ├── profile.py              # sanitized profile validation and compilation
    ├── store.py                # bounded persisted state
    ├── protocol.py             # typed wire contracts
    ├── policy.py               # privacy, risk, freshness, and route policy
    ├── jev_client.py           # Jev/OpenRouter Decisions adapter
    ├── openrouter_fallback.py  # OpenRouter chat fallback
    ├── handoff.py              # typed fallback proposal boundary
    ├── route_policy.py         # route eligibility and ordered fallback
    ├── batch.py                # bounded group proposal handling
    ├── discovery.py             # Supervisor discovery
    ├── change_monitor.py       # invalidation/monitor contracts
    └── web.py                  # ingress Web UI and operator API
custom_components/ha_switchboard/
├── config_flow.py              # Supervisor/manual setup
├── conversation.py             # Assist conversation entity/context
├── coordinator.py              # profile generations, startup scan, events
├── profile_adapter.py          # Core-owned discovery and redaction
├── capabilities.py             # operation/parameter/risk matrix
├── execution.py                # validation, service calls, verification
├── client.py                   # authenticated gateway client
├── opaque.py                   # Core-local capability mapping
├── read_only.py                # local state answers
├── sensor.py                   # diagnostic entities
└── runtime.py                  # config-entry runtime state
standalone/
└── compose.yaml
tests/
├── test_*.py                   # unit and contract coverage
├── fixtures/                   # sanitized provider/profile fixtures
└── runtime/                    # optional HA runtime assertions
tools/
├── local-dev.sh                # guarded local lifecycle
├── local-fixtures/             # idempotent fixture and Assist setup
├── app-image-smoke.sh
├── app-image-e2e.sh
├── check_release_boundary.py
├── verify-ghcr-image.py
└── ha-switchboard-export-public.py
docs/
├── RELEASE.md
└── PUBLIC_REPOSITORY.md
```

**Structure Decision**: Keep the existing App/Core/standalone split. Add typed
contracts and bounded stores inside the owning boundary, add fixture/runtime
tests beside the existing test suite, and keep public documentation and
release checks in the existing root/docs locations. Do not create a second
frontend framework or move Home Assistant credentials across the App boundary.

## Post-Design Constitution Check

- **Authority** remains Core-local: the new provider, profile, conversation,
  and Web UI contracts carry opaque references and proposals only.
- **Fail-closed safety** is explicit in the profile, provider, conversation,
  gateway, and release contracts; stale, malformed, unauthenticated, or
  unverified writes have no success path.
- **Contract-first adapters** are documented before implementation, with
  versioned error and compatibility behavior for unknown schemas.
- **Evidence and local safety** are covered by the quickstart, bounded E2E
  checks, fixture matrix, and preserve-first local lifecycle.
- **Observability and honesty** are covered by diagnostic-event fields,
  reason-specific response language, partial-batch reporting, and separate
  source/CI/live release evidence.
- **Security boundaries** include least privilege, AppArmor, ingress/token
  separation, redaction, redirect/request limits, and standalone warnings.

The post-design gate passes with no exception.

## Complexity Tracking

No constitutional violations or unexplained architectural exceptions are
planned. The provider registry, short-lived conversation context, and bounded
diagnostic store are necessary to satisfy the existing safety and completeness
definition; direct unrestricted model/tool integration was rejected because it
would violate the App/Core authority boundary.
