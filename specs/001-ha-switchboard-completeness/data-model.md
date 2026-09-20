# Data Model: HA Switchboard Feature Completeness

This model separates Core-owned identity and execution data from App-owned
sanitized decision and diagnostic data. The boundary is part of the model, not
just an implementation convention.

## Capability Profile

**Owner**: Core adapter builds it; App stores the sanitized copy.

**Purpose**: Describes the current, bounded capabilities available to the
decision layer.

**Fields**:

- profile revision: required opaque version string; changes for every complete
  replacement
- section fingerprints: bounded map for entities, services, areas, floors,
  labels, groups, routines, Assist surfaces, and state
- capability rows: bounded list of sanitized capability descriptors
- user-facing name/context: bounded display name, domain, area/label/group
  context, and supported operation names; no raw entity ID
- availability: available, unavailable, unknown, or blocked
- operation metadata: parameter schema, risk class, exposure eligibility, and
  verification kind
- warnings: bounded codes/counts, never raw provider or Home Assistant dumps
- created/activated timestamps
- freshness state: active, stale, reconciling, failed, or unavailable

**Validation**:

- complete snapshots are required for activation;
- maximum profile and field sizes are enforced;
- capability IDs are unique and opaque;
- unsupported values are rejected or converted into bounded warning codes;
- raw Home Assistant identifiers are allowed only in Core-local target maps;
- a failed replacement never replaces the active revision.

**Transitions**:

active -> stale on an invalidation, restart, reconnect, or profile generation
change; stale -> reconciling on a scan; reconciling -> active after complete
validation; reconciling -> failed on error while preserving the prior active
copy for reads; failed -> reconciling on a bounded retry/manual scan.

## Capability Target

**Owner**: Core only.

**Purpose**: Maps one opaque capability reference to the exact Home Assistant
target and executable operation.

**Fields**:

- opaque capability ID
- profile revision
- raw Home Assistant entity ID or service reference
- domain and operation
- parameter schema and normalized values
- risk class and confirmation requirement
- exposure/allowlist status
- availability and last observed state
- verification rule

**Validation**:

- target exists in the active Core registry/profile;
- operation is in the published operation matrix;
- parameters satisfy type, range, enum, and size constraints;
- high-risk operations require a matching confirmation context;
- target is not sent to the App or hosted provider.

## Decision

**Owner**: App creates a bounded provider result; Core consumes it as an
untrusted proposal.

**Fields**:

- request identity and correlation ID
- response kind: answer, control, clarify, confirm, delegate, refuse, or
  unavailable
- route ID and provider class, not a secret
- profile revision used
- zero or more opaque capability IDs
- typed parameter object
- confidence and ambiguity scores when supplied
- bounded reason/next action
- optional bounded prose
- expiration and handoff depth

**Validation**:

- unknown response kinds and fields are rejected or ignored according to the
  versioned contract;
- at most one typed capability proposal is returned from a fallback route;
- prose cannot authorize a write;
- capability IDs must exist in the Core-local map for the current revision;
- handoff depth is at most one;
- size and token budgets are enforced before storage or display.

## Conversation Context

**Owner**: Core integration.

**Purpose**: Carries a clarification or confirmation safely to one later Assist
turn.

**Fields**:

- context ID and request identity
- Home Assistant conversation ID
- authenticated Home Assistant user identity
- created and expiry timestamps
- state: awaiting_clarification, awaiting_confirmation, consumed, cancelled,
  expired
- original bounded intent summary
- candidate opaque capability IDs and safe display labels
- normalized parameters
- profile revision
- confirmation policy and one-time nonce/hash

**Validation**:

- context is matched to conversation and user;
- context TTL is bounded;
- it is consumed atomically before execution;
- expired, consumed, cancelled, or mismatched context cannot authorize a write;
- raw entity IDs are retained only in the Core-local capability map.

**Transitions**:

awaiting_clarification -> awaiting_confirmation after a unique candidate and
required confirmation are established; awaiting_clarification -> consumed for
a safe read-only answer; awaiting_confirmation -> consumed on explicit
affirmation; awaiting_confirmation -> cancelled on explicit denial;
awaiting_* -> expired at TTL; consumed/cancelled/expired are terminal.

## Provider Route

**Owner**: App configuration and route policy.

**Fields**:

- stable route ID
- provider kind: Jev decisions, OpenRouter chat, or typed HTTP
- endpoint URL
- model identifier where applicable
- secret reference/value held only by runtime secret handling
- privacy eligibility
- timeout, retry budget, response size, and cost/token budget
- enabled/disabled state
- current health: unknown, healthy, degraded, blocked, unavailable
- last compatibility-check timestamp and bounded error code
- priority/order

**Validation**:

- endpoint scheme/host policy prevents unsafe redirects and unsupported
  transports;
- hosted routes require hosted privacy policy;
- credentials are never included in status, logs, fixtures, or browser payloads;
- route-specific schemas are validated before use;
- retries and handoffs are bounded.

## Reconcile Run

**Owner**: Core coordinator with App status mirror.

**Fields**:

- run ID and trigger: startup, timer, event, manual, recovery
- profile generation before and after
- start/end timestamps
- section set and counts
- outcome: queued, running, active, failed, cancelled
- bounded warning/error codes
- correlation ID

**Validation**:

- only one active replacement per gateway/profile generation;
- concurrent manual requests are coalesced or rejected with a clear state;
- a run cannot report active until the App and Core revisions agree;
- diagnostic payloads do not contain snapshot contents.

## Diagnostic Event

**Owner**: App persistence/display; Core may emit correlated execution events.

**Fields**:

- event ID, timestamp, severity, event kind, correlation ID
- request/run ID where applicable
- bounded outcome/status code
- route class and latency bucket
- profile revision or generation
- safe counts and next action
- redacted message

**Validation**:

- retention and response limits are enforced;
- no credentials, bearer tokens, raw utterances, raw entity IDs, full provider
  bodies, or arbitrary exception text;
- fields have an allowlist and stable schema version;
- log retrieval is authenticated and paginated/bounded.

## App Configuration

**Owner**: Supervisor options and runtime loader.

**Fields**:

- ingress-only mode and gateway mode
- Jev route settings
- ordered fallback routes
- gateway token
- profile refresh interval
- privacy mode
- schema/version marker for migrations

**Validation and migration**:

- every visible option has a safe default and runtime behavior;
- invalid endpoint, model, privacy, interval, or provider combinations are
  rejected before restart;
- old inert supervisor_read_only values are migrated to adapter-only with a
  warning or rejected with actionable upgrade guidance;
- secret fields are never echoed;
- migration keeps the prior options backup and does not delete profile state.

## Release Artifact Set

**Owner**: release workflow and maintainer.

**Fields**:

- source revision and protected-master ancestry proof
- semantic version
- App manifest/image metadata
- Core manifest/package metadata
- changelog and documentation revision
- architecture manifest and image digest
- public mirror/tag/release references
- gate results and live canary evidence

**Validation**:

- all version fields agree;
- all image architectures point to the same source revision;
- public exports contain only allowlisted paths;
- mandatory checks pass before publication;
- rollback target and update notes are recorded.
