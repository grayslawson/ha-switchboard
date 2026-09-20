# Jev provider access and contract research

**Owner:** Jev ecosystem research
**Research date:** 2026-09-20
**Scope:** HA Switchboard provider discovery, Jev access paths, wire contracts,
routing, security, and privacy.
**Method:** Regular web search and direct inspection of official TypeSafe and
OpenRouter documentation. No provider was called and no credential was used.

This note distinguishes vendor/API facts from reports made by community
projects. A URL that accepts JSON, returns a field named `decision`, or calls
itself “Jev” is not evidence of protocol compatibility.

## Executive recommendation

Implement three explicit adapters and keep their readiness separate:

1. **TypeSafe System One** — direct `POST https://api.typesafe.ai/v1/systemone`
   using the official typed `state`/`questions`/`answers` contract.
2. **OpenRouter Decisions** — OpenRouter's distinct alpha
   `POST https://openrouter.ai/api/alpha/decisions` contract, with an explicit
   OpenRouter model ID such as the one accepted by the current compatibility
   probe.
3. **OpenAI-compatible chat fallback** — ordinary
   `POST https://openrouter.ai/api/v1/chat/completions`, or another declared
   chat-compatible service, returning bounded prose or one validated proposal.

Do not select an adapter merely from a hostname or a generic “Jev endpoint”
field. Persist `provider_kind`, endpoint, protocol/schema version, model,
privacy class, supported output types, and probe status. An adapter is ready
only after a sanitized compatibility probe succeeds; all authentication,
timeout, non-2xx, malformed, unknown-model, and schema-mismatch results remain
unavailable or degraded rather than becoming a write authorization.

## 1. Facts verified from official documentation

### Jev/System One primitives

TypeSafe describes System One as a typed decision model. Jev accepts text-only
input represented as a string, JSON object, or array of text; it does not accept
images, audio, or video. It returns typed answers and probabilities rather than
generated prose or reasoning. The three primitives are:

| Primitive | Request shape | Answer shape | Switchboard use |
| --- | --- | --- | --- |
| `choice` | `criteria` is a map of option IDs to descriptions | `choice`, `probabilities`, `confidence` | Pick one opaque capability or route from a closed allowlist |
| `score` | `criteria` is an ordered array of levels | `score`, `legend`, `probabilities`, `confidence` | Assess an ordered risk/ambiguity rubric |
| `noul` | optional `criteria.true`/`criteria.false` | `noul` from 0 to 1 | Estimate a separately defined yes/no proposition |

Questions in one request see the same state and are evaluated independently.
Question IDs are application keys; the answer is returned under the same key.
The application composes answers and owns thresholds and consequences. A
`confidence` value is uncertainty evidence, not proof of correctness or
authorization. TypeSafe explicitly says thresholds depend on the stakes and
should be tested on the application's data.

Sources: [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one),
[state](https://docs.typesafe.ai/concepts/state),
[primitives](https://docs.typesafe.ai/primitives), and
[confidence](https://docs.typesafe.ai/confidence).

### Direct TypeSafe `/v1/systemone` contract

The official HTTP API is:

```http
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <TypeSafe API key>
Content-Type: application/json
```

Required request fields are:

```json
{
  "state": "text or a structured JSON value",
  "model": "jev-latest",
  "questions": {
    "route": {
      "type": "choice",
      "instructions": "Which allowed capability best matches the request?",
      "criteria": {
        "read_status": "Read-only status capability",
        "none": "No listed capability fits"
      }
    },
    "needs_review": {
      "type": "noul",
      "instructions": "Does this request require human confirmation?"
    }
  }
}
```

The direct response contains the resolved `model`, an `answers` map keyed by
the supplied question IDs, and `usage` with input/output token counts. A
Choice answer includes the selected option plus the full option probability
map and confidence. A Score answer includes the probability-weighted numeric
score, legend, probabilities, and confidence. A Noul answer is the yes
probability and has no separate confidence field. The direct API reference
lists `401` for authentication, `422` for invalid request bodies, `429` for
rate limiting, and `529` for temporary overload; its guidance is exponential
backoff for retryable overload/rate-limit responses.

Choice accepts up to 255 options. Score requires at least two levels and the
API accepts up to 10. These are vendor API limits, not a reason to expose a
large raw Home Assistant profile; Switchboard should send only a bounded,
sanitized capability snapshot.

TypeSafe's current model page says `jev-latest` resolves to `jev-1.13.0`, but
also warns that aliases move. It documents `GET /v1/models`, accepts a bearer
key, and recommends pinning the versioned model when thresholds were tuned to a
specific version. Rate limits are described as dynamic. Record the response's
resolved model and do not silently treat the current alias mapping as a stable
contract.

Sources: [TypeSafe API reference](https://docs.typesafe.ai/api),
[TypeSafe models](https://docs.typesafe.ai/models), and
[TypeSafe client SDKs](https://docs.typesafe.ai/sdk).

### OpenRouter Decisions contract

OpenRouter's official OpenAPI document defines a separate alpha endpoint:

```http
POST https://openrouter.ai/api/alpha/decisions
Authorization: Bearer <OpenRouter API key>
Content-Type: application/json
```

The required body fields are `model`, `state`, and `questions`. The questions
use the same `choice`, `score`, and `noul` discriminated shapes. The OpenAPI
schema also defines optional OpenRouter metadata/routing fields such as
`provider`, `session_id`, `trace`, and `user`; Switchboard must not treat these
as provider-side conversation memory or authorization state.

The documented response contains `model`, `answers`, and `usage`; the current
OpenAPI example additionally shows an `id`, `provider`, and usage `cost`. The
resolved response model may be a versioned provider model even when the request
used an alias. Preserve that metadata in redacted diagnostics.

The OpenRouter OpenAPI operation is tagged `alpha.decisions`. It is therefore a
real documented contract as of this research date, but it is not a permanent
compatibility promise. Treat path, schema, model availability, and error
behavior as probe-gated. The OpenRouter API reference also exposes model
metadata and an output-modality filter that includes `decisions`; use the
current catalog/probe to establish availability rather than assuming the
ordinary text-model catalog proves Decisions support.

Important separation:

| Request | Meaning | Must not be substituted |
| --- | --- | --- |
| TypeSafe `/v1/systemone` | Direct vendor System One evaluation | OpenRouter path or a custom `decision` envelope |
| OpenRouter `/api/alpha/decisions` | OpenRouter Decisions router | `/api/v1/chat/completions` |
| OpenRouter `/api/v1/chat/completions` | Normal chat generation | Jev typed decision inference |

Sources: [OpenRouter OpenAPI specification](https://openrouter.ai/openapi.json),
[OpenRouter API reference](https://openrouter.ai/docs/api_reference/overview),
and [OpenRouter model API documentation](https://openrouter.ai/docs/api/api-reference/models/get-models).

## 2. Credible access paths and evidence level

| Path | Evidence level | What it establishes | What it does not establish |
| --- | --- | --- | --- |
| TypeSafe official API/SDK | **Vendor fact** | Direct System One access, typed request/response, official model namespace and documented auth | That a local account is entitled, healthy, or within current dynamic limits; no live probe was made here |
| OpenRouter official Decisions API | **Gateway/vendor documentation fact** | A separately documented Decisions route and current OpenRouter model/provider metadata | Stable long-term alpha compatibility, universal model availability, or zero provider retention |
| OpenRouter chat API | **Gateway/vendor documentation fact** | Normal OpenAI-style chat transport with messages, structured outputs where the selected endpoint supports them, and optional tool-call-shaped output | That a chat model is Jev or that returned prose/JSON is safe to execute |
| `typesafe-jev-examples` | **Third-party report** | A public example project reports direct TypeSafe and OpenRouter adapters and keeps policy in code | Its live tests, pricing, waitlist, model mapping, or compatibility claims are not TypeSafe/OpenRouter guarantees |
| `HA-SystemOne` | **Third-party report** | A public HA integration claims support for hosted, self-hosted, and custom services using the System One shape | TypeSafe endorsement, server correctness, provider security, or Switchboard suitability |
| Other Jev CLIs/MCP/integrations | **Third-party report** | Useful examples of environment selection, typed screening, and bounded decision use | Any endpoint or model alias they invent or adapt; inspect their code and re-probe before reuse |

The public examples are useful design signals, especially their separation of
provider calls from deterministic policy tests. They are not evidence that a
self-hosted server implements the TypeSafe contract, that a proxy preserves
calibration, or that a model is safe for HA writes.

Sources for the third-party reports: [typesafe-jev-examples](https://github.com/rajivkuriakose/typesafe-jev-examples),
[HA-SystemOne](https://github.com/AtHeartEngineer/HA-SystemOne), and
[TypeSafe's public tool-router example](https://github.com/TypeSafeAI/typesafe-playground/blob/main/docs/tool-router.md).

## 3. Normal OpenAI-compatible chat fallback

OpenRouter documents ordinary chat at:

```http
POST https://openrouter.ai/api/v1/chat/completions
Authorization: Bearer <OpenRouter API key>
Content-Type: application/json
```

The body uses `messages` or `prompt`, a selected `model`, and optional
parameters such as `response_format` and `stream`. Non-streaming responses
normalize to an OpenAI-style object with `id`, `choices`, `created`, `model`,
and optional `usage`; each non-streaming choice has a `message`, which may
contain `tool_calls`. Streaming uses SSE chunks. OpenRouter may route a model
across providers and may fall back after provider failures or rate limits.

For a Switchboard fallback, request either bounded prose or one strict proposal
object. A proposal should contain only an opaque offered capability ID and
operation-specific, schema-validated parameters. It must never contain an HA
service name, entity ID, credential, arbitrary service data, or a provider
selection. Do not pass model-generated `tool_calls` through to Home Assistant.
Every proposal re-enters the same Core gates as a Jev result: profile
freshness, exposure, allowlist, enum/range validation, risk and confirmation,
idempotency, Core execution, and post-execution verification.

OpenRouter documents JSON Schema structured outputs via `response_format` with
`type: "json_schema"`. Support is endpoint-specific; the same model can have
providers with different capabilities, and exact schema enforcement is not
guaranteed on every endpoint. If this mode is used, set a closed schema with
`additionalProperties: false`, use `strict: true` where supported, request
`provider.require_parameters: true`, and reject anything that still fails
local validation. Structured output is a parsing aid, not an authorization
boundary.

Sources: [OpenRouter completions reference](https://openrouter.ai/docs/api_reference/overview),
[structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
and [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).

## 4. Routing, security, and privacy strategy

### Routing policy

1. Resolve deterministic local cases first: local read-only status, obvious
   bounded operations, unsupported surfaces, privacy-denied requests, and
   high-risk actions that require clarification or confirmation.
2. Send Jev a current, minimized state and a closed set of opaque capability
   IDs. Ask separate questions for route/candidate, ambiguity, risk, and
   sensitivity. Use `choice` for closed alternatives and `noul` for explicit
   yes/no propositions; use `score` only for a defined ordered rubric.
3. Compose results in Core. A provider answer can propose a route or review
   signal; only Core can resolve raw HA references, validate parameters, and
   execute.
4. Use chat fallback only when the Jev route is unavailable or insufficient,
   with one bounded handoff. Do not let the fallback choose another provider or
   recursively become an HA agent.
5. Make retry behavior contract-specific. Retry only bounded transient
   failures, with backoff and a circuit/availability state. Never retry a
   pending write blindly; preserve or consume pending confirmation according to
   an explicit Core policy, not provider behavior.

### Security boundary

- Keep API keys in runtime secret storage and out of source, evidence, prompts,
  diagnostics, and provider response logs.
- Use an explicit route registry: adapter kind, exact endpoint, protocol/schema
  version, model, timeout/size limits, supported output types, privacy class,
  and readiness state.
- Sanitize before egress. Prefer opaque capability IDs and bounded labels;
  exclude raw entity IDs, service names, credentials, full HA chat history,
  pending authorization tokens, and unrelated household state.
- Treat unknown fields, unknown capabilities, missing probabilities, invalid
  JSON, stale profile revisions, and provider disagreement as refusal or
  clarification. Never coerce a Score into an exact brightness, temperature,
  volume, or other device value without a separately tested deterministic
  mapping.
- Keep Core-local clarification/confirmation state bound to conversation and
  user identity, short-lived, revision-bound, and one-shot. An OpenRouter
  `session_id` is documented for observability grouping and is not provider
  memory; it cannot authorize an HA action.

### Privacy routing

Use explicit privacy classes such as `local_only`, `hosted_allowed`, and
`zdr_only`. For hosted calls, record route/provider/model metadata and latency
without recording raw state or full payloads.

TypeSafe's public docs say requests/responses are not used to train its model
and describe ZDR for enterprise customers, but they do not make a local
Switchboard deployment private by themselves. Confirm the account agreement,
retention terms, and ZDR entitlement before sending household data.

OpenRouter documents that it stores request metadata such as token counts and
latency, while prompt/input-output retention is opt-in at the OpenRouter layer;
the upstream provider has its own logging and retention policy. For sensitive
requests, require a route that satisfies the applicable policy, such as
`provider.data_collection: "deny"` and, where available,
`provider.zdr: true`. These controls can reduce eligible providers or fail the
request; they do not prove that a provider is safe without checking the current
provider policy. Enterprise regional routing is a separate OpenRouter feature
and should not be inferred from a normal key or model selection.

Sources: [TypeSafe legal/data handling](https://docs.typesafe.ai/legal),
[OpenRouter data collection](https://openrouter.ai/docs/guides/privacy/data-collection),
[OpenRouter provider logging](https://openrouter.ai/docs/guides/privacy/provider-logging),
and [OpenRouter privacy-aware provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).

## 5. Probe and readiness requirements

The following are concrete recommendations, not claims that the assigned
worktree already satisfies them:

| Gate | Direct TypeSafe | OpenRouter Decisions | Chat fallback |
| --- | --- | --- | --- |
| Endpoint identity | Exact `api.typesafe.ai/v1/systemone` or explicitly declared compatible origin | Exact `/api/alpha/decisions` | Exact `/api/v1/chat/completions` or declared equivalent |
| Auth check | Bearer key; do not log it | Bearer key; do not log it | Bearer key; do not log it |
| Model check | `GET /v1/models`, then pin or record resolved model | Query current model/provider capability and use accepted Decisions model ID | Verify selected model and structured-output/tool support per endpoint |
| Sanitized canary | One state, one each of Choice/Score/Noul | Same primitives; verify `answers`, `model`, usage and provider metadata | One bounded prose request and one closed-schema proposal fixture |
| Negative cases | 401/422/429/529, malformed answer, unknown question key | Non-2xx, alpha/path mismatch, no model entitlement, malformed answer | Timeout, refusal, invalid JSON, extra fields, tool call, provider failover |
| Readiness result | Ready only on exact response validation | Ready only on exact alpha contract and policy-compatible route | Ready only on validated prose/proposal handling |

All probes must use synthetic, non-household content, bounded timeouts, and
redacted evidence. They must not be “health checks” that call a production HA
service or infer live action authority.

## 6. Explicit uncertainty and open decisions

- No direct TypeSafe or OpenRouter request was made for this research. Account
  access, billing, model entitlement, current latency, current rate limits, and
  response behavior remain unverified for this deployment.
- OpenRouter's Decisions operation is explicitly alpha. The path, model IDs,
  catalog exposure, provider routing behavior, or schema may change.
- TypeSafe aliases move. The current docs map `jev-latest` to `jev-1.13.0`,
  but production should record the resolved version and re-run compatibility
  tests before changing thresholds.
- A TypeSafe-compatible self-hosted or proxy service is not established by a
  generic HTTP response. It needs a declared versioned contract, authentication
  and privacy review, fixture compatibility, and local calibration evidence.
- OpenRouter provider metadata and policy labels are useful routing inputs but
  are not a substitute for reviewing the current provider terms. `zdr: true`
  or `data_collection: "deny"` may leave no eligible endpoint.
- Vendor calibration does not establish accuracy for Home Assistant utterances,
  device names, languages, or high-consequence actions. Thresholds need a
  synthetic/labeled Switchboard corpus split by operation and risk class.
- Community repositories report live integrations, waitlists, aliases, prices,
  and compatibility observations. Those reports are explicitly third-party and
  must be re-checked against current official docs and a probe before becoming
  support claims.

## 7. Recommended implementation decisions for Switchboard

1. Name the adapters `typesafe_systemone`, `openrouter_decisions`, and
   `openai_compatible_chat`; reject an ambiguous “Jev URL”.
2. Normalize only after wire validation into the repository's bounded decision
   or proposal envelope. Keep raw provider envelopes out of execution paths.
3. Keep native Decisions parameter-free for device writes. Exact values come
   from deterministic local extraction or a separately declared typed extractor
   contract, then Core range/enum validation.
4. Pin the model used by an acceptance corpus, record the resolved model in
   diagnostics, and surface alias/protocol drift as degraded readiness.
5. Prefer local-only routing for sensitive household state. If hosted routing is
   enabled, require a route privacy class and minimize state before applying
   OpenRouter data-policy/ZDR controls.
6. Test provider failure as a refusal/clarification path. A provider timeout,
   401, quota error, malformed answer, or unavailable model must not trigger a
   write or silently switch to a less private route.
7. Keep deterministic policy tests and contract fixtures runnable without a key;
   reserve authenticated canaries for release evidence, with no raw payloads in
   artifacts.

## Sources checked on 2026-09-20

### Official

- [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one)
- [TypeSafe state](https://docs.typesafe.ai/concepts/state)
- [TypeSafe primitives](https://docs.typesafe.ai/primitives)
- [TypeSafe API reference](https://docs.typesafe.ai/api)
- [TypeSafe models](https://docs.typesafe.ai/models)
- [TypeSafe confidence](https://docs.typesafe.ai/confidence)
- [TypeSafe legal/data handling](https://docs.typesafe.ai/legal)
- [OpenRouter OpenAPI specification](https://openrouter.ai/openapi.json)
- [OpenRouter TypeSafe models](https://openrouter.ai/typesafe)
- [OpenRouter API reference](https://openrouter.ai/docs/api_reference/overview)
- [OpenRouter model API](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [OpenRouter data collection](https://openrouter.ai/docs/guides/privacy/data-collection)
- [OpenRouter provider logging](https://openrouter.ai/docs/guides/privacy/provider-logging)

### Third-party reports, used only as ecosystem evidence

- [typesafe-jev-examples](https://github.com/rajivkuriakose/typesafe-jev-examples)
- [HA-SystemOne](https://github.com/AtHeartEngineer/HA-SystemOne)
- [TypeSafe playground tool router](https://github.com/TypeSafeAI/typesafe-playground/blob/main/docs/tool-router.md)
