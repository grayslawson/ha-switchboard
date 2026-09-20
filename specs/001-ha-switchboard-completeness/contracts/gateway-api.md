# Gateway API Contract

The App gateway is an HTTP boundary between the Core integration and the
decision/provider layer. JSON objects are versioned, bounded, and fail closed.
Home Assistant credentials and raw entity IDs remain Core-local.

## Authentication and common rules

- Health and readiness responses contain only non-sensitive liveness state.
- Profile, assist, scan, app-status, and diagnostics endpoints require the
  configured gateway bearer token.
- Requests use JSON content type, a bounded body size, and an allowed method.
- Every mutating request includes a request/correlation identity where a retry
  could repeat work.
- Error objects contain stable code, safe message, retryability, and
  correlation ID. They do not include exception text, credentials, URLs with
  secrets, raw utterances, entity IDs, or provider bodies.
- 401 means missing/invalid token; 403 means valid identity but disallowed
  operation; 409 means stale generation/conflicting scan; 413 means size bound
  exceeded; 422 means schema/policy validation; 429 means bounded rate limit;
  502/504 means a provider/dependency failure.

## Endpoints

| Method and path | Auth | Purpose |
| --- | --- | --- |
| GET /healthz | public | Liveness only |
| GET /readyz | public, non-sensitive | Readiness summary without credentials or profile content |
| GET /v1/app/status | bearer | Redacted App options/runtime/provider status |
| GET /v1/profile/status | bearer | Active revision, freshness, counts, invalidations, and current reconcile state |
| POST /v1/profile/reconcile | bearer | Validate and atomically activate a complete sanitized snapshot |
| POST /v1/profile/invalidate | bearer | Mark one or more profile sections stale |
| POST /v1/profile/scan | bearer | Request/coalesce a Core-triggered complete scan and return run state |
| POST /v1/assist/process | bearer | Submit one bounded decision request and return a typed result |
| GET /v1/diagnostics/events | bearer | Return a bounded, paginated, redacted event list |
| POST /v1/providers/check | bearer | Check a configured route using a synthetic sanitized request |

## Reconcile request

Required object:

- schema_version
- request_id
- complete_snapshot: true
- snapshot: sanitized profile object described by profile-reconciliation.md

The gateway validates completeness, size, duplicate IDs, supported values, and
redaction before replacing the active generation. A request that is not a
complete replacement is rejected.

## Assist request

Required object:

- schema_version
- request_id and correlation_id
- conversation_id and user_scope, represented by Core-approved opaque values
- utterance or bounded intent context
- profile_revision
- bounded capability catalog/context
- privacy mode and handoff depth

The App may return answer, control, clarify, confirm, delegate, refuse, or
unavailable. A control result is still a proposal until the Core integration
validates, executes, and verifies it.

## Assist result

- schema_version
- request_id and correlation_id
- result_kind
- safe response text or next action
- zero or more opaque capability IDs
- typed parameters, if present
- profile revision used
- provider route class and bounded diagnostic code
- confirmation requirement and pending-context hint, if present
- no raw Home Assistant identifiers or secrets

## Compatibility

Unknown schema versions, required fields, result kinds, capability references,
or parameter types are rejected with a stable error. Optional unknown fields may
be ignored only when the version contract explicitly permits it. The gateway
and Core integration must advertise compatible schema versions during setup.
