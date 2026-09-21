# T084 Recovery-Safety Evidence — 2026-09-20

Status: **partial; source guards and regression checks passed, protected
App/Core restart remains explicitly unauthorized**.

## Scope and safety

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Branch: `codex/fix-apparmor-runtime`.
- Owned changes: `tools/local-fixtures/local_api.py`, T084-specific tests in
  `tests/test_e2e_harness.py`, and this evidence record.
- `just agent-preflight` was attempted but is unavailable in this nested
  checkout (`error: no justfile found`).
- No restart, reset, volume snapshot/removal, volume mutation, configuration
  mutation, provider request, commit, or secret output was performed.

## Implemented T084 hardening

- Restart authorization is type-strict: only the CLI-produced boolean `True`
  can enter the mutating branch; truthy strings or integers remain the
  read-only inspection path.
- The bounded Core restart command now rejects non-empty malformed output and
  Supervisor JSON responses whose result is not `ok`. Empty output remains
  accepted for wrappers that intentionally suppress successful stdout.
- Existing preserve-first checks remain in force: canonical disposable
  Supervisor identity, named writable volume and stable fingerprint, existing
  config entry/token, App options, conversation agent, fixture count and
  fingerprint, settled profile, and post-App/post-Core volume identity.

## Exact checks

| Check | Result |
| --- | --- |
| `python3 -m pytest -q tests/test_e2e_harness.py -k 'startup or t084 or restart' tests/test_restart_acceptance.py -k 'restart or bounded_timeout or component_wait'` | **PASS** — 23 passed, 16 deselected |
| `python3 -m pytest -q tests/test_e2e_harness.py tests/test_local_dev.py tests/test_restart_acceptance.py` | **PASS** — 47 passed, 1 skipped; the skip is the opt-in live disposable Home Assistant follow-up probe |
| `python3 -m compileall -q tools/local-fixtures/local_api.py tests/test_e2e_harness.py` | **PASS** |
| `git diff --check` | **PASS** |

The tests use mocked host actions only. They prove the guard behavior and
bounded error handling; they are not live App/Core restart evidence.

## Remaining authorization and evidence

T084 remains **PARTIAL**. The protected cycle must still be separately
authorized for this disposable harness with `python3
tools/local-fixtures/local_api.py restart-cycle --allow-restart`. If authorized,
the operator must retain the bounded output and verify App then Core recovery:
unchanged volume fingerprint, App options, config entry/token presence,
fixture count/fingerprint, conversation agent, and an active revisioned profile
with zero pending sections/invalidations. The cycle is not authorized by this
worker and was not run.

The existing `tools/local-dev.sh` lifecycle commands that restart Core/App are
also outside this worker's authorization. They must continue to use the
existing harness and preserve its volume; no reset or replacement is an
acceptable substitute for the missing cycle evidence.
