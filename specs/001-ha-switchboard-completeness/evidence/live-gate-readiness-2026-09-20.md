# Live Gate Readiness Evidence — 2026-09-20

Status: **partial; read-only readiness checks passed, protected live gates remain
unavailable**. This record covers the bounded checks relevant to T059, T084,
and T148. No Home Assistant or Supervisor restart was requested, and no
provider was contacted.

## Scope and safety

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Branch: `codex/fix-apparmor-runtime`.
- Runtime observation baseline: `799efc422b372ecc8117336a904e426126889e80`;
  coordinated App/Core source version: `0.2.0`. This read-only runtime record
  was not rerun at the present source `HEAD e8538be`.
- Worker-owned file: this evidence file only. Existing concurrent changes were
  preserved.
- The repository-level `just agent-preflight` entrypoint was attempted but was
  unavailable here: `error: no justfile found`. This nested checkout contains
  the HA Switchboard fixture harness rather than the pd-nixos `Justfile`.
- All runtime commands below were bounded and read-only. No reset, removal,
  recreation, restart, auth mutation, configuration mutation, or volume
  mutation was performed.
- Outputs were reduced to counts, booleans, states, and statuses. No user
  identity, token value, raw Home Assistant reference, utterance, credentialed
  URL, or provider response was recorded.

## Exact checks and results

| Check | Exact command | Result |
| --- | --- | --- |
| Local startup readiness | `timeout 60s python3 tools/local-fixtures/local_api.py startup` | **PASS**, exit `0`; `mode=read_only`, `ready=true`, existing App options present, existing Core integration entry present, conversation agent present, 28 fixture records, active gateway profile, revision present, zero pending sections/invalidations, and verified local Supervisor volume identity. |
| Core config-entry verification | `timeout 45s docker exec -i busy_cohen docker exec -i homeassistant python3 - verify < tools/local-fixtures/local_api.py` | **PASS**, exit `0`; exactly one Switchboard config entry, expected source/version, and gateway-token presence reported as a boolean only. |
| Protected restart no-op | `timeout 60s python3 tools/local-fixtures/local_api.py restart-cycle` | **PASS**, exit `0`; `mode=read_only`, `restart_requested=false`, `restart_performed=false`; pre-restart lifecycle and option-presence evidence returned; no restart command was issued. |
| Count-only Core auth-store inspection | `timeout 20s docker exec -i busy_cohen docker exec -i homeassistant python3 - <<'PY' ... PY` (probe below) | **PASS**, exit `0`; auth store readable; 3 user records, 2 non-owner user records, 3 refresh-token records, 1 long-lived access-token record, 1 owner-associated long-lived access-token record, **0 non-owner long-lived access-token records**, and 0 unresolved long-lived access-token records. No identities or token material were printed. |
| Restart/readiness guard tests | `timeout 60s python3 -m pytest -q tests/test_restart_acceptance.py tests/test_e2e_harness.py -k 'restart or startup or follow_up_opt_ins or natural_ttl'` | **PASS**, exit `0`; `18 passed, 9 deselected`. |

The count-only auth probe used this exact body; it emitted counts only:

```bash
timeout 20s docker exec -i busy_cohen docker exec -i homeassistant python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path('/config/.storage/auth').read_text(encoding='utf-8'))['data']
users = {item.get('id'): item for item in data.get('users', []) if isinstance(item, dict)}
records = [item for item in data.get('refresh_tokens', []) if isinstance(item, dict)]
long_lived = [item for item in records if item.get('token_type') == 'long_lived_access_token']
non_owner_users = {key for key, item in users.items() if not item.get('is_owner')}
non_owner_records = [item for item in long_lived if item.get('user_id') in non_owner_users]
owner_records = [item for item in long_lived if users.get(item.get('user_id'), {}).get('is_owner')]
unresolved_records = [item for item in long_lived if item.get('user_id') not in users]
print(json.dumps({
    'auth_store_read': True,
    'user_records': len(users),
    'non_owner_user_records': len(non_owner_users),
    'refresh_token_records': len(records),
    'long_lived_access_token_records': len(long_lived),
    'owner_long_lived_access_token_records': len(owner_records),
    'non_owner_long_lived_access_token_records': len(non_owner_records),
    'unresolved_long_lived_access_token_records': len(unresolved_records),
}, sort_keys=True))
PY
```

## Protected restart preflight contract

The harness source requires all of these conditions before an authorized
restart can issue any restart command:

1. The named disposable Supervisor target is running on the expected local
   port, with exactly one writable Supervisor volume mounted at the expected
   destination. The mount source must resolve to that volume, and the expected
   Supervisor/Core directories must exist.
2. The existing Switchboard config entry and conversation agent must be
   present.
3. Existing local App options must be present.
4. At least one fixture record must be present.
5. The gateway profile must be active, have a revision, and have zero pending
   sections.
6. Every external action is bounded: restart action timeout 30 seconds,
   component readiness wait 60 seconds, and total restart-cycle deadline 120
   seconds.
7. After the App and Core steps, the harness rechecks the volume identity and
   requires preservation of App options, the config entry, fixture count,
   conversation-agent presence, and an active, revision-bearing, zero-pending
   profile.

The observed local state satisfied the read-only portions of this preflight.
The actual App/Core restart cycle is **UNAVAILABLE / NOT RUN** because the
explicit `--allow-restart` authorization was withheld as required for this
worker. The no-op command proved that the default invocation does not issue
either restart command.

## Gate disposition

| Task/gate | Outcome | Evidence and remaining authorization |
| --- | --- | --- |
| T059 auth-store prerequisite | **PASS for inspection; unavailable for second-user live proof** | Two non-owner user records exist, but there are zero non-owner long-lived access-token records. No second-user token was available in the local auth store. |
| T059 different-user live follow-up | **UNAVAILABLE** | Requires an already-issued second user's short-lived access token supplied through the approved local secret mechanism, in memory only, plus explicit approval to run the opt-in live probe. No user creation or auth-store mutation is authorized or needed. |
| T059 natural TTL expiry | **UNAVAILABLE** | Requires explicit approval to enable the bounded natural-expiry opt-in and wait for the real continuation TTL (120 seconds plus the harness safety margin). It was not run. |
| T084 startup/scan/restart readiness | **PARTIAL** | Read-only startup, config-entry verification, and restart no-op passed. The protected App/Core restart cycle remains open until the user explicitly authorizes the disposable-harness `--allow-restart` operation. |
| T148 quickstart live lifecycle portion | **PARTIAL** | Current local startup and config-entry readiness passed; complete quickstart acceptance remains open because the protected restart cycle and other separately gated portions were not run. |
| T148 provider acceptance | **UNAVAILABLE / NOT RUN** | No external provider was invoked. Provider credentials, availability, and wire compatibility remain unproven. |
| T148 AppArmor/security-enforcement runtime proof | **UNAVAILABLE / NOT RUN** | These read-only fixture commands do not prove installed AppArmor enforcement. No security-enforcement mutation or restart was attempted. |
| T149 release acceptance | **PENDING** | No HACS/public-mirror/GHCR/protected-master/installed-canary evidence was produced by this local readiness pass. Existing local export or source checks cannot close the external release gate. |
| T151 publication | **PENDING** | No exact protected-master, public tag/mirror, immutable image, and installed App/Core agreement was established; no publication operation was authorized or attempted. |

No result above is a claim of a completed protected restart, second-user live
authorization, natural expiry, provider acceptance, complete quickstart,
release acceptance, or publication. T059, T084, T148, T149, and T151 remain
open/partial pending their exact missing evidence.
