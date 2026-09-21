# Local closeout evidence — 2026-09-21

This record is sanitized evidence for the v0.2.1 source candidate. It does
not contain Home Assistant credentials, provider keys, gateway tokens, raw
entity identifiers, utterances, or provider response bodies.

## Source and packaging gates

- `python3 -m pytest -q`: **498 passed, 4 skipped**. The skips are the
  unavailable host ConversationEntity/config-flow dependencies and the two
  explicitly opt-in live fixture probes.
- `python3 tools/check_release_boundary.py --versions`: **PASS**.
- `python3 tools/check_release_boundary.py --quality`: **PASS**.
- `python3 tools/check_release_boundary.py`: **PASS**.
- `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools tests`:
  **PASS**.
- `bash -n tools/local-dev.sh tools/app-image-e2e.sh` and `git diff --check`:
  **PASS**.
- Public export plus the release-boundary quality check: **PASS**, 210 tracked
  files and 120 regular files exported.

The coordinated source authorities now declare `0.2.1`. This is source
evidence only; it is not proof that a matching public tag, GHCR image, HACS
acceptance, or installed canary exists.

## Preserve-first local runtime

The disposable Home Assistant devcontainer remained `busy_cohen`; its
Supervisor volume identity fingerprint and fixture identity fingerprint were
unchanged. The approved App/Core restart attempt briefly hit a post-App
lifecycle readiness race in the harness. The recovery was not retried in a
loop: the existing App was verified started, the Core was restarted once with
the official `ha core restart --raw-json` command, and the resulting checks
passed:

- Core 2026.9.3 reported `result: ok` and `state: running`.
- Supervisor and observer endpoints returned HTTP 200.
- App state was `started`.
- The `hassio` HA Switchboard config entry remained present with a gateway
  token configured.
- All 28 fixture entities and the existing Conversation agent remained.
- The gateway profile remained `active`, revisioned, and free of pending
  sections or invalidations.
- The configured option-presence checks remained true; secret values were not
  emitted.

The harness's one-shot post-App lifecycle check should be improved to wait on
the App/Core readiness boundary before a future automated restart-cycle run.
The explicit recovery result above is the accepted local runtime evidence for
this candidate.

## Provider and follow-up behavior

The local OpenRouter Decisions configuration was exercised through the real
Assist pipeline:

- Native routine light handling completed with a zero Jev diagnostic delta.
- A normal fixture light control completed and returned a verified `Done.`
  response.
- The lock/cover follow-up fixture did not produce a confirmation from the
  configured OpenRouter decision response. The provider refused or clarified
  those high-risk requests, so the live confirmation/cancellation/replay and
  natural-TTL gates were not falsely marked proved.
- A temporary non-owner HA user was created through the supported local Core
  auth API, used only in memory for the bounded cross-user probe, and deleted
  afterward. The probe preserved the fixture lock state and emitted no auth
  material.

The deterministic Core tests still prove user binding, TTL expiry, explicit
affirmative/negative handling, one-shot consumption, and replay protection.
Live follow-up acceptance remains provider-response dependent until a Jev or
fallback configuration that intentionally returns a confirmation decision is
used.

## External gates

Still pending outside this local worktree: protected-master ancestry, public
mirror synchronization, v0.2.1 tag and GitHub Release, GHCR immutable
multi-architecture image/provenance, HACS external action acceptance, App
repository refresh, AppArmor-enforced canary, and installed v0.2.1 update/
rollback evidence. The existing public v0.2.0 artifact must not be described
as this candidate.
