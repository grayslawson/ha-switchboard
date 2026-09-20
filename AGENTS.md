# HA Switchboard agent instructions

This repository is developed alongside a persistent Home Assistant Supervisor
devcontainer. Treat the App/Core volume, fixtures, config entries, Assist
pipelines, and profile state as user-owned data.

## Preserve-first runtime boundary

- Never reset, remove, recreate, uninstall, or replace the local Home
  Assistant/Supervisor volume to obtain a clean test result.
- Do not restart or rebuild Home Assistant/Core without explicit coordinator
  authorization for that specific operation. App-only rebuilds must use the
  preserve-first wrapper and must verify the existing config entry, fixtures,
  pipelines, and active profile afterward.
- Never print, commit, or place credentials, tokens, raw provider payloads, or
  decrypted Home Assistant auth data in logs, evidence, prompts, or fixtures.
- Keep source state, local runtime state, CI/release state, and public artifact
  state separate; a passing source test is not live or published proof.

## Delegation and completion watcher

- Every delegated agent and subagent must return on completion, failure, or
  required attention. Do not poll repeatedly, launch hidden long-running
  probes, or emit periodic progress loops.
- The coordinator uses one bounded event-driven wait for each delegated group
  and integrates completion notifications when they arrive. A timeout is not
  permission to restart the environment or duplicate the work.
- Delegated edits must have an explicit, disjoint file scope. Workers must not
  revert or overwrite other agents' dirty changes.

## Verification

- Prefer bounded, sanitized local fixture checks. Record exact evidence and
  leave incomplete external gates open rather than inferring success.
- Run focused checks for owned files, then the full suite and release boundary
  checks before landing related work.
