<!--
Sync Impact Report
- Version change: scaffold -> 1.0.0
- Modified principles: none; all principles are newly established.
- Added sections: Security and Product Boundaries; Development and Release Workflow.
- Removed sections: scaffold placeholders only.
- Follow-up TODOs: none.
-->

# HA Switchboard Constitution

## Core Principles

### I. Home Assistant Owns Authority and Execution

Home Assistant Core remains the source of truth for entities, exposure policy,
credentials, service execution, and post-action verification. The Switchboard
App is a decision gateway and profile store; it MUST NOT execute Home Assistant
services or copy the Core integration into `custom_components`. Every action
proposal MUST cross the Core integration boundary before it can change a
device. This separation keeps provider failures, model behavior, and gateway
bugs from bypassing Home Assistant's authority.

### II. Safety and Privacy Are Fail-Closed

The system MUST reject stale, ambiguous, unavailable, blocked, unauthorized, or
unverifiable actions. Writes MUST be bounded by an opaque capability allowlist,
profile revision, exposure policy, parameter validation, risk and confirmation
policy, idempotency protection, and post-action verification. Provider payloads
MUST exclude credentials, raw Home Assistant references, and disallowed private
state. Hosted routes MUST use explicit privacy policy and secure transport;
fallback models MUST re-enter the same proposal and execution checks. A
convenient answer MUST never weaken these boundaries.

### III. Contracts Before Adapters

The App, Core integration, Supervisor discovery, Assist conversation entity,
standalone deployment, Jev clients, fallback providers, WebUI, and release
publisher MUST communicate through explicit, versioned, typed contracts.
Unknown provider responses, unsupported parameters, schema drift, and partial
capabilities MUST produce bounded, user-understandable outcomes. Integrations
MUST be replaceable without moving Home Assistant credentials or execution
authority across the boundary.

### IV. Evidence-Driven Testing and Safe Local Development

Every behavior that crosses a process, trust boundary, or Home Assistant
surface MUST have a focused contract test and an end-to-end validation path.
Release work MUST combine static checks, unit tests, App image checks, Core
runtime tests, and a disposable Home Assistant fixture canary. Local
development MUST preserve the existing Supervisor/Core volume; destructive
environment resets require an explicit guard and a verified snapshot. A green
CI job or commit is not live proof until the requested runtime behavior is
observed.

### V. Observable, Recoverable, and Honest Operations

User-visible and operator-visible state MUST distinguish liveness, readiness,
profile freshness, provider compatibility, fallback availability, execution
verification, and partial failure. App logs MUST be structured, bounded, useful
for diagnosis, and free of secrets and raw utterances. Startup MUST reconcile a
current profile when the Core adapter is available, and manual scans, App/Core
restarts, provider errors, and invalidation races MUST recover without silently
claiming success. Documentation MUST state current limitations and must not
describe compatibility targets or experimental paths as complete.

## Security and Product Boundaries

The default deployment is least privilege: Supervisor ingress is the UI
boundary, direct Core calls use a separate gateway token, and the App does not
request broad Home Assistant API access unless a separately reviewed adapter
requires it. Secrets belong in Supervisor options, Home Assistant config-entry
storage, or runtime secret mechanisms; they MUST NOT be committed, logged,
printed in evidence, or placed in fixtures. AppArmor, container identity,
network exposure, redirect handling, request limits, and CSRF protections are
release concerns, not optional hardening.

Feature completeness means that the documented user journey works end to end:
install App, install Core integration, discover or configure the gateway,
reconcile capabilities, select the conversation agent in Assist, answer
read-only requests, execute bounded single and multi-device controls, handle
parameters and confirmation, delegate eligible open-ended requests, verify
results, diagnose failures in WebUI/logs, and update safely through CI and
public packaging. Unsupported behavior MUST remain explicitly documented until
its acceptance criteria are met.

## Development and Release Workflow

Changes MUST be made in an isolated branch and reviewed as a coherent change.
Plans MUST identify affected contracts, data, security boundaries, tests, and
rollback behavior. New user-visible behavior MUST include documentation and a
fixture or live validation scenario. The App, Core integration, Python package,
container metadata, changelog, and release tag MUST agree on version.

The release gate MUST pass compilation, focused and full tests, Home Assistant
runtime integration tests, App image smoke/E2E checks, release-boundary and
public-export checks, workflow lint, HACS/Hassfest validation, and a protected-
master ancestry check before publishing. A release is complete only after the
versioned image, public mirror, release metadata, and architecture manifests
are independently verified.

## Governance

This constitution governs feature specifications, implementation plans, task
breakdown, code review, and release decisions for HA Switchboard. A change that
violates a principle MUST either be redesigned or include an explicit written
exception with scope, risk, compensating controls, owner, and expiration.

Amendments require a pull request, an updated Sync Impact Report, a rationale,
and review of affected plans and checklists. Versioning follows semantic
meaning: MAJOR for incompatible governance changes, MINOR for new or materially
expanded principles, and PATCH for clarifications. Every feature plan MUST
include a constitution compliance check, and every release review MUST record
which gates were run and which evidence was observed.

**Version**: 1.0.0 | **Ratified**: 2026-09-20 | **Last Amended**: 2026-09-20
