# Feature Specification: HA Switchboard Feature Completeness

**Feature Branch**: `codex/fix-apparmor-runtime`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Use Spec Kit to create a constitution, plan, tasks, and checklist for HA Switchboard. Include everything left to implement for the project to be 100% feature complete."

## Definition of Done

For this specification, “100% feature complete” means that the documented
primary user journey works end to end and every advertised option has a real,
tested behavior. It does not mean that Home Assistant must accept the project
into the default HACS catalog or the official App repository; those are
external review outcomes. The project is complete when those external reviews
can be requested without known source, packaging, security, or documentation
gaps.

## User Scenarios & Testing

### User Story 1 - Install and connect Switchboard (Priority: P1)

A Home Assistant user installs the Switchboard App, installs the companion Core
integration, configures the gateway, and selects the Switchboard conversation
agent in an Assist pipeline without copying files between the App and Core
installation or guessing which credential belongs where.

**Why this priority**: Without a reliable installation and connection path,
none of the product's control, fallback, or diagnostic features are usable.

**Independent Test**: Starting from a clean disposable Home Assistant fixture,
install the App and integration through their documented paths, accept
Supervisor discovery or complete the manual flow, select the agent in an Assist
pipeline, and reach an active profile without editing YAML or copying the
integration into the App.

**Acceptance Scenarios**:

1. **Given** a supported Home Assistant OS/Supervised installation, **when** a
   user adds the App repository and installs Switchboard, **then** the App is
   listed, starts, exposes its Web UI through Supervisor ingress, and reports
   a truthful liveness and readiness state.
2. **Given** the App is running and advertising discovery, **when** the user
   accepts the discovered Core integration flow, **then** the config entry is
   created with the discovered endpoint and the user-provided gateway token,
   and no secret appears in the title, log, or diagnostic state.
3. **Given** discovery is unavailable, **when** the user enters the App URL and
   token manually, **then** the integration validates both health and the
   authenticated profile boundary before creating the entry and explains
   invalid URL, authentication, and unavailable-gateway errors.
4. **Given** the integration is configured, **when** the user opens an Assist
   pipeline's conversation-agent selector, **then** HA Switchboard is offered
   as a selectable agent and the setup documentation explains the exact path.
5. **Given** an existing installation is upgraded or restarted, **when** the
   App and Core integration reconnect, **then** configuration and the last
   valid profile remain intact and the system does not silently return to an
   unconfigured state.

### User Story 2 - Use Assist for ordinary home control (Priority: P1)

A user speaks or types a request through Home Assistant Assist and receives a
useful answer, read-only state result, clarification, confirmation request, or
verified control result. Clear built-in requests use Home Assistant's native
Conversation/Assist intent path first. Requests that native handling does not
claim continue through Switchboard's bounded read-only, Jev, clarification,
confirmation, or fallback paths while Home Assistant remains the authority
that executes every device change.

**Why this priority**: This is the product's core value: a dependable natural
language layer in front of normal Home Assistant control surfaces.

**Independent Test**: With the fixture profile current, run read-only, single
device, parameterized, ambiguous, confirmation-required, and unsupported
requests through the conversation entity and compare the returned result and
Home Assistant state with the acceptance matrix.

**Acceptance Scenarios**:

1. **Given** a current profile and a uniquely identified exposed device,
   **when** the user asks for a clear built-in routine action, **then** Core
   first offers the request to Home Assistant's native intent handler. A native
   match completes without a Jev or fallback call; requests not claimed by the
   native handler continue through Switchboard, where Core validates the
   bounded capability, Home Assistant executes it, and the response states the
   verified result.
2. **Given** a current profile, **when** the user asks for a read-only state
   question, **then** Switchboard answers from Core-owned current state without
   sending unnecessary Home Assistant identifiers to a hosted provider.
3. **Given** multiple matching devices, **when** the user asks for an action
   without enough identifying detail, **then** Switchboard asks a bounded
   clarification question that names safe user-facing choices and performs no
   write.
4. **Given** a risky action such as unlocking, opening, or changing a protected
   setting, **when** the user requests it, **then** Switchboard asks for an
   explicit confirmation before execution and never treats the original request
   as confirmation.
5. **Given** a provider returns an unknown capability, invalid parameter, stale
   revision, or unsupported route, **when** Core evaluates the result, **then**
   no write occurs and the user receives a specific next step rather than the
   exact generic phrase “I could not safely complete that request.”
6. **Given** a request cannot be completed by the configured fast path, **when**
   no eligible fallback is available, **then** the response explains whether
   the issue is ambiguity, unavailable data, unsupported scope, or provider
   configuration and suggests a supported alternative.

### User Story 3 - Control groups and multiple devices (Priority: P1)

A user can address a bounded set of devices by plural wording, area, label, or
Home Assistant group and receive per-target verification without Switchboard
claiming atomicity that Home Assistant cannot provide.

**Why this priority**: Multi-device requests are a normal home-control
workflow; supporting only one device makes the conversation agent impractical.

**Independent Test**: Use fixture areas, labels, groups, and mixed availability
to run on/off, toggle, and other supported batch operations, including a
mid-operation failure, and inspect both device state and the response report.

**Acceptance Scenarios**:

1. **Given** a bounded group of exposed compatible devices, **when** the user
   asks to turn all of them on or off, **then** every target is preflighted,
   each allowed target is processed, and the response reports verified success
   and any partial outcome by user-facing target name.
2. **Given** a batch contains an unavailable, unexposed, unsupported, or
   confirmation-required target, **when** the batch is requested, **then** the
   system does not silently skip it and either asks for confirmation or reports
   that no unsafe member was changed.
3. **Given** a batch exceeds the configured safety bound, **when** the user
   requests it, **then** Switchboard refuses before execution and offers a
   narrower area, label, or group selection.
4. **Given** one target fails after earlier targets have been verified, **when**
   the response is returned, **then** it explicitly reports partial completion,
   never reports all-success, and provides a retry-safe summary.
5. **Given** a batch request is retried with the same request identity, **when**
   the retry arrives within the idempotency window, **then** it does not repeat
   a completed non-toggle action.

### User Story 4 - Understand values and continue a conversation (Priority: P1)

A user can set bounded values such as brightness, volume, temperature, or HVAC
mode and can answer a clarification or confirmation in the next Assist turn
without restarting the request.

**Why this priority**: Parameter extraction and follow-up state are required for
natural conversation; otherwise Switchboard only handles a narrow subset of
commands.

**Independent Test**: Run parameterized requests, invalid values, clarification
answers, confirmation answers, expired pending actions, and concurrent
conversation IDs through a fixture Assist pipeline.

**Acceptance Scenarios**:

1. **Given** a supported operation with a bounded numeric or enumerated value,
   **when** the user supplies that value in natural language, **then** the
   value is extracted, validated against the capability schema, and included in
   the Core execution request.
2. **Given** a value is missing or outside its safe range, **when** the request
   is processed, **then** Switchboard asks for the missing value or explains the
   allowed range and performs no write.
3. **Given** Switchboard asked which device the user meant, **when** the user
   answers with one offered choice in the same conversation, **then** the
   pending request resumes using that choice and the user is not required to
   repeat the full utterance.
4. **Given** Switchboard asked for confirmation, **when** the user says a clear
   affirmative or negative response in the same conversation, **then** the
   pending action is executed once or cancelled, respectively.
5. **Given** a pending clarification or confirmation expires, belongs to a
   different user, or has already been consumed, **when** a follow-up arrives,
   **then** it cannot authorize an action and the user receives a new bounded
   prompt.

### User Story 5 - Fall back to a capable model safely (Priority: P1)

A user can configure an eligible fallback model through OpenRouter or another
typed endpoint for requests that Jev cannot answer, while Switchboard retains
privacy, cost, capability, confirmation, freshness, execution, and verification
controls.

**Why this priority**: The product must remain useful for open-ended requests;
fallback is a controlled continuation of the request, not a second unrestricted
Home Assistant agent.

**Independent Test**: Configure an OpenRouter chat fallback and a typed HTTP
fallback in separate fixture runs, exercise eligible prose and typed proposals,
then inject malformed, over-budget, unauthorized, and unavailable responses.

**Acceptance Scenarios**:

1. **Given** a hosted fallback is configured and the privacy policy explicitly
   permits it, **when** Jev selects delegation, **then** the fallback receives
   only the bounded sanitized request, capability catalog, allowed context, and
   route policy.
2. **Given** the fallback returns bounded prose, **when** no device action is
   required, **then** Switchboard returns that prose with a route and latency
   diagnostic that does not expose secrets or raw entity IDs.
3. **Given** the fallback returns one typed capability proposal, **when** the
   proposal is received, **then** it re-enters freshness, allowlist, parameter,
   confirmation, idempotency, execution, and verification checks before any
   write.
4. **Given** the fallback attempts to name a provider, invent a capability,
   issue arbitrary service data, or bypass confirmation, **when** the proposal
   is validated, **then** it is rejected and the user receives an actionable
   bounded response.
5. **Given** multiple fallback routes are configured, **when** the first route
   is unavailable or disallowed by privacy/cost policy, **then** Switchboard
   selects the next eligible route without looping or exceeding the handoff
   limit.
6. **Given** fallback is disabled, privacy is too restrictive, or all routes
   fail, **when** delegation is requested, **then** Switchboard explains the
   missing configuration or temporary failure and never claims a device action
   occurred.
7. **Given** a fallback provider is configured with an invalid endpoint,
   unsupported response schema, excessive latency, or an unsafe redirect,
   **when** it is tested or selected, **then** it is marked unavailable and the
   request fails closed with a diagnostic event.

### User Story 6 - Keep the capability profile current (Priority: P1)

The integration builds a complete sanitized profile on startup, updates it when
Home Assistant registries or relevant Assist surfaces change, and lets an
operator request a scan from the App Web UI.

**Why this priority**: Decisions are only safe when they use current exposure,
availability, and service information.

**Independent Test**: Start the fixture with entities and services, verify an
initial reconcile before the refresh interval, mutate entity/device/area/label
registries and state, trigger a manual scan, interrupt a reconcile, and inspect
profile status and execution behavior during each transition.

**Acceptance Scenarios**:

1. **Given** the Core integration starts while the App is reachable, **when**
   the startup lifecycle completes, **then** it performs a complete profile
   reconciliation rather than waiting for the periodic refresh timer.
2. **Given** Home Assistant reports a relevant registry, exposure, service,
   Assist-surface, reconnect, or restart change, **when** the change is
   observed, **then** affected sections are invalidated and one complete
   replacement snapshot is reconciled atomically.
3. **Given** an operator opens the Web UI, **when** they choose “Scan Home
   Assistant now,” **then** one bounded scan is requested, progress and outcome
   are visible, concurrent scans are coalesced or rejected clearly, and the
   last successful profile remains usable until replacement is valid.
4. **Given** a snapshot is incomplete, malformed, oversized, or interrupted,
   **when** reconciliation fails, **then** the old profile is not replaced by a
   partial snapshot and writes are blocked when freshness cannot be proven.
5. **Given** the App restarts or the Core connection drops, **when** recovery
   completes, **then** the system detects the generation change, reconciles a
   fresh snapshot, and reports the recovery state in status and diagnostics.
6. **Given** the profile contains unsupported entity or service shapes, **when**
   it is compiled, **then** supported entries remain available, unsupported
   entries are represented as warnings, and no raw Home Assistant identifiers
   cross the gateway boundary.

### User Story 7 - See and manage Switchboard state in the Web UI (Priority: P2)

An operator can understand whether Switchboard is alive, ready, current,
connected, configured, and able to delegate; can initiate a scan; and can read
diagnostic logs without seeing secrets or raw utterances.

**Why this priority**: The current minimal Web UI leaves operators guessing
whether a request failed because of profile, provider, integration, or policy
state.

**Independent Test**: Exercise healthy, stale, disconnected, provider-error,
scan-in-progress, partial-reconcile, and fallback-disabled states in the fixture
and inspect the ingress Web UI, status endpoints, and log view.

**Acceptance Scenarios**:

1. **Given** an operator opens the App Web UI through ingress, **when** status
   data is available, **then** the dashboard shows liveness, readiness, profile
   freshness, capability count, last successful scan, Core connection, Jev
   compatibility/configuration, and fallback availability without secret values.
2. **Given** a status or provider check is unavailable, **when** the dashboard
   refreshes, **then** it distinguishes unknown/unavailable from healthy and
   gives an actionable recovery message.
3. **Given** the operator opens configuration help, **when** they inspect an
   option, **then** the UI explains its purpose, safe default, privacy impact,
   credential type, and whether a restart or rescan is needed.
4. **Given** an operator opens logs, **when** requests, scans, provider calls,
   policy decisions, and executions have occurred, **then** a bounded,
   structured timeline can be filtered by level, event, correlation ID, and
   outcome and includes a redacted reason and next action.
5. **Given** a log event includes a token, API key, raw utterance, entity ID,
   or provider response body, **when** it is persisted or displayed, **then** it
   is redacted or omitted before storage and rendering.
6. **Given** a user navigates the UI with keyboard, reduced-motion settings, or
   a screen reader, **when** they use status, scan, configuration-help, and log
   controls, **then** the controls have accessible names, focus order, and
   non-color-only status indicators.

### User Story 8 - Support the advertised Home Assistant capability surface (Priority: P2)

A user can use the documented supported entity domains, operations, areas,
labels, groups, routines, and Assist surfaces, while unsupported features are
identified explicitly instead of appearing to work and failing later.

**Why this priority**: A profile that only models a narrow baseline makes the
project appear connected while leaving common Home Assistant workflows absent.

**Independent Test**: Populate the fixture with every supported entity type and
operation, expose and hide entities, exercise area/label/group selection, and
compare the generated capability catalog and execution matrix with the support
documentation.

**Acceptance Scenarios**:

1. **Given** an exposed supported entity, **when** the profile is reconciled,
   **then** its user-facing name, area/label context, availability, supported
   operations, parameter bounds, risk class, and opaque capability reference
   are represented consistently.
2. **Given** entities are hidden or no longer exposed to Assist, **when** the
   profile updates, **then** they cannot be selected or executed through
   Switchboard.
3. **Given** a supported light, switch, fan, media_player, climate, lock, cover,
   or garage entity is present, **when** a user requests a documented operation,
   **then** the operation has a typed contract, validation rules, confirmation
   policy, and post-action verification. Script and scene rows may be present for
   sanitized visibility only; their `activate` operation is explicitly excluded
   from Core execution.
4. **Given** an entity or operation is outside the supported matrix, **when** a
   user requests it, **then** Switchboard identifies the limitation and does
   not expose a misleading executable capability.
5. **Given** Home Assistant adds or changes an integration-specific attribute,
   **when** the profile is rebuilt, **then** unknown fields are bounded and
   ignored or surfaced as warnings rather than causing silent profile loss.

### User Story 9 - Run safely in supported deployment modes (Priority: P2)

An operator can run Switchboard as a Supervisor App or standalone Compose
gateway, understand the security boundary of each mode, and recover from
provider, network, or process failures without losing configuration.

**Why this priority**: Deployment safety and predictable recovery are part of a
control layer that can affect physical devices.

**Independent Test**: Run App and standalone fixture scenarios with empty and
configured options, restart the process, deny provider/network access, rotate
the gateway token, and inspect permissions, health, readiness, and persistence.

**Acceptance Scenarios**:

1. **Given** the Supervisor App is installed, **when** its manifest and runtime
   are inspected, **then** it uses least privilege, ingress-only UI access,
   scoped Supervisor self-information and discovery, non-root execution,
   declared AppArmor permissions, no host networking, and no unnecessary
   devices or broad Home Assistant API access.
2. **Given** standalone Compose is used, **when** the gateway is started,
   **then** the published port is protected by the configured token and the
   documentation clearly states that Supervisor ingress and AppArmor boundaries
   do not exist in this mode.
3. **Given** options are empty or a provider is unavailable, **when** the App
   starts, **then** it remains healthy, reports not-ready or degraded with a
   useful reason, and does not crash-loop or invent a provider configuration.
4. **Given** an operator restarts or upgrades the App, **when** `/data` is
   remounted, **then** configuration, bounded diagnostics, and the last valid
   profile survive according to the documented backup policy.
5. **Given** an unauthorized or oversized direct request arrives, **when** the
   gateway handles it, **then** it is rejected with a bounded response, does
   not disclose profile data, and does not cause unbounded work.
6. **Given** a provider redirects, times out, returns malformed data, or fails
   repeatedly, **when** the gateway retries or opens a circuit, **then** retry
   limits, backoff, timeouts, and recovery state are observable and no request
   loop occurs.

### User Story 10 - Develop, validate, publish, and update Switchboard (Priority: P2)

A maintainer can make changes in the local Home Assistant devcontainer, run
fixture and image checks without destroying existing configuration, publish the
App image and Core integration together, and verify that users can install the
resulting release.

**Why this priority**: A feature is not complete if local development is
fragile, the release artifacts drift, or users receive an image that was not
validated against the source.

**Independent Test**: Rebuild the local harness without deleting its volume,
run the complete unit/contract/runtime/E2E suite with mock entities and an
Assist pipeline, build both target architectures, run release checks, and
verify the public tag, image digest, source revision, App repository metadata,
and HACS metadata agree.

**Acceptance Scenarios**:

1. **Given** a maintainer has the repository and Docker/Podman prerequisites,
   **when** they run the documented local setup, **then** a Home Assistant
   devcontainer starts at the documented URL, preserves existing fixture data
   across rebuilds, and exposes the App in the Local Apps repository.
2. **Given** the local fixture is empty or incomplete, **when** the fixture
   setup command runs, **then** it creates representative entities across the
   supported matrix, areas, labels, groups, services, and an Assist pipeline
   idempotently without replacing unrelated user data.
3. **Given** a release candidate, **when** the maintainer runs the release
   gates, **then** source tests, App image smoke/E2E checks, Core runtime tests,
   packaging checks, security checks, workflow checks, HACS/Hassfest checks,
   and public-export checks all pass or produce an explicitly documented
   exception.
4. **Given** a versioned release is published, **when** users inspect the
   release, **then** the App manifest, Core manifest, Python package,
   changelog, public tag, image labels, multi-architecture manifest, and
   documentation all report the same version and source revision.
5. **Given** a new release is installed over an older release, **when** the App
   and integration update, **then** options are migrated safely, incompatible
   values are reported before writes are enabled, and rollback guidance is
   available.

### Edge Cases

- The App starts before Supervisor discovery is available.
- Supervisor provides an App options file that is unreadable by the non-root
  serving process.
- The Core integration starts before the App, after the App, or during an App
  upgrade.
- Discovery contains a stale hostname, port, UUID, or token and must not create
  a duplicate or unauthorized config entry.
- The gateway token is empty, rotated, mismatched, or accidentally exposed in a
  URL, log, diagnostic sensor, or error message.
- A profile snapshot is incomplete, too large, has duplicate capability IDs,
  or contains raw Home Assistant references in a field intended for hosted
  routing.
- A registry change arrives while reconciliation is in flight, or multiple
  change events arrive in a burst.
- A scan is requested while another scan is running, while the Core connection
  is unavailable, or after the App has restarted.
- A capability becomes unavailable between decision and execution.
- The same request is delivered twice, including toggle and batch operations.
- A batch includes mixed domains, unavailable members, high-risk members, or
  more targets than the configured bound.
- A user answers a clarification with an ambiguous name, an old choice, a
  different conversation ID, or after the pending context expires.
- A confirmation response is negative, malformed, repeated, or sent by a
  different user.
- A parameter is missing, outside bounds, has the wrong type, or is valid for a
  different operation.
- Jev returns a valid HTTP response with an invalid schema, unknown route, or
  an unsupported capability.
- OpenRouter or another fallback returns prose that looks like an action,
  multiple proposals, tool calls, credentials, raw entity IDs, or an unsafe
  redirect.
- Privacy mode disallows the selected route, the route is not configured, or a
  route exceeds timeout, cost, or handoff limits.
- A provider is unavailable during a read-only question versus during a
  physical-device write.
- Home Assistant returns an unknown or unavailable state after a service call,
  or verification disagrees with the requested result.
- AppArmor, container identity, filesystem permissions, or network policy
  differs between the local fixture and a real Supervisor host.
- A direct API request omits authorization, uses the wrong content type, is
  oversized, or sends an unexpected method/path.
- A release build succeeds for one architecture but fails or has a different
  image revision for the other.
- A local environment rebuild is interrupted and must resume without deleting
  the Supervisor/Core volume or fixtures.

## Requirements

### Functional Requirements

- **FR-001**: The project MUST provide one documented installation journey for
  the Supervisor App and the separate Core integration, including discovery,
  manual setup, gateway-token roles, Assist-pipeline selection, first scan, and
  recovery from each setup failure.
- **FR-002**: The App MUST remain a gateway and profile store; it MUST NOT
  execute Home Assistant services or install files into the Core
  `custom_components` directory.
- **FR-003**: The Core integration MUST remain the authority for Home Assistant
  credentials, raw entity references, exposure policy, service execution,
  confirmation handling, and post-action verification.
- **FR-004**: The conversation surface MUST support bounded read-only answers,
  supported single-device actions, explicit clarification, explicit
  confirmation, and verified results through Home Assistant Assist. Clear
  built-in routine intents MUST be offered to Home Assistant's native
  Conversation/Assist handler before Jev or a fallback provider is called.
- **FR-005**: The conversation surface MUST never emit the exact generic
  response “I could not safely complete that request.”; every unsuccessful
  result MUST identify a bounded reason and an actionable next step without
  claiming an unverified action.
- **FR-006**: The system MUST support bounded multi-device selection through
  plural requests and documented Home Assistant context such as areas, labels,
  or groups, with per-target preflight and verification.
- **FR-007**: The system MUST report partial batch outcomes honestly and MUST
  not imply transactional atomicity unless the underlying operation provides
  it.
- **FR-008**: The system MUST enforce a documented maximum batch size and
  reject or narrow requests that exceed it before execution.
- **FR-009**: The system MUST support typed, bounded parameter extraction for
  every parameterized operation in the published capability matrix, including
  numeric ranges and enumerated values.
- **FR-010**: The system MUST persist pending clarification and confirmation
  context for a bounded time, bind it to the conversation and user, consume it
  once, and prevent expired or cross-user context from authorizing a write.
- **FR-011**: The system MUST reconcile a complete sanitized profile at Core
  startup when the App is reachable, without waiting for the periodic refresh
  timer.
- **FR-012**: The system MUST subscribe to or otherwise observe all documented
  Home Assistant registry, exposure, state, service, Assist-surface,
  reconnect, and restart changes and reconcile a complete replacement profile
  after invalidation.
- **FR-013**: The system MUST provide an authenticated manual scan operation
  from the App Web UI and expose bounded progress, result, timestamp, and error
  state.
- **FR-014**: Profile replacement MUST be atomic; incomplete, malformed,
  oversized, or interrupted snapshots MUST NOT replace the last valid profile.
- **FR-015**: The gateway MUST expose truthful liveness, readiness, profile
  freshness, capability count, provider compatibility, Core connection, and
  scan state through authenticated status surfaces.
- **FR-016**: Every exposed App configuration option MUST have an implemented,
  documented behavior, validation rules, safe default, migration behavior, and
  clear privacy/security explanation. Dead options MUST be removed rather than
  presented as working features.
- **FR-017**: Fallback routing MUST support an explicit provider contract for
  OpenRouter chat completion and at least one typed HTTP provider, with a
  replaceable route registry that supports ordered eligibility, privacy policy,
  timeout, size/cost limits, and one-level handoff limits. Generic fallback
  MUST be selected only after native Home Assistant handling and Jev routing
  leave an eligible unresolved or open-ended request; provider transport
  failure MUST NOT silently turn an ordinary device-control request into an
  unrestricted model call.
- **FR-018**: Fallback providers MUST receive only the sanitized payload allowed
  by the selected privacy mode and MUST never receive credentials, raw entity
  IDs, unrestricted service data, or arbitrary Home Assistant tool authority.
- **FR-019**: Fallback prose MUST be bounded and MUST NOT be interpreted as an
  executed action; a fallback typed proposal MUST pass the same allowlist,
  freshness, parameter, confirmation, idempotency, execution, and verification
  checks as a Jev proposal.
- **FR-020**: Provider failures, malformed responses, unsafe redirects,
  privacy violations, timeouts, rate limits, and unavailable routes MUST be
  represented as bounded diagnostic outcomes with retry/backoff and no
  unbounded request loop.
- **FR-021**: The Web UI MUST provide an understandable status dashboard, manual
  scan control, configuration help, provider/fallback state, integration setup
  guidance, and a redacted structured log view.
- **FR-022**: Web UI status, help, errors, and logs MUST distinguish healthy,
  degraded, stale, unavailable, blocked, and unknown states and MUST provide a
  user-actionable recovery message for each.
- **FR-023**: Diagnostic logs MUST be structured, bounded in retention and
  response size, correlated across request/scan/provider/execution events, and
  redacted before persistence or display. Secrets, raw utterances, raw entity
  IDs, and provider response bodies MUST NOT be logged.
- **FR-024**: Web UI controls MUST expose accessible names, keyboard focus,
  non-color-only state indicators, and usable loading/error states.
- **FR-025**: The published capability matrix MUST cover each supported domain,
  operation, parameter, risk class, exposure rule, and verification rule, and
  MUST identify unsupported Home Assistant surfaces without misleading
  executable entries.
- **FR-026**: The integration MUST preserve opaque capability IDs at the App
  boundary and keep the mapping to raw Home Assistant identifiers Core-local.
- **FR-027**: The App MUST run with least-privilege Supervisor permissions,
  non-root identity, declared AppArmor access, no host networking, no
  unnecessary devices or privileges, and only the scoped Supervisor access
  required for options, self-information, and discovery.
- **FR-028**: Direct gateway endpoints MUST require the gateway token, enforce
  bounded request size and method/content-type rules, and avoid leaking profile
  or provider data on authentication failure.
- **FR-029**: Standalone deployment MUST use the same functional contracts as
  the App, require explicit network protection and token configuration, and
  document the absence of Supervisor ingress and AppArmor boundaries.
- **FR-030**: App and Core restarts, option migrations, token rotation,
  provider outages, and profile failures MUST preserve recoverable state and
  MUST not silently enable writes with stale or unknown authorization.
- **FR-031**: Local development tooling MUST load optional secrets only from
  ignored environment files or explicitly supplied environment variables,
  MUST never print their values, and MUST provide a clear environment health
  check.
- **FR-032**: Local development tooling MUST preserve the existing Supervisor,
  Home Assistant, App, configuration-entry, and fixture volume by default;
  destructive reset MUST require an explicit guard and a verified backup or
  snapshot.
- **FR-033**: The local fixture MUST create representative entities across
  every supported domain and operation, areas, labels, groups, availability
  states, registry changes, and an Assist pipeline idempotently.
- **FR-034**: The validation suite MUST include unit, contract, Core runtime,
  App image, multi-architecture, integration, fallback, security, recovery,
  and end-to-end Assist scenarios for the acceptance criteria in this
  specification.
- **FR-035**: E2E and provider probes MUST use bounded timeouts and retry counts;
  a failed dependency MUST terminate with actionable evidence rather than
  appearing to hang indefinitely.
- **FR-036**: Release automation MUST verify version and source-revision
  consistency across the App, Core integration, Python package, changelog,
  public tag, image labels, image digest, and architecture manifest.
- **FR-037**: Release automation MUST validate App repository metadata,
  Supervisor presentation/security requirements, HACS metadata, Hassfest
  compatibility, public export boundaries, and protected-master ancestry
  before publication.
- **FR-038**: Documentation MUST explain current behavior and limitations in
  plain language, including App versus integration responsibilities, Assist
  placement, Jev and fallback contracts, privacy modes, gateway tokens,
  profile scans, Web UI diagnostics, local development, backups, and
  troubleshooting.
- **FR-039**: Documentation MUST distinguish supported behavior, experimental
  behavior, compatibility targets, and external acceptance dependencies; it
  MUST NOT describe an unimplemented provider, surface, or configuration field
  as complete.
- **FR-040**: The project MUST provide a release-readiness checklist and a
  rollback/update procedure that records source, artifact, runtime, and live
  Home Assistant evidence separately.
- **FR-041**: The native Assist fast path MUST remain distinct from
  Switchboard routing: the currently supported routine intents (`HassLightSet`
  and light, switch, or fan `HassTurnOn`, `HassTurnOff`, and `HassToggle`)
  MUST be handled by Home Assistant without a provider call when native
  resolution succeeds. Unresolved, ambiguous, compound, risky, or open-ended
  requests MUST continue through the bounded Switchboard route and its Core
  execution gates.

### Current implementation boundaries used by this specification

The requirements use the following reviewed implementation boundary; these are
not promises for arbitrary Home Assistant domains or service shapes.

| Domain | Supported operations | Parameters / safety | Explicit exclusion |
| --- | --- | --- | --- |
| `light` | `turn_on`, `turn_off`, `toggle`, `set_brightness` | Brightness 0–100%; routine risk | Unsupported light services are omitted |
| `switch` | `turn_on`, `turn_off`, `toggle` | Routine risk | Other switch services are omitted |
| `fan` | `turn_on`, `turn_off`, `toggle` | Routine risk | Other fan services are omitted |
| `media_player` | `turn_on`, `turn_off`, `play`, `pause`, `stop`, `set_volume` | Volume 0–1; routine risk | Other media-player services are omitted |
| `climate` | `set_temperature`, `set_hvac_mode` | Temperature 5–35°C before per-entity bounds; HVAC mode is the entity-provided enum | Other climate services are omitted |
| `lock` | `lock`, `unlock` | Confirmation required | Other lock services are omitted |
| `cover` | `open_cover`, `close_cover` | Confirmation required | Other cover services are omitted |
| `garage` | `open_cover`, `close_cover` | Confirmation required; maps to the `cover` service | Other garage services are omitted |

Explicit plural on/off batches are limited to exposed `light`, `switch`, and
`fan` targets, with at most 32 members. Toggle batches, parameterized batches,
atomic batches, and general area/label/group semantics are excluded. Exposed
script and scene rows can be represented for visibility but have no executable
`activate` capability. Unsupported domains, operations, and unrecognized
service shapes are omitted or surfaced as warnings; they are never emulated.

### Reviewed safety and wire bounds

The following values are the current reviewed policy values, taken from
`app/ha_switchboard/limits.py` and the fallback adapters. A policy change must
update the source and this table together:

| Area | Bound |
| --- | --- |
| Gateway request / response | 64,000 bytes each; utterance 2,000 characters; text 4,000 characters |
| Provider request / response | Jev request 64,000 / response 32,000 bytes; OpenAI-compatible fallback request 64,000 / response 32,000 bytes |
| Profile and request context | 2,000 capabilities; 16 context items; 64 candidates; 32 routes |
| Diagnostics | 256 retained events; 32 fields per event; event/page text 4,000 characters |
| Batch and workers | 32 batch targets; 32 request workers |
| Retry, timeout, and rate | 2 retry attempts; gateway read timeout 10 seconds; 120 requests per 60-second window |
| Fallback response | 512 maximum completion tokens; 4,000-character prose; 64 choices; 512-character choice text |
| Fallback validation | API key 512 characters; endpoint 2,048 characters; model 128 characters; timeout 0.2–15 seconds; max tokens 1–512 |
| Handoff | One handoff level (`handoff_depth == 1`); at most 8 ordered route attempts; 5-second default handoff timeout, clamped to 0.2–15 seconds |

The Core profile adapter additionally bounds entities at 2,000, aliases at 32,
warnings at 128, service fields at 64, and observed device domains at 32.

### Current user-facing App configuration contract

The Supervisor manifest, English App translations, and `app/DOCS.md` define
these separate fields and descriptions. Secrets are entered at runtime and are
not reproduced here.

| Field | User-facing meaning |
| --- | --- |
| `ingress_only` | Keep the Web UI on Supervisor ingress; direct Core calls use the matching gateway token. |
| `gateway_mode` | `adapter_only`: Core/another adapter supplies sanitized profiles and owns Home Assistant actions. Legacy `supervisor_read_only` is migrated to this value with a warning and is not an active schema choice. |
| `jev_provider` | Select disabled, direct TypeSafe, OpenRouter Decisions, or a compatible typed Jev service. |
| `jev_endpoint` | Decision-service URL matching the selected Jev provider; OpenRouter uses its Decisions URL, not chat completions. |
| `jev_model` | Model identifier for the selected Jev route; compatible typed services may ignore it. |
| `jev_api_key` | Credential for the Jev service, separate from the Home Assistant gateway token. |
| `fallback_provider` | Optional disabled, OpenRouter, OpenAI-compatible, or typed HTTP fallback route. |
| `fallback_endpoint` | Fallback URL; OpenRouter may use its default, while typed HTTP requires a compatible endpoint. |
| `fallback_model` | Model identifier for an OpenRouter-compatible fallback. |
| `fallback_api_key` | Credential for the fallback service, configured separately from the Jev key. |
| `gateway_token` | Core-to-App bearer token, shared with the Core integration and distinct from provider keys. |
| `profile_refresh_minutes` | Interval for the Core worker's complete profile refresh; the Web UI scan is the explicit first/recovery request. |
| `privacy_mode` | `local_only`, `jev_hosted_allowed`, or `hosted_allowed`, controlling whether hosted Jev and fallback requests may receive bounded context. |

### Key Entities

- **Capability Profile**: A versioned, fingerprinted, sanitized snapshot of
  exposed Home Assistant capabilities, states, services, areas, labels, groups,
  routines, and Assist context. It has freshness, section status, warnings, and
  an atomic active revision.
- **Capability Target**: A Core-local mapping from an opaque capability ID to a
  Home Assistant entity/service operation, parameter schema, risk class,
  availability state, and verification rule.
- **Decision**: A typed Jev or fallback outcome containing route, confidence,
  ambiguity, bounded rationale, capability references, typed parameters, and
  response kind.
- **Conversation Context**: A short-lived, user- and conversation-bound record
  for clarification, confirmation, request identity, and one-time consumption.
- **Provider Route**: A configured Jev or fallback endpoint with provider type,
  model, privacy eligibility, timeout, size/cost limits, health state, and
  secret reference.
- **Reconcile Run**: A bounded profile build operation with trigger, generation,
  start/end timestamps, sections, outcome, warnings, and failure reason.
- **Diagnostic Event**: A redacted, bounded, correlated record for requests,
  scans, provider calls, policy decisions, executions, verification, and
  recovery.
- **App Configuration**: Validated runtime options for ingress, provider routes,
  privacy, refresh policy, token protection, and persistence.
- **Release Artifact Set**: The coordinated App image, Core integration,
  package metadata, release tag, changelog, manifests, and validation evidence
  for one source revision.

## Success Criteria

### Measurable Outcomes

- **SC-001**: In a clean disposable Home Assistant fixture, a maintainer can
  complete App installation, Core integration setup, Assist-agent selection,
  initial scan, and one read-only conversation without YAML edits or manual
  integration copying in at most 10 minutes using only the documented guide.
- **SC-002**: The startup path reaches an active profile or an explicit
  actionable degraded state within 60 seconds of both App and Core becoming
  reachable; it never waits for the periodic refresh interval as its first
  reconciliation.
- **SC-003**: The acceptance matrix passes for at least one clear native Assist
  request with no provider call, one read-only request, one single-device
  control, one parameterized control, one clarification, one confirmation, one
  supported multi-device control, one partial batch failure, one fallback prose
  response, one fallback typed proposal, and one refusal/error path.
- **SC-004**: 100% of automated provider-payload and diagnostic-log fixtures
  contain no gateway token, provider key, Home Assistant credential, raw entity
  ID, or raw user utterance.
- **SC-005**: 100% of writes in the E2E acceptance matrix have a current profile
  revision, allowlisted capability, valid parameters, required confirmation,
  idempotency decision, and post-action verification recorded in diagnostics.
- **SC-006**: Manual scans complete or fail with a visible bounded outcome in
  30 seconds for the standard fixture; a second concurrent scan does not create
  duplicate concurrent reconciliation work.
- **SC-007**: A restart and upgrade test preserves the App configuration,
  config entry, fixture entities, last valid profile, and documented recovery
  state across at least three consecutive restart cycles.
- **SC-008**: The security test matrix demonstrates that unauthenticated direct
  API calls, invalid tokens, oversized requests, unsafe provider responses, and
  stale-profile writes are rejected without data disclosure.
- **SC-009**: The local validation command finishes within 10 minutes on the
  supported development host, has bounded retries, and returns a nonzero exit
  status with actionable evidence for each injected failure.
- **SC-010**: A release candidate produces matching amd64 and arm64 image
  manifests whose source revision and version match the Core/App metadata,
  public tag, and changelog, with no failed mandatory release gate.
- **SC-011**: A reviewer unfamiliar with the project can answer what the App
  does, what the Core integration does, how to select Switchboard in Assist,
  which data leaves Home Assistant, how fallback works, and how to recover a
  failed install from the documentation alone.
- **SC-012**: No advertised App option, endpoint, supported domain, provider
  route, or local development command remains without either a passing
  acceptance scenario or an explicit documented external dependency.
- **SC-013**: In the runtime fixture, a clear built-in routine intent is
  handled by Home Assistant's native intent path without a Jev or fallback
  request, while a non-native request reaches the bounded Switchboard route;
  both outcomes preserve the Core-owned execution and diagnostic boundary.

## Assumptions

- Home Assistant Core and Supervisor remain the authorities for entity
  exposure, credentials, execution, and verification.
- The first complete release supports Home Assistant OS/Supervised App
  deployment and Home Assistant Container standalone deployment; other
  platforms remain compatibility targets unless separately validated.
- OpenRouter is the first hosted fallback provider, while the provider contract
  remains replaceable and supports a typed HTTP adapter for self-hosted or
  other compatible services.
- Hosted routing is opt-in and requires the corresponding privacy mode; local
  read-only operation remains possible without hosted credentials.
- Home Assistant does not provide transactional rollback for arbitrary service
  batches, so Switchboard reports partial results instead of promising atomic
  multi-device changes.
- The default safety bounds, timeouts, retention limits, and batch limits are
  conservative configuration values documented with the release and can be
  expanded only through a reviewed policy change.
- The local devcontainer uses disposable infrastructure but its Supervisor/Core
  volume is valuable test state; normal rebuilds must preserve it.
- HACS default-catalog inclusion and official Home Assistant App repository
  acceptance are external review processes and are release dependencies, not
  claims that source code can guarantee.
- Existing users may have the legacy `supervisor_read_only` option. On option
  load, the App normalizes it to `adapter_only` and emits the compatibility
  warning `supervisor_read_only_migrated_to_adapter_only`; `supervisor_read_only`
  is not an active schema choice and does not select a read-only execution
  mode. No separate read-only adapter is part of this specification.
- The user-facing response language may evolve, but it must remain specific,
  actionable, honest about partial failure, and free of the prohibited generic
  refusal phrase.
