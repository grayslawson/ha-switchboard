# Local closeout evidence — 2026-09-21

This record is sanitized evidence for the v0.2.1 source candidate. It does
not contain Home Assistant credentials, provider keys, gateway tokens, raw
entity identifiers, utterances, or provider response bodies.

## Source and packaging gates

- `python3 -m pytest -q`: **506 passed, 4 skipped**. The skips are the
  unavailable host ConversationEntity/config-flow dependencies and the two
  explicitly opt-in live fixture probes.
- `python3 tools/check_release_boundary.py --versions`: **PASS**.
- `python3 tools/check_release_boundary.py --quality`: **PASS**.
- `python3 tools/check_release_boundary.py`: **PASS**.
- `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools tests`:
  **PASS**.
- `bash -n tools/local-dev.sh tools/app-image-e2e.sh` and `git diff --check`:
  **PASS**.
- Public export plus the release-boundary quality check: **PASS**, 211 tracked
  files and 120 regular files exported.

The coordinated source authorities now declare `0.2.1`. The installed local
canary was refreshed to that source candidate, but this is not proof of a
matching public tag, GHCR image, HACS acceptance, or production canary.

## Preserve-first local runtime

The disposable Home Assistant devcontainer remained `busy_cohen`; its
Supervisor volume identity fingerprint and fixture identity fingerprint were
unchanged. The bounded restart harness now subscribes to the nested Docker
event stream before each mutation, then waits for App `/readyz` or Core HTTP
readiness before taking the one-shot Supervisor check. The explicitly
authorized App/Core cycle completed successfully without resetting or
recreating the volume:

- Core 2026.9.3 remained running, the Supervisor restart command reported
  `result: ok`, and the bounded Core HTTP readiness watcher completed.
- Supervisor and observer endpoints returned HTTP 200.
- App state was `started`.
- The `hassio` HA Switchboard config entry remained present with a gateway
  token configured.
- All 28 fixture entities and the existing Conversation agent remained.
- The gateway profile remained `active`, revisioned, and free of pending
  sections or invalidations.
- The configured option-presence checks remained true; secret values were not
  emitted.

The installed local App was refreshed through Supervisor to candidate version
`0.2.1` from the current staged source. The low-risk Assist control canary
completed with a successful response, and the bounded multi-device Assist
canary verified two exposed devices. The App image label carried the local
source marker; this does not prove a public GHCR digest.

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

The source/provider compatibility boundary was also exercised with a real
OpenRouter-compatible response using sanitized fixture capabilities: the
initial optional structured-output request received a bounded HTTP 400, the
adapter retried once without that optional hint, parsed the bounded JSON
proposal, and the Gateway re-entered it as a confirmation result for a
high-risk lock/cover capability. No provider key, raw request, raw response,
entity identifier, or utterance is retained here. This proves provider
compatibility and confirmation policy at the Gateway boundary; it does not
close the installed Assist continuation/TTL gate above.

The deterministic Core tests still prove user binding, TTL expiry, explicit
affirmative/negative handling, one-shot consumption, and replay protection.
Live follow-up acceptance remains provider-response dependent until a Jev or
fallback configuration that intentionally returns a confirmation decision is
used.

## External gates

Still pending outside this local worktree: protected-master ancestry, public
mirror synchronization, v0.2.1 tag and GitHub Release, GHCR immutable
multi-architecture image/provenance, HACS external action acceptance, App
repository refresh, AppArmor-enforced canary, and installed v0.2.1 rollback
evidence. The existing public v0.2.0 artifact must not be described as this
candidate. The source workflows now allow a bounded 120-second GHCR
build-to-mirror visibility window, but that policy has not been exercised on
the protected publication path.
