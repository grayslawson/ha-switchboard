# T148 Local Quickstart Evidence — 2026-09-20

Status: **partial**. The safe local source, image, lifecycle, scan, native,
fixture, follow-up, ingress, and protected-endpoint checks were run against the
preserved disposable harness. The opt-in App/Core restart cycle, token
rotation, provider acceptance, and external release gates were not run. No
production Home Assistant endpoint was used.

## Scope and baseline

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Source revision: `fcff6e86e729f34d4d01201cafebe3bf86f9cddd`; the worktree had
  unrelated concurrent changes before this run and they were preserved.
- Source versions agree at App/Core `0.2.0` in the checked-in metadata.
- Local harness: Supervisor container `busy_cohen`, loopback Supervisor port
  `7123`, Core container `homeassistant`; the startup probe verified the
  mounted Supervisor volume as a local Docker volume.
- The evidence below intentionally omits credentials, raw entity or
  conversation identifiers, utterances, gateway URLs, and provider bodies.

## Source and image gates

| Gate | Status | Command and sanitized result |
| --- | --- | --- |
| Compile | passed | `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools` — exit `0`. |
| Source tests | passed with skips | `python3 -m pytest -q tests` — exit `0`, `393 passed, 3 skipped`. Skips were the host-side Assist/config-flow dependency checks and the explicitly opt-in native-miss runtime probe. |
| Release boundary | passed | `python3 tools/check_release_boundary.py` — exit `0`, `release boundary: PASS`. |
| Local App image smoke | passed | `bash tools/app-image-smoke.sh` — exit `0`; local image health, expected provider-degraded readiness, authentication boundary, persistence, stale-profile recovery, and non-root serving checks passed. This is not public-image proof. |

## Preserved local runtime gates

| Gate | Status | Command and sanitized result |
| --- | --- | --- |
| Reuse/wait for existing harness | passed | `tools/local-dev.sh e2e` reused the existing harness; Supervisor, Core, observer, App-start, and App ingress checks all passed. |
| Idempotent fixture install | passed | `python3 tools/local-fixtures/install.py` — exit `0`; local fixture package installed and Core configuration validated. No reset, volume replacement, or Core restart was requested by this command. |
| Read-only startup | passed | `python3 tools/local-fixtures/local_api.py startup` — exit `0` before and after the fixture checks; local volume verified, options present, existing `ha_switchboard` entry present, conversation agent present, `28` fixture entities, active profile with `28` capabilities, revision present, and zero pending sections/invalidations. |
| Read-only lifecycle | passed | Core-side `local_api.py lifecycle` — exit `0`; the same config-entry, conversation-agent, fixture-count, and active-profile facts were observed. |
| Read-only profile | passed | Core-side `local_api.py profile` — exit `0`; profile status `active`, `28` capabilities, revision present, zero pending sections/invalidations. |
| Bounded manual scan | passed | Core-side `local_api.py scan` — exit `0`; scan request HTTP `202`, then `completion: settled` after `8` bounded polls with active profile and zero pending sections/invalidations. |
| Native Assist fast path | passed | Core-side `local_api.py native` — exit `0`; the Switchboard pipeline preferred local intents, event sequence completed without an error, fixture state changed and was restored, and Jev diagnostic delta was `0` (`native_provider_bypass: proved`). |
| Native miss continuation | passed | `HA_SWITCHBOARD_RUN_NATIVE_MISS=1 python3 tools/local-fixtures/native_miss_runtime.py` — exit `0`; one bounded Assist run completed, exactly one Switchboard gateway result was observed, the conversation ID was reused, and no recursion was observed. |
| Fixture operation coverage | passed | Core-side `local_api.py coverage` — exit `0`; `24/24` executable operation rows were present and exposed, with no missing or unexposed rows. Two native-Core-only surfaces were present and unexposed. |
| Native-only boundary | passed | Core-side `local_api.py unsupported` — exit `0`; both native-only surfaces were present, unexposed, and not Switchboard capabilities. |
| Direct fixture operation matrix | partial | Core-side `local_api.py exercise` — exit `0`; all `24/24` direct service/state transitions verified. The helper output did not include a post-action restoration assertion, so this run does not claim fixture-state restoration for the matrix. |
| Follow-up conversation | partial | Core-side `local_api.py follow-up` — exit `0`; same-conversation continuation, cancellation without a write, and replay safety were proved. Different-user and natural TTL-expiry checks were `unavailable` because they require an additional HA user/clock setup and no auth mutation was performed. |
| Config-entry verification | passed | Core-side `local_api.py verify` — exit `0`; exactly one local `ha_switchboard` entry, Hass.io source, version `1`, and token presence were confirmed without printing connection data. |
| Deterministic failure fixtures | passed | Core-side `local_api.py failures` — exit `0`; stable provider-unavailable, malformed-provider, missing/out-of-range-parameter, and unknown-capability cases were emitted without provider calls or secrets. |

## Acceptance matrix classification

The following is the complete quickstart matrix classification for this run;
“not run” means no live claim is made.

| Scenario | Status | Evidence boundary |
| --- | --- | --- |
| Clear built-in Assist intent | not run | No additional natural-language Assist run was issued. |
| Read-only state question | not run | Provider/routing invocation was not used for this safe pass. |
| Unique single-device on/off | partial | Native Assist success and state restoration passed for one fixture device; Jev/Core proposal behavior was not exercised. |
| Parameterized brightness/volume/temperature | partial | Direct fixture matrix verified the typed transitions; Assist/Switchboard routing was not exercised. |
| Ambiguous device | not run | No live ambiguous request was issued. |
| Confirmation-required lock/cover action | partial | Follow-up cancellation and replay safety passed; an accepted confirmation write was not run. |
| Clarification/confirmation follow-up | partial | Same-conversation cancellation/replay passed; second-user and natural-expiry cases were unavailable. |
| Exposed script/scene row | passed | Coverage/unsupported checks confirmed native-only surfaces are not exposed as Switchboard capabilities. |
| Explicit two-device on/off | not run | No provider-dependent two-device Assist request was issued. |
| Mixed-availability batch | not run | No live partial-availability batch was issued. |
| Stale profile | partial | Local scan settled active; stale-write behavior is source-tested but was not injected live. |
| Jev invalid/unavailable | partial | Deterministic failure fixtures and source tests passed; no live provider outage or malformed provider response was used. |
| OpenRouter prose fallback | not run | No external/provider fallback request was issued. |
| Typed fallback proposal | not run | No external/provider fallback request was issued. |
| Fallback disabled/privacy blocked | partial | Configuration/source boundaries passed; no live fallback decision was requested. |
| Manual scan during event/reconcile | partial | One bounded authenticated scan settled; concurrent/coalesced event contention was not run. |
| App/Core restart | blocked | The explicit user boundary forbids the opt-in restart cycle in this worker run. The default read-only restart inspection below passed. |

## Security and recovery classification

| Gate | Status | Command and sanitized result |
| --- | --- | --- |
| Read-only restart inspection | passed | `python3 tools/local-fixtures/local_api.py restart-cycle` — exit `0`; `restart_requested: false`, `restart_performed: false`, local volume/config entry/fixture/profile invariants present. |
| Protected endpoint without token | passed | Bounded local probe returned HTTP `401`; no response body was retained. |
| Protected endpoint with invalid token | passed | Bounded local probe returned HTTP `401`; no response body was retained. |
| Wrong content type / oversized request | partial | Wrong-content-type probe was rejected at the authentication boundary with HTTP `401`; the `415` content-type branch and oversized live request were not independently proven here. Source tests cover request validation. |
| Stale revision / unknown capability / invalid parameter / malformed provider | partial | Source and deterministic fixture checks passed; live injection was not run. |
| Runtime identity and App permissions | partial | App PID 1 reported UID/GID `65532`; source metadata has AppArmor enabled, no host networking, no privileged mode, and no devices. The preserved devcontainer reports host security options `apparmor=unconfined`, so installed AppArmor enforcement parity is not proven. |
| Three-cycle App/Core restart recovery | blocked | Explicitly not authorized for this run; no restart was performed. |
| Gateway-token rotation | blocked | Explicitly excluded; no token was rotated or printed. |
| Volume snapshot/removal recovery | not run | No volume removal or reset was attempted or needed. |

## Release classification

| Gate | Status | Result |
| --- | --- | --- |
| Public export and exported-tree boundary | not run | No public export was created in this worker scope. |
| Workflow, HACS, and Hassfest acceptance | not run | External/CI acceptance was not run against this preserved local harness. |
| Multi-architecture image, GHCR digest, tag, mirror, and source-label proof | not run | Local image smoke is not publication or immutable-artifact proof. |
| Live App/Core release canary | not run | Production/public endpoints were not used. |

## Safety and changed files

- No Supervisor/Core volume reset, removal, recreation, or replacement was
  performed.
- No opt-in App/Core restart, token rotation, production endpoint, or live
  provider acceptance request was performed.
- The direct fixture matrix helper completed all rows but did not emit a
  restoration assertion; this is recorded as partial/attention rather than
  inferred success.
- Worker-owned changed files: [local-quickstart-2026-09-20.md](local-quickstart-2026-09-20.md)
  only. Existing concurrent changes in the shared worktree were not edited.
