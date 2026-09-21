# Quickstart Validation: HA Switchboard Feature Completeness

This is a validation guide, not an implementation recipe. It is safe for the
existing local development environment when its preserve-first rules are
followed: normal commands may restart or rebuild processes, but do not remove
the Supervisor/Core volume. The local-dev commands below can still create,
configure, or restart the disposable harness. This documentation pass did
not run those mutating commands, any opt-in restart, token rotation, or
provider request.

**T148 evidence status (2026-09-20): partial.** This quickstart is not a
complete live Supervisor/App/Core acceptance run. Its commands and matrix
define required evidence; they do not claim that every fixture scenario,
live provider path, or release canary succeeded. A detailed sanitized partial
run is recorded in `evidence/local-quickstart-2026-09-20.md`; the status
remains partial for the unrun lifecycle, provider, security-enforcement, and
release gates. The current source metadata agrees on App/Core version `0.2.0`,
but that is source evidence, not installed or published-artifact proof.

The current source-level run at `HEAD`
`f05fada427fd2c503e370724de4a80d0ebe60e4b` was `473 passed, 4 skipped`.
The tracked credential-free `tools/standalone-smoke.sh` is now included in
the public export allowlist and the export regression check passes. External
T149 gates remain open.
The skips are the unavailable host ConversationEntity/config-flow dependencies
and two explicitly opt-in live fixture probes. No command in this
reconciliation reset, removed, recreated, reconfigured, or restarted the
Home Assistant volume or Core. The current read-only startup check passed;
the opt-in restart cycle was not run.

The preserved local Supervisor harness was checked read-only on this date:
`local_api.py startup` reported `mode=read_only`, `ready=true`, the existing
`ha_switchboard` entry, the conversation agent, 28 fixture entities, 28 active
capabilities, a revision, and zero pending sections/invalidations. This is
local-runtime proof, not public-release or live-provider proof.

**Additional sanitized local evidence (2026-09-20):** Earlier bounded local
records show `lifecycle`, `profile`, and `scan` evidence: the scan received
HTTP 202 and reached `completion: settled` with an active/no-pending profile.
The default `restart-cycle` inspection was a no-op. These checks were not
rerun in this read-only reconciliation, and they do not prove the opt-in
App/Core restart cycle. The separate readiness record confirms that no
non-owner access token is available for the cross-user probe and that the
protected restart preflight was ready but not authorized.

**Additional sanitized fixture evidence (2026-09-20):** Earlier bounded
fixture records reported all 24 executable operation rows present and exposed,
the 2 native-Core-only surfaces present and unexposed, and 24 of 24 direct
service/state transitions verified. Earlier local image/E2E records also
reported non-root, token-boundary, ingress, persistence, and
provider-degraded-readiness checks. Those are local records, not public-image,
HACS/Hassfest, provider-compatibility, or App/Core restart proof. The live
follow-up record proves same-conversation continuation, cancellation, and
replay safety; second-user and natural-TTL inputs remain unavailable. The
current read-only pass did not rerun these mutating/opt-in probes.

**Additional native Assist evidence (2026-09-20):** Earlier bounded records
show the real `Switchboard` pipeline with `prefer_local_intents`, a completed
native event sequence, fixture-state restoration, and
`jev_diagnostic_delta: 0`. The separate native-miss probe reported one
completed Assist run, one Switchboard gateway result, conversation reuse, and
no recursion. This is local native/provider-bypass evidence only; the current
read-only pass did not rerun it, and the full public-release canary remains a
separate gate.

## Prerequisites

- The intended feature worktree with the feature branch checked out. Preserve
  unrelated dirty changes; a clean worktree is not required for the read-only
  source checks below.
- Python 3.12+, pytest, Docker or Podman, rsync, curl, and the Home Assistant
  devcontainer CLI or npx fallback.
- A disposable local Home Assistant Supervisor harness.
- Optional provider values in an ignored .env.local file using only:
  HA_SWITCHBOARD_JEV_ENDPOINT, HA_SWITCHBOARD_JEV_API_KEY,
  HA_SWITCHBOARD_FALLBACK_PROVIDER, HA_SWITCHBOARD_FALLBACK_ENDPOINT,
  HA_SWITCHBOARD_FALLBACK_MODEL, HA_SWITCHBOARD_FALLBACK_API_KEY,
  HA_SWITCHBOARD_GATEWAY_TOKEN, HA_SWITCHBOARD_PROFILE_REFRESH_MINUTES, and
  HA_SWITCHBOARD_PRIVACY_MODE. The fallback variables are optional and must
  remain separate from the Jev variables.
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

Run private workflow lint, HACS, and Hassfest through the repository's
documented release path. The pinned Hassfest container may also be run against
a read-only public export locally; HACS still requires its authorized public
repository/action path. Build and inspect both linux/amd64 and linux/arm64
images. Verify the source revision and
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

- Worktree: `codex/fix-apparmor-runtime`, current `HEAD`
  `f05fada427fd2c503e370724de4a80d0ebe60e4b`. External publication gates
  remain open.
- Coordinated source version: `0.2.0` in the App config/image metadata, gateway
  package, Core manifest, and changelog.
- Current local source checks: `python3 -m compileall -q
  app/ha_switchboard custom_components/ha_switchboard tools tests` passed;
  `python3 -m pytest -q tests` passed (`473 passed, 4 skipped`); and
  `python3 tools/check_release_boundary.py --quality` passed. The current
  skips are the unavailable host ConversationEntity/config-flow dependencies
  and two opt-in live fixture probes. `git diff --check` is clean for the
  owned paths.
- The current read-only public export passed as `public export: PASS (207
  tracked files)`; its temporary export contained 119 regular files and
  `check_release_boundary.py --root` passed. This is local export evidence,
  not HACS, public-mirror, GHCR, or release proof.
- The preserve-first runtime guards now verify Docker volume identity and
  settled-profile invariants before an explicitly authorized restart; the
  default `restart-cycle` inspection remained read-only with no restart
  performed. Detailed current local-gate results are recorded in
  `evidence/local-checks-2026-09-20.md`.
- Local runtime evidence already recorded above remains disposable-harness
  evidence only. This pass performed a preserve-first App-only rebuild, a
  read-only startup check, a repeatable native Assist check, and a read-only
  restart-cycle inspection; it did not run the opt-in Core/App restart cycle.

The exact gates still open are the authorized live portions of T059 and T084,
the complete T148 quickstart, and T149/T151 publication and canary evidence.
That includes second-user/natural-TTL follow-up, the protected App/Core
restart cycle, provider acceptance, installed AppArmor enforcement, HACS,
public mirror/tag/release agreement, GHCR immutable multi-architecture
provenance, and installed update/restart/rollback/canary evidence. Local
metadata, tests, a fixture, or a local image cannot close any of them.

All fixture, local App-image, and E2E output is sanitized disposable-harness
evidence. It must not be presented as proof of a public release, HACS/App
catalog acceptance, or a live production installation.
