# Local Validation Evidence — 2026-09-20

Status: **current local source/read-only startup/export gates passed; live and
external gates remain pending**. This record covers the preserved disposable
Home Assistant harness and local source/export checks only. No credentials,
raw entity identifiers, utterances, provider bodies, or volume paths are
retained here.

Current baseline: branch `codex/fix-apparmor-runtime`, `HEAD`
`299a5cb384445e109e9d729e98ee33de2d3f8bcd`, coordinated App/Core version
`0.2.0`.

## Source and packaging

| Gate | Result | Evidence |
| --- | --- | --- |
| Full source tests | passed with expected skips | `python3 -m pytest -q tests` — `469 passed, 4 skipped`. Skips are the unavailable host ConversationEntity/config-flow dependencies and the two opt-in live fixture probes. |
| Compilation and quality | passed | `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools tests`; `python3 tools/check_release_boundary.py --quality`; `git diff --check` for the owned paths. |
| Workflow lint | passed | `actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml`. |
| Publication workflow hardening | passed locally | `python3 -m pytest -q tests/test_release_workflows.py tests/test_release_boundary.py tests/test_local_dev.py` — `24 passed`; the mirror workflow now requires the exact source/tag revision, commit marker, GHCR gate, and App-image E2E gate before public publication. |
| Public export | passed locally | `python3 tools/ha-switchboard-export-public.py <temporary-directory>` — `public export: PASS (207 tracked files)`; the temporary export contained 119 regular files, and `python3 <temporary-export>/tools/check_release_boundary.py --root <temporary-export>` passed. This is not HACS, public-mirror, GHCR, or release proof. |
| Provenance gate hardening | passed locally | `python3 -m pytest -q tests/test_ghcr_revision_gate.py` — `8 passed`; the verifier now supports sanitized offline records, anonymous read-only registry validation, immutable digests, exact architecture sets, and release/image/source revision agreement. It does not turn the currently mismatched public `v0.2.0` artifact into a valid candidate. |
| Local App-image smoke/E2E | passed for current source | `bash tools/app-image-smoke.sh` and `bash tools/app-image-e2e.sh` exited `0` for `299a5cb`; local image, non-root runtime, Supervisor-like ingress/token boundary, persistence/recreate, and bounded cleanup checks passed. AppArmor was accurately reported unavailable on this WSL host. |
| Standalone Compose model | passed for current source | `bash tools/standalone-smoke.sh` rendered the Compose model with an isolated empty environment and passed loopback publication, read-only root, persistent `/data`, healthcheck, standalone-boundary, and secret-free wiring checks. |

## Preserved local runtime

| Gate | Result | Sanitized observation |
| --- | --- | --- |
| Current startup inspection | passed | `timeout 60s python3 tools/local-fixtures/local_api.py startup` — exit `0`; `mode=read_only`, `ready=true`, existing local Supervisor volume identity verified, App options present, `ha_switchboard` entry present, conversation agent present, 28 fixture entities, 28 active capabilities, revision present, and zero pending sections/invalidations. |
| Default restart inspection | passed | `python3 tools/local-fixtures/local_api.py restart-cycle` returned `restart_requested: false` and `restart_performed: false`; no App/Core restart was attempted. |
| Follow-up probe | partial | Earlier bounded live evidence passed same-conversation continuation, cancellation, and one-shot replay (`... -k live_follow_up_fixture` — `1 passed`). Explicit second-user-token and natural-TTL opt-ins remain unavailable. They were not rerun in this read-only reconciliation. |
| Native-miss probe | passed in earlier opt-in evidence | Earlier bounded evidence reported one Assist run, exactly one Switchboard gateway result, conversation reuse, and no recursion. It was not rerun here. |

The T084 preserve-first guard requires a named writable Docker volume with
matching source identity, a settled profile, existing fixture entities, and
the existing Switchboard agent before an explicitly authorized restart. It
rechecks volume identity after each restart phase and emits only bounded
invariants.

## External gates still open

HACS/Hassfest acceptance, GHCR credentials and immutable image proof, public
mirror/tag provenance, protected-master ancestry, multi-architecture image
verification, installed AppArmor parity, live provider acceptance,
migration/rollback, and the public App/Core canary remain pending. T059,
T084, T148, T149, and T151 are not complete: their exact missing
authorization, lifecycle, provider, or public-release evidence is not inferred
from these local checks. Local tests, metadata, and a disposable image cannot
close those gates.

The read-only external records are kept separately in
`external-validation-2026-09-20.md`, `provenance-checks-2026-09-20.md`, and
`t149-t151-provenance-gate-audit-2026-09-20.md`. They confirm local Hassfest
success but show that the public tag/GHCR revision does not match this local
candidate; no publication claim is made.

No publication, push, tag, reset, volume removal, App/Core restart, or provider
request was performed for this evidence record.

## Current checkout reconciliation — 2026-09-20

The current source descendant at `HEAD
299a5cb` was freshly checked with the full source suite (`469 passed, 4 skipped`), compilation,
`check_release_boundary.py --quality`, `check_release_boundary.py`, and
`git diff --check`. A fresh read-only public export passed with `207` tracked
files and `119` regular files; the exported-tree release boundary passed. The
focused release/provenance/acceptance/boundary/local-dev/workflow suite passed
`44 tests`, and the focused group/harness suite passed `61 tests with 1
opt-in skip`.

These fresh checks do not refresh the earlier App-image, preserved-harness,
provider, public-mirror, GHCR, HACS, AppArmor, or canary observations. Those
remain bounded evidence at their recorded revisions, and the exact open gates
remain T059, T084, T148, T149, and T151 as described above.
