# Research: HA Switchboard Feature Completeness

**Date**: 2026-09-20
**Scope**: Resolve design choices needed to implement the feature specification
without changing the existing local Home Assistant data.

## Baseline

The 0.2.0 source already contains a working App/Core separation, Supervisor
discovery, Core config flow, sanitized profile, startup/manual reconciliation
hooks, a native-first Assist gate, bounded batch support for a narrow operation
set, explicit TypeSafe/OpenRouter Jev adapters, OpenAI-compatible fallback
client modules, diagnostic sensors, local fixture tooling, and release
workflows. The current documented limitations are the authoritative starting
point for this plan:

- native OpenRouter Decisions only handles the current parameter-free question
  set;
- Core-local follow-up clarification/confirmation context exists, but complete
  live same-conversation Assist proof and parameter continuation remain open;
- batch support is limited and can leave partial results;
- fallback routes are configurable but optional and must be typed;
- profile coverage and Home Assistant event/discovery coverage remain partial;
- the Web UI is a status/scan surface rather than a complete operator console;
- the local E2E retry path needs bounded failure behavior;
- every App option must either acquire runtime behavior or be removed/migrated.

Evidence reviewed: README.md, app/DOCS.md, app/config.yaml,
app/ha_switchboard/{gateway,jev_client,openrouter_fallback,protocol,profile,server,web}.py,
custom_components/ha_switchboard/{config_flow,conversation,coordinator,execution,profile_adapter}.py,
tools/local-dev.sh, tools/local-fixtures/README.md, the complete tests/
suite, and .forgejo/workflows/.

## Decision 1: Preserve the App/Core authority split

**Decision**: Home Assistant Core owns credentials, raw entity IDs, exposure,
service execution, follow-up authorization, and post-action verification. The
App owns only sanitized profile state, route policy, decision orchestration,
and operator diagnostics.

**Rationale**: This is already the safest working boundary and is required by
the constitution. It also allows the App to run with homeassistant_api: false
and only scoped Supervisor access for options/self-information/discovery.

**Alternatives considered**:

- Let the App call Home Assistant services directly: rejected because provider
  failures or a compromised gateway could bypass Core exposure, confirmation,
  and verification.
- Put all model routing in a Core integration: rejected because it would move
  provider credentials and hosted payload construction into the Home Assistant
  authority process and duplicate the App's deployment role.

## Decision 1a: Use Home Assistant native Assist before Jev

**Decision**: Clear built-in routine intents take Home Assistant's native
Conversation/Assist path first. The Switchboard Core entity invokes the public
native intent helper with a filter that excludes Switchboard itself, returns a
native result without a Jev or fallback request when the helper handles it, and
routes only native misses into local read-only handling or the bounded provider
pipeline.

**Rationale**: Home Assistant already resolves ordinary commands such as a
clear light or switch action. Sending every such utterance through a remote
classifier adds latency and dependency without adding decision value. Jev is
more useful for the gray area: ambiguity, compound requests, risk and
confirmation policy, and deciding whether an unresolved request needs a
bounded fallback handoff.

**Alternatives considered**:

- Route every utterance through Jev: rejected because it duplicates native HA
  intent handling and makes provider availability part of the simple-command
  path.
- Let the native handler and Switchboard both execute the same request: rejected
  because duplicate execution and recursive conversation-agent calls are unsafe.

## Decision 2: Normalize every provider into one typed decision contract

**Decision**: Jev, OpenRouter fallback, and typed HTTP fallback must normalize
into a bounded route result containing response kind, opaque capability
references, typed parameters, confidence/ambiguity, route identity, and a
bounded reason. Fallback prose is never an execution instruction.

**Rationale**: A single proposal gate prevents the fallback path from becoming
an unrestricted second Home Assistant agent. It keeps allowlist, profile
freshness, confirmation, idempotency, and verification checks identical across
providers.

**Alternatives considered**:

- Accept arbitrary provider tool calls: rejected because arbitrary service
  names and data cannot be safely reconciled with the Core-local capability map.
- Treat all fallback output as prose: rejected because useful typed controls
  need a machine-validated proposal path.

## Decision 3: Use two explicit fallback adapters initially

**Decision**: Ship an OpenRouter chat-completions adapter for bounded prose or
one typed proposal, plus a generic typed HTTP adapter for compatible local or
hosted services. Keep the route registry replaceable and make hosted routes
opt-in through hosted_allowed privacy policy.

**Rationale**: The current project already has OpenRouter-specific code and a
typed handoff boundary. OpenRouter's native Decisions endpoint can remain the
fast Jev route, but it must not be presented as a parameter extractor until
its response contract and question set support those values. A generic typed
HTTP adapter gives users a safe path to another provider without accepting an
arbitrary Home Assistant conversation agent.

**Alternatives considered**:

- Use an arbitrary Home Assistant conversation agent as fallback: rejected;
  that agent may execute its own actions outside Switchboard checks.
- Bundle a model in the App: rejected for image size, lifecycle, hardware, and
  model-quality reasons; Jev and fallback providers remain external services.
- Use only the OpenRouter Decisions endpoint for every request: rejected until
  parameter extraction and delegation semantics are proven by a compatible
  typed contract.

## Decision 4: Make profile generations atomic and startup-first

**Decision**: Core performs a full sanitized reconciliation as soon as the App
and integration are both reachable, then schedules periodic reconciliation.
Registry, exposure, state, service, Assist-surface, reconnect, and restart
signals invalidate a generation. A complete replacement is validated and
activated atomically; failed replacements do not overwrite the last valid
profile, and writes require a current revision.

**Rationale**: Waiting for the refresh timer creates a dangerous first-use gap.
Generation checks handle events arriving during a reconcile without allowing a
profile built from stale registry data to become active.

**Alternatives considered**:

- Reconcile only on a timer: rejected because device exposure and availability
  can change immediately after startup or between timer ticks.
- Apply profile sections independently: rejected because decisions could see a
  mixed revision with stale allowlists and new state.
- Replace the profile with every partial event payload: rejected because event
  payloads are not complete snapshots.

## Decision 5: Keep clarification and confirmation state Core-local

**Decision**: Store short-lived pending context in the Core integration runtime
(or a bounded Core-owned persistence layer if restart survival is needed).
Bind it to conversation ID and user identity, store only the minimum proposal
and opaque references, expire and consume it once, and never treat a provider
response or a free-form “yes” without matching context as authorization.

**Rationale**: Core owns the conversation identity and the final action gate.
Keeping this state Core-local avoids sending authorization state to hosted
providers and prevents an App restart from accidentally authorizing a stale
write.

**Alternatives considered**:

- Store pending actions only in the App: rejected because the App does not own
  the user/conversation identity and cannot safely authorize Core writes.
- Reparse the full follow-up utterance without context: rejected because it
  loses the user's selected target and makes confirmations ambiguous.

## Decision 6: Use bounded partial-batch semantics

**Decision**: Keep the initial maximum at 32 targets. Preflight every member,
require confirmation for any risky member, execute only allowlisted operations,
verify each member, and return per-target results. Non-toggle retries use a
request identity/idempotency window; toggle is never silently replayed.

**Rationale**: Home Assistant does not provide a transaction covering arbitrary
service calls. Explicit partial reporting is more honest and safer than a
fictional rollback guarantee.

**Alternatives considered**:

- Claim all-or-nothing behavior: rejected because an unavailable device or
  mid-batch failure can leave earlier service calls applied.
- Permit unlimited groups: rejected because accidental broad requests and
  provider misinterpretations become operationally dangerous.
- Roll back by issuing inverse service calls: rejected as unsafe for toggles,
  external side effects, and devices whose state changed independently.

## Decision 7: Migrate the legacy mode to adapter-only

**Decision**: The complete release exposes only configuration options with real
runtime behavior. The current `supervisor_read_only` value is migrated at
option load to `adapter_only`, and the App emits the
`supervisor_read_only_migrated_to_adapter_only` compatibility warning. The
current schema has no `supervisor_read_only` choice, and no separate read-only
adapter is implemented or required by this specification.

**Rationale**: The current option is confusing and cannot truthfully promise a
Supervisor-owned read-only execution path. Migration is safer than breaking
existing options without explanation, while `adapter_only` preserves the
Core-owned execution boundary.

**Alternatives considered**:

- Keep the value and document that it does nothing: rejected because it invites
  unsafe assumptions and makes the configuration contract dishonest.
- Delete the key without migration: rejected because existing Supervisor
  options would fail validation or silently change behavior.

## Decision 7a: Record the reviewed implementation bounds

The requirements use the concrete bounds currently enforced by
`app/ha_switchboard/limits.py`, `app/ha_switchboard/jev_client.py`, and
`app/ha_switchboard/openrouter_fallback.py`: gateway request/response 64,000
bytes; Jev and fallback responses 32,000 bytes; 2,000 capabilities; 256
diagnostic events; 32 diagnostic fields; 32 routes; 32 batch targets; two
retry attempts; 10-second gateway reads; 120 requests per 60 seconds; and one
fallback handoff level. The fallback adapter additionally bounds requests at
64,000 bytes, prose at 4,000 characters, choices at 64, choice text at 512
characters, completion tokens at 512, API keys at 512 characters, endpoints at
2,048 characters, models at 128 characters, timeouts at 0.2–15 seconds, and
max tokens at 1–512. These are reviewed policy values, not claims that every
Home Assistant or provider path has unlimited support.

## Decision 7b: Enumerate the current capability boundary

The current executable domains are `light`, `switch`, `fan`, `media_player`,
`climate`, `lock`, `cover`, and `garage`, with the operations and parameter or
confirmation rules recorded in the specification's implementation-boundary
table. Explicit plural on/off batches apply only to light, switch, and fan
targets and are capped at 32. Script and scene rows are visibility-only;
`activate` is excluded from Core execution. Unsupported domains, operations,
and service shapes are omitted or warned, not emulated.

## Decision 7c: Enumerate the App fields

The current `app/config.yaml`, `app/translations/en.yaml`, and `app/DOCS.md`
jointly define `ingress_only`, `gateway_mode`, `jev_provider`,
`jev_endpoint`, `jev_model`, `jev_api_key`, `fallback_provider`,
`fallback_endpoint`, `fallback_model`, `fallback_api_key`, `gateway_token`,
`profile_refresh_minutes`, and `privacy_mode`. Their user-facing meanings are
captured in the specification table; provider keys and the gateway token remain
runtime secrets and are not copied into requirements evidence.

## Decision 8: Treat the Web UI as an operator console, not a second HA UI

**Decision**: Add status cards, scan action, route/configuration help,
integration setup guidance, provider compatibility state, and redacted
structured diagnostics to the ingress Web UI. Home Assistant remains the UI for
entity control and Assist pipeline selection.

**Rationale**: Operators need to distinguish App liveness, profile freshness,
Core connection, Jev compatibility, fallback eligibility, and execution
verification. Duplicating Home Assistant's entity UI would weaken the boundary
and create two sources of truth.

**Alternatives considered**:

- Add a full device dashboard to the App: rejected because Core/Home Assistant
  already owns entity display and control.
- Expose raw diagnostic logs directly: rejected because logs can contain
  secrets, utterances, IDs, or provider payloads unless redaction happens first.

## Decision 9: Preserve local data by default

**Decision**: Local dev commands may rebuild or restart the App/Core processes,
but must not remove the devcontainer or its Supervisor volume by default. A
destructive reset requires HA_SWITCHBOARD_ALLOW_DEV_RESET=1 and a verified
snapshot/backup. Fixture setup is idempotent and refuses production hosts.

**Rationale**: The local Supervisor volume contains onboarding, config entries,
fixtures, and test pipelines; losing it makes debugging slower and invalidates
runtime evidence.

**Alternatives considered**:

- Recreate the devcontainer on every test: rejected because it destroys the
  state required to reproduce integration lifecycle bugs.
- Put fixture state in the repository: rejected because Home Assistant runtime
  state is not safely represented as committed secrets or opaque database
  contents.

## Decision 10: Make release evidence multi-layered

**Decision**: Release gates separately verify source tests, local image behavior,
Home Assistant runtime behavior, metadata/Hassfest/HACS, public mirror/tag,
GHCR version/revision/architecture, and live install evidence. A commit or
successful CI job alone cannot close the release.

**Rationale**: Prior debugging demonstrated that source, staging image,
published image, public mirror, and live Supervisor state can drift. Separate
evidence prevents a narrow green check from hiding a bad published artifact.

**Alternatives considered**:

- Treat CI as the sole release proof: rejected because CI may build source that
  is not the image or mirror users install.
- Publish App and Core independently: rejected because their wire contracts
  must remain version-compatible.

## Open external dependencies

These are tracked in the plan but cannot be guaranteed by repository changes:

1. HACS default-catalog inclusion requires HACS review/acceptance.
2. Official Home Assistant App repository inclusion requires Home Assistant
   review/acceptance.
3. Provider-specific OpenRouter Decisions behavior can change upstream; the
   adapter must enforce its own schema and retain a compatible typed endpoint
   option.
