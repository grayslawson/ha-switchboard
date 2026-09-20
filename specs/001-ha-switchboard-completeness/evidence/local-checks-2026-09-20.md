# Local Validation Evidence — 2026-09-20

Status: **current local source/read-only startup/export gates passed; live and
external gates remain pending**. This record covers the preserved disposable
Home Assistant harness and local source/export checks only. No credentials,
raw entity identifiers, utterances, provider bodies, or volume paths are
retained here.

Current baseline: branch `codex/fix-apparmor-runtime`, `HEAD`
`799efc422b372ecc8117336a904e426126889e80`, coordinated App/Core version
`0.2.0`.

## Source and packaging

| Gate | Result | Evidence |
| --- | --- | --- |
| Full source tests | passed with expected skips | `python3 -m pytest -q tests` — `431 passed, 4 skipped`. Skips are the unavailable host ConversationEntity/config-flow dependencies and the two opt-in live fixture probes. |
| Compilation and quality | passed | `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools tests`; `python3 tools/check_release_boundary.py --quality`; `git diff --check` for the owned paths. |
| Workflow lint | passed | `actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml`. |
| Publication workflow hardening | passed locally | `python3 -m pytest -q tests/test_release_workflows.py` — `9 passed`; the mirror workflow now requires the exact source/tag revision, commit marker, GHCR gate, and App-image E2E gate before public publication. |
| Public export | passed locally | `python3 tools/ha-switchboard-export-public.py <temporary-directory>` — `public export: PASS (203 tracked files)`; the temporary export contained 125 regular files, and `python3 <temporary-export>/tools/check_release_boundary.py --root <temporary-export>` passed. This is not HACS, public-mirror, GHCR, or release proof. |
| Provenance gate hardening | passed locally | `python3 -m pytest -q tests/test_ghcr_revision_gate.py` — `8 passed`; the verifier now supports sanitized offline records, anonymous read-only registry validation, immutable digests, exact architecture sets, and release/image/source revision agreement. It does not turn the currently mismatched public `v0.2.0` artifact into a valid candidate. |

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
