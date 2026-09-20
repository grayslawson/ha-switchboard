# Diagnostics and Web UI Contract

## Dashboard model

The ingress Web UI consumes a redacted status object containing:

- liveness and readiness
- profile freshness, revision prefix, capability count, warning count
- last scan trigger, duration bucket, and outcome
- Core integration connection and config-entry state
- Jev configured/compatible/blocked state
- fallback enabled/eligible/healthy state by route class
- safe version and source revision prefix

Secrets, raw URLs containing credentials, raw entity IDs, utterances, and
provider response bodies are never returned.

## Scan action

The scan control is authenticated by Supervisor ingress and requests the Core
integration's scan through the approved gateway boundary. It displays idle,
queued, running, active, failed, and unavailable states. It cannot start
unbounded concurrent runs and reports the existing run when one is active.

## Log model

The log view supports bounded pagination and filters for severity, event kind,
correlation ID, route class, and outcome. Each entry has timestamp, safe event
code, redacted summary, latency/count fields, and next action. It never renders
raw exception text or arbitrary provider content.

## Configuration help

Every visible option has a plain-language description, safe default, credential
warning, privacy impact, valid values/range, restart/rescan behavior, and a
link to the relevant installation or troubleshooting section. Secret inputs are
write-only and are never hydrated into browser state.

## Accessibility and failure states

Controls have accessible names and keyboard order. Status is communicated by
text/icon and color together. Loading, empty, stale, unavailable, unauthorized,
and server-error states are distinct and actionable.
