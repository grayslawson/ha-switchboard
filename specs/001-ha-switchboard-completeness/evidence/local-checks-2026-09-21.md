# Local Validation Evidence — 2026-09-21

Status: **current source and local read-only health checks passed; protected
live and external release gates remain pending**.

This record contains no credentials, provider bodies, raw Home Assistant entity
identifiers, or volume paths.

## Source validation

- Revision: `2c2424b44e5a28f6d8f4b18368f71987002d2fa8` on
  `codex/fix-apparmor-runtime`.
- `python3 -m pytest -q`: **498 passed, 4 skipped**.
- Focused provider/release/preflight tests: **48 passed**.
- `python3 tools/check_release_boundary.py --quality`: **PASS**.
- `python3 tools/check_release_boundary.py`: **PASS**.
- `python3 tools/check_release_boundary.py --versions`: **PASS**.
- Compilation, shell syntax, and `git diff --check`: **PASS**.

The four skips remain expected opt-in/runtime dependency skips. They do not
count as live Home Assistant or external provider proof.

## Read-only runtime health

- Existing local Home Assistant development container remained running.
- Home Assistant endpoint: HTTP 200.
- Supervisor observer endpoint: HTTP 200.
- `python3 tools/local-fixtures/live_gate_preflight.py`: exit `0`, read-only;
  the target identity, existing profile/config-entry/fixture invariants, App
  options, and provider configuration were present. The result correctly
  remained `ready_for_authorized_live_gate=false` because restart authorization,
  a second-user token, and AppArmor enforcement were unavailable.
- No restart, reset, volume mutation, profile scan, provider request, or
  publication operation was performed for this record.

## Remaining gates

T059 still needs the authorized second-user and natural-TTL live probes. T084
still needs the explicitly authorized protected App/Core restart cycle. T148
still needs complete lifecycle/provider/security-enforcement acceptance. T149
and T151 still need public mirror, GHCR, HACS, multi-architecture, protected
master, and installed-canary evidence.
