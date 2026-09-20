# Provider Routing Contract

## Route request

Every Jev or fallback adapter receives a bounded request with:

- schema version, request/correlation ID, and handoff depth
- sanitized user intent or bounded utterance
- opaque capability catalog and safe display context
- current profile revision
- allowed response kinds
- privacy mode and route policy
- parameter schemas and safety limits

No request includes gateway tokens, provider API keys, Home Assistant
credentials, raw entity IDs, arbitrary service data, or unrestricted state.

## Normalized result

Adapters return exactly one normalized result:

- answer with bounded prose
- control proposal with one or more opaque capability IDs and typed parameters
- clarify with bounded candidate choices or a missing parameter
- confirm with a safe action summary
- delegate only when another eligible route exists
- refuse/unavailable with stable reason and next action

Fallback may return bounded prose or one typed proposal, never arbitrary tool
calls, multiple independent actions, provider-selection instructions, or a
claim that Home Assistant executed a service.

## Route types

| Route | Input/output responsibility | Privacy requirement |
| --- | --- | --- |
| Jev decisions | Fast typed route selection and bounded capability/parameter result | local_only or jev_hosted_allowed according to endpoint |
| OpenRouter chat | Bounded prose or one typed proposal under a strict response schema | hosted_allowed |
| Typed HTTP | Same normalized result contract for a compatible local/hosted service | local or hosted according to endpoint and policy |

## Eligibility

A route is eligible only when enabled, schema-compatible, privacy-allowed,
within timeout/size/cost budget, and not in circuit-open state. Ordered fallback
tries each eligible route at most once per request and never exceeds one
delegation level.

## Failure contract

Timeout, transport failure, invalid JSON, invalid schema, unsafe redirect,
privacy mismatch, rate limit, and provider refusal map to stable bounded
diagnostics. Retry only idempotent provider requests with a small exponential
backoff. Never retry a device execution through a provider adapter.
