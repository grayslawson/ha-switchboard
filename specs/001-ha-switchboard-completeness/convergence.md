# HA Switchboard convergence record

**Review date:** 2026-09-20
**Worktree:** `ha-switchboard-ci-hardening`
**Reviewed revision:** `1ccb6ce2ba5e162249f4f15847280763aee4fb9e`
(current source revision)
**Scope:** This note records the current Spec Kit convergence boundary. The
primary runtime, test, workflow, fixture, and user-document changes remain
owned by their respective workstreams.

## Task status

The task ledger contains 153 tasks:

| State | Count | Meaning |
| --- | ---: | --- |
| Complete | 148 | Current source or artifact plus focused passing tests and local runtime evidence directly prove the exact task. |
| Unchecked | 5 | The task still needs stronger live integration evidence or an external release gate. |

The ledger is authoritative for the checked/unchecked state. The previous
81-complete/54-partial/16-open split was stale: it listed already implemented
provider, Web UI, documentation, and Core diagnostics work as unresolved and
did not include the native-first task. The remaining 5 tasks are concentrated
in live Assist/action/restart acceptance, runtime matrix coverage, live AppArmor
and deployment recovery proof, and source/image/mirror/HACS/Hassfest/live-release
evidence.

## Verified boundaries

- Native OpenRouter Decisions is parameter-free. Typed Jev supports bounded
  parameter values through its typed contract and Core validation.
- Supported clear routine intents now get a Core native Assist/Conversation
  fast path before provider routing. `native_path.py` restricts this to
  `HassLightSet` and light/switch/fan `HassTurnOn`, `HassTurnOff`, and
  `HassToggle`; the native intent filter excludes Switchboard itself. The
  preserved Home Assistant 2026.9 runtime now proves a native fixture action,
  state restoration, and zero Jev diagnostic delta through the repeatable
  `local_api.py native` check. The bounded `native_miss_runtime.py` probe also
  proves a single completed Assist run continues through exactly one
  Switchboard gateway result without recursion.
- The provider contracts are distinct: direct TypeSafe System One uses the
  `/v1/systemone` answers contract and runtime base URL/API key/model inputs;
  OpenRouter Decisions uses its alpha Decisions endpoint and is parameter-free
  in this adapter; generic Jev expects Switchboard's typed `decision` envelope;
  and the `openrouter`/`openai_compatible` fallback is a separate generic OpenAI-compatible
  chat-completions route.
- The documentation and contract now preserve Home Assistant's native
  Assist/Conversation intent path as the simple-command fast path. Switchboard
  is an additional Core Conversation routing layer for ambiguous, compound, or
  risky requests; fallback is for unresolved/open-ended requests and does not
  execute Home Assistant.
- The fixture reports 24 executable Switchboard operation-matrix rows.
  Script and scene are native Core-only surfaces and are not Switchboard
  `activate` capabilities.
- Explicit light, switch, and fan on/off batches can target the whole exposed
  domain, one unambiguous known area, floor, or label, or one validated named
  Home Assistant group. Batch execution stays bounded at 32 targets and
  fail-closed for ambiguous, unavailable, or unsafe members; atomic, toggle,
  and parameterized batch operations remain outside the current boundary.
- The App dashboard now exposes keyboard landmarks, live announcements,
  diagnostic-log semantics, busy/disabled state, and reduced-motion behavior;
  browser-level accessibility inspection remains an open acceptance gate.
- `tools/local-dev.sh` preserves the local Supervisor/Core volume by default;
  reset is guarded by a verified snapshot and explicit confirmation.
- Supervisor discovery retry is bounded and reuses a sanitized payload.
- Latest full pytest result at the reviewed revision: `459 passed, 4 skipped`.
  The skips require the absent Home Assistant runtime/config-flow dependency
  in the host worktree and the two opt-in live fixture probes; they are not
  source or live proof by themselves.
- The current focused release/boundary/local-dev/workflow suite passes (`24
  passed`),
  the quality audit passes, and the sanitized public export contains `204`
  tracked files and `117` regular files before its release-boundary check.
  The release workflows validate the changelog marker, the Home Assistant
  conversation-agent translation shape, and the bounded App-image E2E gate
  before tag publication.
- The preserved local Supervisor harness was recovered after a host reboot and
  independently checked read-only: Core and Supervisor returned HTTP 200, the
  App was started and ready, the persisted `hassio` integration entry and
  `conversation.ha_switchboard` were present, three Assist pipelines were
  available, and fixture entities covered the published mock domains. No
  provider call or secret was used in that check.

## Contradictions and remaining gates

- T016 is implemented at source: `_migrate_options` normalizes a legacy
  persisted `supervisor_read_only` value to `adapter_only`, records a
  compatibility marker, and surfaces the migration warning through App status
  and diagnostics. Live upgrade evidence remains part of the open recovery
  gates.
- Direct TypeSafe client construction and base-URL normalization exist in the
  source, and the Supervisor App manifest exposes `jev_provider`; runtime
  `JEV_BASE_URL` remains a standalone/environment input rather than an App
  option. Source-level adapter evidence exists, but no authenticated direct
  TypeSafe live-provider evidence is recorded.
- The forward-looking specification and plan cover complete live Assist,
  provider, recovery, and release journeys. The current source now covers the
  bounded implementation and source tests for those paths, while traceability
  continues to separate the unproven live and external-release gates.
- Public mirror/tag/GHCR architecture evidence, HACS/App-catalog review,
  installed Supervisor parity, and live canary evidence remain separate gates.
- The supplied pd-nixos AGENTS map does not match this repository-shaped
  worktree: `just agent-preflight` could not run because no Justfile is present.
  This did not change the artifact-only scope.

The task ledger contains older narrative snapshots, including a `109`-file
export count and earlier test totals, alongside its later `437`-test snapshot.
Those historical lines are outside this worker's allowed scope; the exact
current counts above are the ones to use for this documentation review.
