# Jev ecosystem and architecture research

**Scope:** HA Switchboard Jev/provider boundary, current public ecosystem, and
safe Home Assistant integration strategies.

**Research date:** 2026-09-20. Links below were checked on this date. No
credentials or live provider calls were used.

## Executive summary

Jev is a typed decision model, not a chat model or an autonomous Home Assistant
agent. Its documented contract is: one text/JSON `state` plus named `Choice`,
`Score`, and `Noul` questions, followed by typed answers and uncertainty data.
The application owns composition, thresholds, authorization, side effects, and
fallback. This matches Switchboard's Core-owned execution boundary.

OpenRouter's `POST /api/alpha/decisions` is a distinct OpenRouter alpha router.
It is not interchangeable with TypeSafe's documented direct `POST /v1/systemone`
API, and neither is equivalent to an arbitrary endpoint that happens to be
called “Jev”. A provider adapter must declare which wire contract it implements,
pin or discover the model, and fail closed on a mismatch.

The most important current design correction is parameter handling. Native
OpenRouter Decisions can choose among supplied alternatives and return ordered
scores, but its documented response does not return arbitrary action JSON such
as `{brightness: 43}` or `{temperature: 20}`. Switchboard keeps native
Decisions on route/capability/ambiguity/risk questions; exact values must come
from deterministic local parsing, a separately verified typed service, or a
bounded fallback contract, and then pass Core validation.

The request path also has a local-first boundary: Home Assistant's native
Conversation/Assist handler gets the first opportunity for supported clear
routine intents. Switchboard does not add a remote Jev call to an obvious
command that Home Assistant can already resolve. Jev handles the remaining
gray-area routing and policy decisions, and generic OpenAI-compatible fallback
is reserved for eligible unresolved or open-ended requests.

## 1. Verified Jev functionality and wire shape

### Official model behavior

TypeSafe documents System One/Jev as a fast, structured decision model. It
accepts text-only state represented as a string, JSON object, or array of text;
images, audio, and video are not supported. It returns typed decisions and
probabilities rather than prose or reasoning. The three primitives are:

| Primitive | Use | Returned value |
| --- | --- | --- |
| `Choice` | Pick one item from a closed set | `choice`, `probabilities`, `confidence` |
| `Score` | Place state along ordered, described levels | `score`, `legend`, `probabilities`, `confidence` |
| `Noul` | Estimate whether a proposition is true | `noul` from 0 to 1 |

Sources: [System One](https://docs.typesafe.ai/concepts/system-one), [state](https://docs.typesafe.ai/concepts/state), and [primitives](https://docs.typesafe.ai/primitives).

### OpenRouter Decisions

OpenRouter's current OpenAPI specification defines:

```http
POST https://openrouter.ai/api/alpha/decisions
Authorization: Bearer <OpenRouter key>
Content-Type: application/json
```

The required request fields are `model`, `state`, and a `questions` map. Each
question is one of `choice`, `score`, or `noul`; state may be a string, object,
or array. The response contains `answers` keyed by the application question
IDs, plus model, provider, and usage metadata. Choice answers contain a chosen
string and optional probabilities/confidence; score answers contain a numeric
position and optional legend/probabilities/confidence; Noul contains a yes
probability. The OpenAPI examples use `typesafe/jev-1.13`.

Source: [OpenRouter Decisions request/response schema](https://openrouter.ai/openapi.json#tag/alpha.decisions).
The endpoint is explicitly tagged alpha in that specification, so its path and
contract need compatibility tests rather than being treated as a permanent
OpenAI-compatible endpoint.

OpenRouter separately lists Typesafe models and says they are available through
the unified API. Its model page currently lists Jev Latest and Jev 1.13; the
page's quickstart refers to an alias such as `~typesafe/jev-latest`, while the
Decisions OpenAPI example uses `typesafe/jev-1.13`. Pin the exact model ID that
has passed a compatibility probe; do not silently rely on a moving `latest`
alias. Source: [OpenRouter Typesafe models](https://openrouter.ai/typesafe).

### Direct TypeSafe or compatible service

TypeSafe's official docs describe a direct `POST /v1/systemone` API and SDKs.
That is a different path and request/response contract from OpenRouter's
`/api/alpha/decisions`. A self-hosted or proxy service is only “Jev-compatible”
after it declares which version of the System One contract it implements and
passes request, response, timeout, and error compatibility tests. A generic
Switchboard-specific service may instead expose the repository's own normalized
`decision` envelope; that is an adapter contract, not proof that the service is
the TypeSafe API.

Source: [TypeSafe System One API](https://docs.typesafe.ai/concepts/system-one).
As a useful but non-authoritative ecosystem example, [HA-SystemOne](https://github.com/AtHeartEngineer/HA-SystemOne)
supports hosted, self-hosted, and custom System One-compatible URLs, but its
claims are not TypeSafe's compatibility guarantee.

### Supported interaction patterns

The official guidance and working examples support these patterns:

1. **One state, many independent questions.** Questions over the same state
   are evaluated independently and can be sent together. Use this to ask route,
   risk, ambiguity, and sensitivity questions in one call.
2. **Speculative fan-out.** Ask questions that may be needed later and let code
   ignore irrelevant answers. This is safer than serially asking the model to
   choose its next step.
3. **Code-owned composition.** Combine answers, confidence, and probabilities
   with deterministic policy. Thresholds must be tuned to consequence and
   reversibility; confidence is uncertainty evidence, not authorization or
   correctness proof.
4. **Two-stage/hierarchical decisions.** If the second question needs the first
   answer to construct new state or candidate options, make a second request in
   code. Do not assume questions in one request see each other's answers.
5. **Classification, matching, ranking, screening, and verification.** These
   are common ecosystem uses when the answer set is closed and an abstain/review
   option is present.

Sources: [TypeSafe build guidance](https://docs.typesafe.ai/concepts/how-to-build-with-system-one),
[confidence](https://docs.typesafe.ai/confidence), and [TypeSafe's worked examples](https://github.com/rajivkuriakose/typesafe-jev-examples).

## 2. How people and projects currently use Jev

These are concrete public examples, not claims that every project is
production-proven:

| Project | Observed pattern | Switchboard relevance |
| --- | --- | --- |
| [typesafe-jev-examples](https://github.com/rajivkuriakose/typesafe-jev-examples) | Support-ticket triage asks several narrow questions in one request; a reranker sends one Noul per candidate and sorts by probability. It separates live model calls from offline policy tests. | Use one request for independent route/risk signals; keep policy and tests local. |
| [TypeSafe playground tool router](https://github.com/TypeSafeAI/typesafe-playground/blob/main/docs/tool-router.md) | Jev chooses only an allowed graph edge; deterministic hard rules remove secret-related paths; a separate approval checkpoint precedes a mutating mock tool; invented nodes and missing scores stop the flow. | Strong precedent for candidate allowlists, explicit approval, and no model-supplied arguments. |
| [HA-Jev](https://github.com/AboveColin/HA-Jev) | A third-party HA integration exposes Noul/Choice/Score/ask actions, sensors, an Assist router, daily token budget, confidence threshold, and an optional fallback conversation agent. It explicitly describes itself as unaffiliated with TypeSafe. | Confirms real HA demand for typed sensors and Assist routing, but its fallback/whole-house behavior must not be copied without Switchboard's stronger execution boundary. |
| [jev-browser](https://github.com/jkudish/jev-browser) | Jev chooses a browser action from DOM candidates and uses Noul stop/stuck judgments; a separate small model supplies text when typing is required. It bounds steps/time and checks the proposed action before execution. | Separate “choose an allowed action” from “generate a value”; retain bounded stop conditions and post-decision checks. |
| [jevwire](https://github.com/Brainwires/jevwire) and [jev-mcp](https://github.com/blakestone-x/jev-mcp) | MCP/harness layers expose verify, screen, rank, match, gate, and next-step tools with policy thresholds in code; they describe screening as advisory, not an authorization boundary. | Observability and review signals are useful, but Jev remains advisory and cannot replace HA authorization. |

The public examples consistently use the same architecture: Jev narrows or
scores a bounded decision, while ordinary code owns candidate construction,
thresholds, approvals, tool execution, retries, and audit output. No verified
example establishes Jev as a general-purpose HA service executor.

## 3. Safe architectural strategies for Home Assistant

### Typed decision boundary

Build the provider request from a sanitized, current Core profile. Offer opaque
capability IDs and user-facing labels, not entity IDs, service names, arbitrary
service data, or credentials. Ask separately for intent/route, candidate match,
ambiguity, risk, and confirmation requirement. Treat a missing, malformed, or
out-of-catalog answer as a refusal or clarification.

Jev can propose a capability; only Core can map that capability to a raw HA
target, validate parameters, call the service, and verify the resulting state.
This is aligned with [Home Assistant's conversation entity contract](https://developers.home-assistant.io/docs/core/entity/conversation/)
and its rule that the request `Context` is attached to HA actions.

### Bounded questions and parameters

Use `Choice` for operation/domain/candidate selection and `Noul` for separate
yes/no judgments. Use `Score` only when an ordered rubric is genuinely the
needed output. A Score's interpolated numeric position is not automatically an
exact brightness, volume, or temperature value. Native OpenRouter Decisions
therefore cannot authorize parameterized writes by itself.

For a parameterized command, prefer this sequence:

```text
local deterministic extraction when unambiguous
  -> typed range/enum validation in Core
  -> Jev route/candidate/risk decision if needed
  -> confirmation policy
  -> Core execution and verification
```

If a compatible service extracts values, make its parameter schema explicit,
versioned, bounded per operation, and test it against labeled cases. Never allow
the provider to return service names, entity references, or arbitrary nested
service data.

### Follow-up context and memory

Jev requests are stateless in the documented model: each request supplies its
state, and questions in the request are independent. OpenRouter's `session_id`
is documented for grouping/observability and is not sent to the provider; it is
not provider conversation memory. Home Assistant supplies an optional
`conversation_id` for multi-turn conversations and a `continue_conversation`
response flag. Source: [Home Assistant Conversation API](https://developers.home-assistant.io/docs/intent_conversation_api/).

Keep pending clarification, parameter, and confirmation state in Core, bound to
conversation and user identity, with a short TTL, profile/policy revision, and
one-time consumption. Do not send the pending authorization token to Jev or a
fallback. Rebuild the provider state on each turn from the stored bounded
request and the current profile; reject expiry, replay, cross-user, and stale
revision cases.

### Routing, handoff, and fallback

Use deterministic routing before Jev where possible: local read-only answers,
obvious single-device operations, unsupported/high-risk blocks, and privacy
denials do not need a provider call. Route low-confidence or unsupported cases
to clarification, refusal, or one explicit downstream handoff. Keep handoff
depth bounded and keep route selection in code; Jev must not choose a provider
name or endpoint.

Treat downstream chat as a prose/typed-proposal service, not a second HA agent.
OpenRouter Chat Completions supports ordinary chat, structured JSON schemas, and
tool calling, but that is a different API from Decisions. Switchboard should
accept either bounded prose or one proposal containing an offered opaque
capability and validated parameters. Every proposal re-enters freshness,
allowlist, risk, confirmation, idempotency, Core execution, and verification.
Source: [OpenRouter API reference](https://openrouter.ai/docs/api_reference/overview).

### Multi-device actions

Do not ask Jev to emit an atomic multi-device plan. Core should resolve an area,
label, group, or explicit plural request to a bounded set, preflight every
member, partition unavailable/unsupported/confirmation-required targets, execute
sequentially or with an explicitly reviewed concurrency policy, and report each
verification result. Home Assistant has no general transaction/rollback
contract for arbitrary service batches; partial completion must be visible.

### Capability selection and provider discovery

The provider receives a bounded snapshot, not a long-lived profile or HA chat
log. Profile generation, exposure, availability, service shape, operation
allowlist, parameter schema, and verification rule should be versioned together.
Provider discovery must verify endpoint kind, protocol version, model, supported
question/output types, maximum state/questions, authentication, latency, and
privacy classification before marking the route ready.

OpenRouter's API specification exposes model architecture/output modality and a
model-list filter for `decisions`; use that rather than assuming the default
text-model catalog proves Decisions support. Source: [OpenRouter OpenAPI model-list schema](https://openrouter.ai/openapi.json).

### Observability and privacy

Record route kind, adapter/protocol version, model, provider request ID when
available, latency, usage/cost, confidence/ambiguity bands, policy outcome,
profile revision, and execution/verification result. Do not record utterances,
raw state, credentials, raw entity IDs, or full provider payloads by default.
Provider metadata is useful evidence: OpenRouter's Decisions response includes
model/provider/usage fields, so discarding all of them makes diagnosis harder.

## 4. Three-way comparison

| Boundary | Native OpenRouter Decisions | Compatible Jev/System One service | Downstream chat/fallback |
| --- | --- | --- | --- |
| Wire contract | OpenRouter alpha `POST /api/alpha/decisions`; `model`, `state`, typed `questions`; response `answers`. | Direct TypeSafe documents `POST /v1/systemone`; a proxy/self-host must declare its exact compatibility. | OpenRouter `/api/v1/chat/completions` or a declared Switchboard typed HTTP contract. |
| Output | Only `Choice`, `Score`, `Noul` answer shapes. | Same only if the service actually implements that System One contract; a Switchboard custom envelope is a separate contract. | Prose or structured JSON; may also expose tool calling, which Switchboard must not pass through. |
| Good HA use | Route, candidate choice, ambiguity/risk/sensitivity, read-only classification. | Parameter extraction only after explicit schema/version and calibration tests; route and risk signals. | Open-ended bounded explanation or one typed proposal after Jev cannot answer. |
| Not safe to assume | Exact brightness/temperature values, HA execution, memory, provider selection, or stable endpoint semantics. | That any “Jev” URL is System One-compatible, or that OpenRouter alpha behavior is reproduced. | Arbitrary HA agent/tool calls, multi-action plans, confirmation bypass, or raw service data. |
| Current Switchboard state | Adapter exists and intentionally clarifies parameterized candidates; it computes confidence from returned probabilities. | Direct TypeSafe `/v1/systemone`, native OpenRouter Decisions, and generic Switchboard-compatible Jev adapters are explicit provider choices; source-level contract tests pass, but authenticated live provider evidence remains open. | OpenRouter and generic OpenAI-compatible fallback adapters support bounded prose or one offered typed proposal; ordered failover is source-tested, while live provider/runtime evidence remains open. |

## 5. Gaps and wrong assumptions in the current design

Repository observations are from the assigned worktree on 2026-09-20:

1. **Generic Jev compatibility is overstated.** `app/ha_switchboard/jev_client.py`
   sends Switchboard-specific `questions` and expects `decision`; that is not
   the official OpenRouter Decisions shape or the documented direct System One
   shape. The adapter must be selected explicitly by provider/protocol, not by
   “non-OpenRouter URL”.
2. **Native parameter extraction is correctly fail-closed but incomplete.**
   `OpenRouterDecisionsClient` only accepts parameter-free controls. `T061`
   must not turn `typed_object` in the generic client into a claim that native
   OpenRouter can return typed action values. Add a separate extractor contract
   and calibration/evidence gate.
3. **Follow-up context is local but not yet a complete behavior.** The Core
   store has TTL, user binding, and one-shot consumption (`T062`), while
   parameter follow-up resolution and live same-conversation Assist proof remain
   open (`T059`, `T063`-`T065`). A bare “yes” must never be sent to Jev as if it
   were a fresh action request.
4. **Jev cannot plan a batch.** The native adapter asks for one capability. Group
   resolution and per-target verification belong to `T048`-`T054`, not to a
   provider-generated list of service calls.
5. **Fallback does not equal a capable HA agent.** The chat fallback is a
   separate text model and returns bounded prose or one offered capability
   proposal. `T071`, `T075`, `T077`, and `T078` still need to prove typed
   parameters, malformed responses, privacy, route failover, compatibility
   probing, and one-level handoff separately.
6. **Provider discovery and negotiation remain incomplete.** Current source
   selection is explicit for direct TypeSafe, OpenRouter Decisions, generic
   Jev-compatible, and OpenAI-compatible fallback modes, with migration tests.
   `T014`, `T077`, and `T100` still need the full route registry contract,
   authenticated compatibility probe, and visible readiness evidence.
7. **Model/version drift is not visible enough.** Native responses contain model,
   provider, request ID, and usage, but the normalized decision currently keeps
   little of that evidence. `T009`, `T042`, `T065`, and `T099` should preserve
   redacted metadata and policy/profile revisions.
8. **Confidence is being used in the right direction but needs calibration
   evidence.** It must gate or escalate, not authorize. Thresholds should be
   measured against labeled Switchboard utterances by operation/risk class;
   TypeSafe's published examples explicitly say thresholds depend on stakes.

## 6. Prioritized recommendations mapped to Spec Kit tasks

| Priority | Recommendation and task IDs | Confidence | Evidence gate before calling complete |
| --- | --- | --- | --- |
| P0 | Split native OpenRouter, direct System One, and Switchboard-custom adapters; add explicit `provider_kind`, protocol/schema version, model ID, and capability probe: `T008`, `T014`, `T020`, `T077`, `T146`. | High | Fixtures for all three envelopes; authenticated live probes where credentials are available; wrong endpoint/model/shape must be rejected and readiness must remain degraded. |
| P0 | Keep native OpenRouter to route/candidate/risk/ambiguity; implement exact parameter extraction only as a separately declared, bounded contract: `T056`-`T061`, `T107`-`T109`. | High | Per-operation range/enum tests; labeled parameter cases; reject missing, interpolated, out-of-range, conflicting, and unknown values; no write on any provider mismatch. |
| P0 | Complete Core-local continuation, including parameter questions, affirmative/negative parsing, revision binding, expiry, replay, and cross-user cases: `T059`, `T063`-`T065`. | High | Live fixture Assist requests preserve `conversation_id`; same-user follow-up executes once; no-ID, expired, replayed, cross-user, and stale-profile replies cannot authorize writes. |
| P0 | Make multi-device resolution deterministic and Core-owned; never accept provider service plans: `T044`-`T054`. | High | Area/label/group/plural fixtures, 32-target bound, unavailable/confirmation partitions, per-target verification, partial failure, and idempotent retry evidence. |
| P1 | Finish fallback as two explicit modes—bounded prose and one typed proposal—with parameter schema, route identity, privacy, timeout/circuit, failover, and depth enforcement: `T067`-`T079`. | High | Synthetic OpenRouter/typed services return valid, malformed, oversized, invented-capability, arbitrary-service-data, unauthorized, timeout, and failover cases; every proposal re-enters Core gates. |
| P1 | Use OpenRouter model discovery with `decisions` output modality where available and pin the tested model; surface provider/model/usage/latency without sensitive payloads: `T009`, `T014`, `T077`, `T096`, `T099`, `T100`. | Medium-high | Probe records endpoint kind, model, supported primitives, max bounds, and response version; catalog omission or alpha drift produces a visible unavailable/degraded state. |
| P1 | Add a Jev evaluation corpus and operation/risk calibration report; keep deterministic policy tests independent of provider calls: `T002`, `T056`-`T059`, `T134`, `T140`, `T149`. | Medium | Reproducible offline corpus plus bounded live canary; report false-act/false-clarify rates by risk class and retain no raw household identifiers. |

## 7. Unresolved questions

- Which exact direct TypeSafe model/version and authentication flow will
  Switchboard support, versus only OpenRouter's alpha Decisions route?
- Is the intended “compatible Jev service” the official `/v1/systemone`
  contract, the repository's custom `decision` envelope, or both? It should not
  be left implicit in one URL field.
- Will parameter values be extracted deterministically from user text, by a
  dedicated typed service, or by a chat fallback? The answer changes the
  contract and calibration burden.
- What is the supported behavior when OpenRouter's Decisions model is absent
  from the default model catalog or its alpha schema changes?
- Should provider failure during a pending confirmation preserve the pending
  action for a bounded retry, or consume it and require a new request? The
  safety choice should be explicit and tested.
- Which HA surfaces are guaranteed to preserve `conversation_id` and user
  identity for voice satellites, REST, WebSocket, and direct conversation-entity
  calls?

## 8. Do not implement

- Do not treat Jev as a prose chatbot, autonomous agent, or HA service executor.
- Do not use `/api/v1/chat/completions` as a Jev Decisions endpoint, or infer
  that any OpenRouter model endpoint is a standalone Jev service.
- Do not claim native OpenRouter Decisions extracts arbitrary brightness,
  temperature, volume, entity IDs, or service data.
- Do not map a Score position to an exact device value without an explicit,
  tested mapping and Core validation.
- Do not use confidence/probability as proof of correctness, authorization, or
  confirmation.
- Do not treat `session_id`, an LLM chat history, or a provider-side memory as
  the Core pending-action authorization record.
- Do not let Jev or fallback choose providers, endpoints, raw HA targets,
  arbitrary service data, or an unbounded multi-device plan.
- Do not claim atomic batch execution or rollback for ordinary HA service calls.
- Do not call an unverified self-hosted endpoint “Jev-compatible” solely because
  it accepts JSON or returns a field named `decision`.
- Do not enable a moving `latest` model alias in production without recording
  the resolved model and passing the current compatibility gate.

## Sources and access date

**Official:** [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one),
[TypeSafe state](https://docs.typesafe.ai/concepts/state), [TypeSafe primitives](https://docs.typesafe.ai/primitives),
[TypeSafe confidence](https://docs.typesafe.ai/confidence), [TypeSafe build guidance](https://docs.typesafe.ai/concepts/how-to-build-with-system-one),
[OpenRouter Decisions OpenAPI](https://openrouter.ai/openapi.json), [OpenRouter API reference](https://openrouter.ai/docs/api_reference/overview),
and [OpenRouter Typesafe models](https://openrouter.ai/typesafe).

**Home Assistant:** [Conversation entity](https://developers.home-assistant.io/docs/core/entity/conversation/),
[Conversation API](https://developers.home-assistant.io/docs/intent_conversation_api/),
[Assist pipelines](https://developers.home-assistant.io/docs/voice/pipelines/), and
[LLM API](https://developers.home-assistant.io/docs/core/llm/).

**Public examples/integrations:** [typesafe-jev-examples](https://github.com/rajivkuriakose/typesafe-jev-examples),
[TypeSafe playground tool router](https://github.com/TypeSafeAI/typesafe-playground/blob/main/docs/tool-router.md),
[HA-Jev](https://github.com/AboveColin/HA-Jev), [HA-SystemOne](https://github.com/AtHeartEngineer/HA-SystemOne),
[jev-browser](https://github.com/jkudish/jev-browser), [jevwire](https://github.com/Brainwires/jevwire),
and [jev-mcp](https://github.com/blakestone-x/jev-mcp). Community project claims
are treated as examples and design signals, not vendor guarantees.
