# Local Provider Compatibility Evidence — 2026-09-20

Status: **source and deterministic fixture gates passed; live provider and release gates remain pending**.

## Scope

This record covers the Jev, OpenRouter/generic OpenAI-compatible fallback, typed
HTTP fallback, route-policy, and sanitized downstream-response fixture contracts.
All provider transports were monkeypatched or represented by checked-in fixtures;
no external provider request, credential, Home Assistant restart, or runtime
mutation was performed.

## Checks

| Gate | Result | Evidence |
| --- | --- | --- |
| Focused provider acceptance | passed | `python3 -m pytest -q tests/test_fallback_routing.py tests/test_openrouter_fallback.py tests/test_typed_http_fallback.py tests/test_provider_architecture.py tests/test_route_policy.py` — `43 passed`. |
| Full source suite at provider-evidence collection | passed with expected skips | `python3 -m pytest -q` — `430 passed, 4 skipped`; this is the provider worker's historical collection result. Skips are unavailable Home Assistant host/config-flow dependencies and explicitly opt-in local runtime probes. |
| Python compilation | passed | `python3 -m compileall -q app/ha_switchboard tests/test_openrouter_fallback.py tests/test_typed_http_fallback.py tests/test_route_policy.py tests/test_fallback_routing.py` — exit `0`. |
| Patch hygiene | passed | `git diff --check` — exit `0`. |

## Contract coverage

- Jev direct/generic typed contracts retain typed answers/parameters, bounded
  transport retry, malformed-response fail-closed behavior, and provider
  selection separation.
- OpenRouter/generic chat fallback covers bounded prose, one offered opaque
  proposal, no tool calls, pre-transport rejection of forbidden references,
  bounded transient retry, and no retry for non-retryable HTTP failure.
- Typed HTTP fallback exercises both checked-in prose/proposal fixtures, typed
  parameter preservation, exact contract-version matching, raw service JSON
  rejection, identity/response bounds, and bounded transport retry.
- Route policy exercises local privacy eligibility, hosted-route exclusion,
  disabled/open-circuit behavior, explicit failover order, and latency/cost
  budget eligibility.
- The only implementation adjustment is a strict acceptance rule for the
  checked-in `ha-switchboard-fallback/v1` response marker; unknown markers and
  fields remain rejected.

## Remaining gates

These deterministic checks do **not** prove authenticated Jev/OpenRouter or
generic-provider compatibility, model entitlement, live endpoint behavior,
installed AppArmor parity, App/Core canary behavior, or release provenance.
T148 and T149 remain incomplete; T148 still requires its authorized runtime and
release evidence, and T149 still requires the external provider, image,
publication, and canary gates. No live provider compatibility claim is made.

The current source checkout was independently rechecked with the full source
suite at `HEAD e8538be`:
`445 passed, 4 skipped`. That refresh did not contact a provider, so the live
provider gates remain unchanged.
