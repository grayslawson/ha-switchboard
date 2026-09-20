# T148 Local Quickstart Evidence — 2026-09-20

Status: **partial**. Earlier bounded local evidence covers source, image,
lifecycle, scan, native, fixture, follow-up, ingress, and protected-endpoint
checks against the preserved disposable harness. This reconciliation refreshed
the source count, current revision, public-export result, and read-only startup
fact only; it did not rerun mutating or opt-in runtime probes. The App/Core
restart cycle, token rotation, provider acceptance, and external release gates
remain open. No production Home Assistant endpoint was used.

## Scope and baseline

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Source revision at this reconciliation: `e8538be`;
  unrelated concurrent changes and existing commits were preserved.
- Source versions agree at App/Core `0.2.0` in the checked-in metadata.
- Local harness: Supervisor container `busy_cohen`, loopback Supervisor port
  `7123`, Core container `homeassistant`; the startup probe verified the
  mounted Supervisor volume as a local Docker volume.
- The evidence below intentionally omits credentials, raw entity or
  conversation identifiers, utterances, gateway URLs, and provider bodies.

## Source and image gates

| Gate | Status | Command and sanitized result |
| --- | --- | --- |
| Compile | passed | Current `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools tests` — exit `0`. |
| Source tests | passed with skips | `python3 -m pytest -q tests` — exit `0`, `445 passed, 4 skipped`. Skips were the unavailable host ConversationEntity/config-flow dependencies and the two explicitly opt-in live fixture probes. |
| Compilation/quality | passed | `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools tests` — exit `0`; `python3 tools/check_release_boundary.py --quality` — `quality audit: PASS`. |
| Public export | passed locally | `python3 tools/ha-switchboard-export-public.py <temporary-directory>` — `public export: PASS (204 tracked files)`; exported-tree boundary — `release boundary: PASS`. The temporary export contained 117 regular files. This is not HACS, public-mirror, GHCR, or release proof. |
| Local App image smoke | passed | `bash tools/app-image-smoke.sh` — exit `0`; local image build, root-only data preparation, non-root runtime, profile persistence, recreate/restore, and stale-profile fail-closed behavior passed. This is not public-image proof. |

The bounded local App-image E2E harness also passed after this reconciliation:
`bash tools/app-image-e2e.sh` — exit `0`; source marker, non-root runtime,
ingress boundary, token protection, and bounded cleanup passed. The WSL host
reported AppArmor unavailable because enforcement was not requested and no
host AppArmor interface was available; no enforcement claim is made.

## Preserved local runtime gates

| Gate | Status | Command and sanitized result |
| --- | --- | --- |
| Reuse/wait for existing harness | previously recorded | `tools/local-dev.sh e2e` reused the existing harness; Supervisor, Core, observer, App-start, and App ingress checks all passed. It was not rerun in this read-only reconciliation. |
| Idempotent fixture install | previously recorded | `python3 tools/local-fixtures/install.py` — exit `0`; local fixture package installed and Core configuration validated. It was not rerun here; no reset, volume replacement, or Core restart was requested. |
| Read-only startup | passed | `timeout 60s python3 tools/local-fixtures/local_api.py startup` — exit `0`; `mode=read_only`, `ready=true`, local volume verified, options present, existing `ha_switchboard` entry present, conversation agent present, `28` fixture entities, active profile with `28` capabilities, revision present, and zero pending sections/invalidations. |
| Read-only lifecycle | previously recorded | Core-side `local_api.py lifecycle` — exit `0`; the same config-entry, conversation-agent, fixture-count, and active-profile facts were observed. It was not rerun here. |
| Read-only profile | previously recorded | Core-side `local_api.py profile` — exit `0`; profile status `active`, `28` capabilities, revision present, zero pending sections/invalidations. It was not rerun here. |
| Bounded manual scan | passed in earlier evidence | Earlier Core-side `local_api.py scan` evidence recorded HTTP `202`, then `completion: settled` after bounded polls with active profile and zero pending sections/invalidations. It was not rerun here. |
| Native Assist fast path | passed in earlier evidence | Earlier Core-side `local_api.py native` evidence recorded local-intent preference, a completed event sequence, fixture-state restoration, and Jev diagnostic delta `0`. It was not rerun here. |
| Native miss continuation | passed in earlier opt-in evidence | Earlier `native_miss_runtime.py` evidence recorded one bounded Assist run, exactly one Switchboard gateway result, conversation reuse, and no recursion. It was not rerun here. |
| Fixture operation coverage | previously recorded | Core-side `local_api.py coverage` — exit `0`; `24/24` executable operation rows were present and exposed, with no missing or unexposed rows. Two native-Core-only surfaces were present and unexposed. It was not rerun here. |
| Native-only boundary | previously recorded | Core-side `local_api.py unsupported` — exit `0`; both native-only surfaces were present, unexposed, and not Switchboard capabilities. It was not rerun here. |
| Direct fixture operation matrix | partial, previously recorded | Core-side `local_api.py exercise` — exit `0`; all `24/24` direct service/state transitions verified. The helper output did not include a post-action restoration assertion, so this run does not claim fixture-state restoration for the matrix. |
| Follow-up conversation | partial | Earlier Core-side `local_api.py follow-up` evidence proved same-conversation continuation, cancellation without a write, and replay safety. Different-user and natural TTL-expiry checks remain `unavailable`; this reconciliation did not create users, mutate auth, or wait on TTL. |
| Config-entry verification | previously recorded | Core-side `local_api.py verify` — exit `0`; exactly one local `ha_switchboard` entry, Hass.io source, version `1`, and token presence were confirmed without printing connection data. It was not rerun here. |
| Deterministic failure fixtures | previously recorded | Core-side `local_api.py failures` — exit `0`; stable provider-unavailable, malformed-provider, missing/out-of-range-parameter, and unknown-capability cases were emitted without provider calls or secrets. It was not rerun here. |

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
| Public export and exported-tree boundary | passed locally | The current read-only export passed with 204 tracked files and 117 regular files; the boundary check passed. This is not public-mirror publication proof. |
| Private workflow lint | passed locally | `actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml` passed with no diagnostics. |
| HACS acceptance | pending | The authorized HACS action/public-repository path was not run. Static metadata shape is not HACS acceptance. |
| Hassfest acceptance | local export evidence only | The pinned Hassfest container passed in an earlier read-only exported-tree run; no claim is made for public-mirror or installed acceptance. |
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
- This record is limited to the owned documentation/evidence scope. Existing
  concurrent changes outside that scope were not edited.

## Task disposition

- **T059:** remains open/partial. Same-conversation, cancellation, and replay
  are locally evidenced; second-user and natural-TTL live proof is unavailable.
- **T084:** remains open/partial. Startup/scan/readiness and the default
  restart no-op are evidenced; the authorized App/Core restart cycle was not
  run.
- **T148:** remains open/partial. Local evidence is recorded, but the complete
  quickstart lifecycle/provider/security/release matrix is not complete.
- **T149/T151:** remain pending. No exact HACS, public-mirror/tag/GHCR
  provenance, protected-master, publication, or installed-canary evidence is
  claimed here.
