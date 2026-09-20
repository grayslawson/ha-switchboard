# Quickstart Validation: HA Switchboard Feature Completeness

This is a validation guide, not an implementation recipe. It is safe for the
existing local development environment: normal commands restart or rebuild
processes but do not remove the Supervisor/Core volume.

**T148 evidence status (2026-09-20): partial.** This quickstart was not
executed as a complete live Supervisor/App/Core acceptance run during this
documentation pass. Its commands and matrix define required evidence; they do
not claim that the fixture, live Assist pipeline, or release canary succeeded.
A detailed sanitized partial run is recorded in
`evidence/local-quickstart-2026-09-20.md`; the status remains partial for
the same unrun lifecycle, provider, security-enforcement, and release gates.
The source metadata in this worktree currently agrees on App/Core version
`0.2.0`; that is source evidence, not an installed or published artifact.

The latest source-level pytest run was `410 passed, 4 skipped`; the skips
require the Home Assistant runtime/config-flow dependency in the host
worktree or are explicitly opt-in live fixture probes. No command in this
documentation pass reset, removed, or
reconfigured the Home Assistant volume. A preserve-first App-only rebuild was
performed and followed by read-only startup/recovery checks; Core was not
restarted and the opt-in restart-cycle was not run.

The preserved local Supervisor harness was also recovered and checked
read-only on this date: Supervisor and Core returned HTTP 200, the App was
started and `/readyz` reported a ready profile, the persisted Core entry and
conversation entity were present, three Assist pipelines were available, and
the fixture covered the published mock domains. This is local-runtime proof,
not public-release or live-provider proof.

**Additional sanitized local evidence (2026-09-20):** Using the preserved
`busy_cohen` harness read-only, `lifecycle` reported the existing
`ha_switchboard` entry, `conversation` agent present, 28 fixture entities, and
an active profile with 28 capabilities and no pending sections or
invalidations. The bounded `scan` command received HTTP 202 and reached
`completion: settled` with an active/no-pending profile; no credentials,
gateway URL, raw entity IDs, or provider response bodies were emitted. The
preserve-first App-only rebuild and subsequent read-only `restart-cycle`
check retained the same volume, config entry, fixture count, and active
profile. This is not proof of the opt-in App/Core restart cycle; that remains
closed by default and requires an explicit disposable-harness authorization.

**Additional sanitized fixture evidence (2026-09-20):** The host-side
`startup` check passed without mutation. The idempotent Assist exposure repair
then reported all 24 executable operation rows present and exposed, while the
2 native-Core-only surfaces were present and unexposed. The bounded disposable
fixture operation matrix verified 24 of 24 service/state transitions. The
source-built App image smoke and isolated image E2E harness both passed,
including non-root runtime, token boundary, ingress, persistence, and
provider-degraded readiness checks. These results do not prove a public image,
Hassfest/HACS acceptance, provider compatibility, or an App/Core restart cycle.
The real fixture Assist follow-up also proved the requested conversation ID,
confirmation cancellation, and replay safety. The harness accepts an
explicitly supplied second-user token and a bounded natural-TTL opt-in, but
those live inputs remain unavailable in this preserved environment; the
default run does not create users or wait on the TTL. Clock-controlled source
tests cover both boundaries.

**Additional native Assist evidence (2026-09-20):** The preserve-first App
rebuild refreshed the installed local image without removing the Supervisor or
Core volume. The repeatable `local_api.py native` check then selected the real
`Switchboard` pipeline with `prefer_local_intents` enabled and accepted a
routine fixture-light request. The live event sequence reached `run-start`,
`intent-start`, `intent-end`, and `run-end` without an error; the fixture state
changed to off and was restored; and the gateway's bounded Jev diagnostic count
did not change (`jev_diagnostic_delta: 0`). The diagnostics endpoint returned
HTTP 200 after the App refresh. The bounded `native_miss_runtime.py` probe
separately verified one completed Assist run, one Switchboard gateway result,
conversation reuse, and no recursion. This closes T153 native success,
provider-bypass, and native-miss continuation evidence. The full
public-release canary remains a separate gate.

## Prerequisites

- The intended feature worktree with the feature branch checked out. Preserve
  unrelated dirty changes; a clean worktree is not required for the read-only
  source checks below.
- Python 3.12+, pytest, Docker or Podman, rsync, curl, and the Home Assistant
  devcontainer CLI or npx fallback.
- A disposable local Home Assistant Supervisor harness.
- Optional provider values in an ignored .env.local file using only:
  HA_SWITCHBOARD_JEV_ENDPOINT, HA_SWITCHBOARD_JEV_API_KEY,
  HA_SWITCHBOARD_GATEWAY_TOKEN, HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES, and
  HA_SWITCHBOARD_PRIVACY_MODE.
- Never use a production Home Assistant URL or production token with fixture
  setup commands.

## Source and contract gates

Run from the repository root:

    python3 -m compileall app/ha_switchboard custom_components/ha_switchboard tools
    python3 -m pytest -q tests
    python3 tools/check_release_boundary.py
    bash tools/app-image-smoke.sh

These are source/image checks, not Home Assistant lifecycle checks. Run only
the checks appropriate to the evidence being collected; no command should
print a secret.

## Preserve-first local App/Core loop

The following commands are the operational acceptance loop and are not part of
the source-only evidence recorded in this pass. If run later, preserve the
existing volume and use the bounded commands; never substitute a reset or
fresh-volume command for missing evidence.

1. Start or reuse the existing local harness:

       tools/local-dev.sh up
       tools/local-dev.sh wait

   If Home Assistant or Supervisor is already running, do not run a reset
   command. The rebuild command is allowed only when an existing container is
   found and preserves the data volume.

2. Refresh the local App store and install the staged App:

       tools/local-dev.sh store
       tools/local-dev.sh install

3. Apply only the explicitly exported or ignored-file test options:

       tools/local-dev.sh configure

   The command must report that credentials were applied without printing their
   values. Use local_only when provider access is not part of the scenario.

4. Synchronize the current Core integration and restart Core only:

       tools/local-dev.sh sync-integration

5. Run the bounded App ingress checks:

       tools/local-dev.sh e2e

6. Install or refresh the idempotent local fixture:

       python3 tools/local-fixtures/install.py

   Follow the fixture README to create the area, exposed entities, groups,
   Assist pipeline, and mock domains. The fixture commands must refuse a
   production host and must not overwrite unrelated Home Assistant data.

## Acceptance matrix

With the fixture profile active, run these scenarios through the dedicated
fixture Assist pipeline and record the returned result plus the post-action
state:

| Scenario | Expected evidence |
| --- | --- |
| Clear built-in Assist intent | Home Assistant's native intent path handles the request before Jev/fallback; no provider call is recorded |
| Read-only state question | Core-local answer, no unnecessary provider payload |
| Unique single-device on/off | Either native HA handling with no provider call, or a typed Jev/Core proposal when native handling does not match; in both cases, verified result |
| Parameterized brightness/volume/temperature | Validated typed value and verified result |
| Ambiguous device | Clarification with safe choices and no write |
| Confirmation-required lock/cover action | Pending confirmation then one verified write |
| Clarification/confirmation follow-up | Same conversation resumes or cancels safely |
| Exposed script/scene row | Profile visibility may include the routine, but `activate` is held out by Core and must not produce a service call |
| Explicit two-device on/off | Both targets preflighted and per-target verified |
| Mixed-availability batch | No silent skip; explicit partial/blocked result |
| Stale profile | Write blocked with rescan guidance |
| Jev invalid/unavailable | Specific provider diagnostic and bounded next step |
| OpenRouter prose fallback | Bounded prose only; no action claim |
| Typed fallback proposal | Same Core gates as a Jev proposal |
| Fallback disabled/privacy blocked | Specific configuration/privacy guidance |
| Manual scan during event/reconcile | Coalesced run, atomic revision, visible outcome |
| App/Core restart | Configuration and last valid profile preserved |

The response must never contain the prohibited generic sentence. Diagnostic
evidence must contain only safe event codes, counts, timing, route class, and
next actions.

## Security and recovery checks

- Call a direct protected endpoint without a token and with an invalid token;
  expect a bounded unauthorized response with no profile data.
- Send an oversized or wrong-content-type request; expect a bounded rejection.
- Inject a stale revision, unknown capability, invalid parameter, and malformed
  provider result; expect no Home Assistant write.
- Inspect App user, AppArmor, manifest permissions, network mode, devices,
  Supervisor API scope, and published ports.
- Restart the App and Core three times; verify config entry, fixture entities,
  profile revision, and diagnostics survive.
- Rotate the gateway token through the supported configuration flow; verify old
  direct calls fail and the updated Core entry reconnects.
- Before any intentional devcontainer/volume removal, take and verify a Docker
  volume snapshot. Normal validation never uses the guarded reset command.

The opt-in restart-cycle and token-rotation checks were not performed in this
documentation pass; the default read-only restart-cycle check did pass.

## Release validation

For a release candidate, additionally run:

    python3 tools/ha-switchboard-export-public.py /tmp/ha-switchboard-public
    python3 /tmp/ha-switchboard-public/tools/check_release_boundary.py --root /tmp/ha-switchboard-public

Run workflow lint, HACS, and Hassfest through the repository CI. Build and
inspect both linux/amd64 and linux/arm64 images. Verify the source revision and
version in the App, Core integration, Python package, changelog, tag, image
labels, and public mirror. Only then run the live App/Core canary and record
its observed runtime state separately from source/CI results.

None of the public-release or live-canary gates above is closed by the local
source evidence in this file.

## Evidence record

For each run record:

- source revision and App/Core versions;
- command and exit status;
- fixture/Supervisor/Core container identity;
- observed profile revision/readiness and config-entry state;
- acceptance scenario and post-action state;
- image digest/architecture if applicable;
- sanitized logs or event codes;
- whether native handling, local read-only, Jev, or fallback handled each
  acceptance scenario;
- any external HACS/App-repository dependency still pending.

Never include tokens, API keys, passwords, raw entity IDs, raw utterances, or
full provider responses in the evidence record.

## Observed source evidence for this pass

- Worktree: `codex/fix-apparmor-runtime`, candidate commit
  `d513f5ef89333e338ddb4a49306c8b97e6f3b2dc`; the implementation and spec
  changes are committed locally, while external publication gates remain open.
- Coordinated source version: `0.2.0` in the App config/image metadata, gateway
  package, Core manifest, and changelog.
- Local source checks: `python3 -m compileall -q app/ha_switchboard
  custom_components/ha_switchboard tools` passed; the full test suite passed
  (`410 passed, 4 skipped`), with two skips requiring the Home Assistant
  runtime/config-flow dependency and two opt-in live fixture probes; the
  focused release, workflow, boundary, and quality tests also passed (`37
  passed`). The sanitized public export
  contains 109 tracked files and passes its release-boundary check; workflow
  lint also passed.
- `python3 tools/check_release_boundary.py` passed, and `git diff --check`
  reported no whitespace errors for the owned paths.
- The preserve-first runtime guards now verify Docker volume identity and
  settled-profile invariants before an explicitly authorized restart; the
  default `restart-cycle` inspection remained read-only with no restart
  performed. Detailed current local-gate results are recorded in
  `evidence/local-checks-2026-09-20.md`.
- Local runtime evidence already recorded above remains disposable-harness
  evidence only. This pass performed a preserve-first App-only rebuild, a
  read-only startup check, a repeatable native Assist check, and a read-only
  restart-cycle inspection; it did not run the opt-in Core/App restart cycle.

The exact external gates still open are protected-master ancestry, public
mirror/tag/Release, GHCR immutable multi-architecture image and source-label
verification, HACS and Hassfest validation on the exported tree, provider
acceptance, complete live Assist/E2E coverage, and the installed App/Core
update, restart, rollback, and canary evidence. Local metadata, tests, a
fixture, or a local image cannot close any of them.

All fixture, local App-image, and E2E output is sanitized disposable-harness
evidence. It must not be presented as proof of a public release, HACS/App
catalog acceptance, or a live production installation.
