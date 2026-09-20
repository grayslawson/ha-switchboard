# Local Validation Evidence — 2026-09-20

Status: **local gates passed; external release gates remain pending**.
This record covers the preserved disposable Home Assistant harness and local
source/image checks only. No credentials, raw entity identifiers, utterances,
provider bodies, or volume paths are retained here.

## Source and packaging

| Gate | Result | Evidence |
| --- | --- | --- |
| Full source tests | passed with expected skips | `python3 -m pytest -q tests` — `410 passed, 4 skipped`. Skips are the unavailable host ConversationEntity/config-flow dependencies and the two opt-in live fixture probes. |
| Focused follow-up/recovery/provenance tests | passed with expected opt-in skips | `python3 -m pytest -q tests/test_restart_acceptance.py tests/test_preserve_first_runtime.py tests/test_local_fixtures.py tests/test_e2e_harness.py tests/test_native_miss_runtime.py tests/test_ghcr_revision_gate.py` — `54 passed, 2 skipped`. |
| Release/quality/packaging tests | passed | `python3 -m pytest -q tests/test_release_acceptance.py tests/test_release_boundary.py tests/test_quality_audit.py tests/test_release_workflows.py tests/test_packaging.py tests/test_standalone_runtime.py` — `37 passed`. |
| Compilation and quality | passed | `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools tests`; `python3 tools/check_release_boundary.py --quality`; `git diff --check`. |
| Workflow lint | passed | `actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml`. |
| Public export | passed | `python3 tools/ha-switchboard-export-public.py <temporary-directory>` and exported-tree boundary check — `public export: PASS (109 tracked files)`. |
| Provenance gate hardening | passed locally | `python3 -m pytest -q tests/test_ghcr_revision_gate.py` — `8 passed`; the verifier now supports sanitized offline records, anonymous read-only registry validation, immutable digests, exact architecture sets, and release/image/source revision agreement. It does not turn the currently mismatched public `v0.2.0` artifact into a valid candidate. |

## Preserved local runtime

| Gate | Result | Sanitized observation |
| --- | --- | --- |
| Startup inspection | passed | Existing local Supervisor volume identity verified; App options present; `ha_switchboard` entry present; conversation agent present; 28 fixture entities; 28 active capabilities; revision present; zero pending sections/invalidations; readiness true. |
| Default restart inspection | passed | `python3 tools/local-fixtures/local_api.py restart-cycle` returned `restart_requested: false` and `restart_performed: false`; no App/Core restart was attempted. |
| Follow-up probe | partial | The bounded live probe passed for same-conversation continuation, cancellation, and one-shot replay (`HA_SWITCHBOARD_RUN_FOLLOW_UP=1 ... -k live_follow_up_fixture` — `1 passed`). The harness now supports explicit second-user-token and natural-TTL opt-ins with strict redaction/bounds; those live inputs remain unavailable and were not run. |
| Native-miss probe | passed when explicitly enabled | One bounded Assist run continued through exactly one Switchboard gateway result without recursion; the default suite leaves this live probe opt-in. |

The T084 preserve-first guard now requires a named writable Docker volume with
matching source identity, a settled profile, existing fixture entities, and
the existing Switchboard agent before an explicitly authorized restart. It
rechecks volume identity after each restart phase and emits only bounded
invariants.

## External gates still open

HACS/Hassfest acceptance, GHCR credentials and immutable image proof, public
mirror/tag provenance, protected-master ancestry, multi-architecture image
verification, installed AppArmor parity, live provider acceptance,
migration/rollback, and the public App/Core canary remain pending. Local tests,
metadata, and a disposable image cannot close those gates.

The read-only external records are kept separately in
`external-validation-2026-09-20.md`, `provenance-checks-2026-09-20.md`, and
`t149-t151-provenance-gate-audit-2026-09-20.md`. They confirm local Hassfest
success but show that the public tag/GHCR revision does not match this local
candidate; no publication claim is made.

No publication, push, tag, reset, volume removal, App/Core restart, or provider
request was performed for this evidence record.
