# Quickstart Validation: HA Switchboard Feature Completeness

This is a validation guide, not an implementation recipe. It is safe for the
existing local development environment when its preserve-first rules are
followed: normal commands may restart or rebuild processes, but do not remove
the Supervisor/Core volume. The local-dev commands below can still create,
configure, or restart the disposable harness. The current closeout used only
bounded, explicitly authorized runtime actions; it did not reset, recreate, or
delete the Home Assistant volume. See the sanitized closeout record for the
commands and results.

**T148 evidence status (2026-09-21): partial.** This quickstart is not a
complete public release acceptance run. Its commands and matrix define
required evidence; they do not claim that every fixture scenario, live
provider path, or release canary succeeded. The current sanitized closeout is
recorded in `evidence/local-closeout-2026-09-21.md`, alongside the earlier
local records. The local provider boundary, preserve-first restart cycle, and
installed v0.2.1 disposable canary now pass. The status remains partial for
the provider-dependent high-risk follow-up, AppArmor enforcement on this WSL
host, and the external publication gates.

The current source-level run for candidate `0.2.1` was `511 passed, 4
skipped`.
The tracked credential-free `tools/standalone-smoke.sh` is now included in
the public export allowlist and the export regression check passes. External
T149 gates remain open.
The skips are the unavailable host ConversationEntity/config-flow dependencies
and two explicitly opt-in live fixture probes. The authorized App/Core
restart-cycle harness now subscribes before mutation and waits for actual App
or Core service readiness. The cycle passed without changing the
Supervisor/Core volume or fixture set. The installed local App was refreshed
to v0.2.1 and completed both a low-risk control and a bounded two-device
Assist canary.

The preserved local Supervisor harness was checked read-only on this date:
`local_api.py startup` reported `mode=read_only`, `ready=true`, the existing
`ha_switchboard` entry, the conversation agent, 28 fixture entities, 28 active
capabilities, a revision, and zero pending sections/invalidations. This is
local-runtime proof, not public-release or live-provider proof. The bounded
startup check exited `0`. The default restart inspection also exited `0` with
`restart_requested=false` and `restart_performed=false`; the explicitly
authorized restart attempt and bounded recovery are described in
`evidence/local-closeout-2026-09-21.md`.

The same read-only slice reran compilation, both release-boundary checks, the
public export and exported-tree boundary, `bash tools/standalone-smoke.sh`,
and the credential-free Podman App-image smoke/E2E checks. All exited `0`;
AppArmor enforcement was unavailable on this host and no profile was
requested. The current closeout adds the bounded provider and local-runtime
evidence recorded in the 2026-09-21 closeout record.

**Additional sanitized local evidence (2026-09-20):** Earlier bounded local
records show `lifecycle`, `profile`, and `scan` evidence: the scan received
HTTP 202 and reached `completion: settled` with an active/no-pending profile.
The earlier scan record was not rerun in this read-only reconciliation. The
default `restart-cycle` inspection was rerun as a no-op, and it does not prove
the opt-in App/Core restart cycle. The separate readiness record is historical;
the current closeout records the temporary non-owner probe and the authorized
restart attempt without retaining its credentials.

**Additional sanitized fixture evidence (2026-09-20):** Earlier bounded
fixture records reported all 24 executable operation rows present and exposed,
the 2 native-Core-only surfaces present and unexposed, and 24 of 24 direct
service/state transitions verified. Earlier local image/E2E records also
reported non-root, token-boundary, ingress, persistence, and
provider-degraded-readiness checks. Those are local records, not public-image,
HACS/Hassfest, provider-compatibility, or App/Core restart proof. The
provider-backed follow-up record proves same-conversation confirmation,
cancellation, and one-shot replay safety; second-user and natural-TTL inputs
remain unavailable. The current read-only pass did not rerun these
mutating/opt-in probes.

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

- Worktree: `codex/fix-apparmor-runtime`, current candidate with the validation
  hardening in this closeout. External publication gates remain open.
- Coordinated source version: `0.2.1` in the App config/image metadata, gateway
  package, Core manifest, and changelog.
- Current local source checks: `python3 -m compileall -q
  app/ha_switchboard custom_components/ha_switchboard tools tests` passed;
  `python3 -m pytest -q tests` passed (`511 passed, 4 skipped`); and
  `python3 tools/check_release_boundary.py --quality` passed. The current
  skips are the unavailable host ConversationEntity/config-flow dependencies
  and two opt-in live fixture probes. `git diff --check` is clean for the
  owned paths.
- The current read-only public export passed as `public export: PASS`; its
  temporary export contained 120 regular files and
  `check_release_boundary.py --root` passed. This is local export evidence,
  not HACS, public-mirror, GHCR, or release proof.
- The preserve-first runtime guards verify Docker volume identity and
  settled-profile invariants before an explicitly authorized restart. The
  successful event-driven App/Core restart cycle is recorded in
  `evidence/local-closeout-2026-09-21.md`.
- Local runtime evidence already recorded above remains disposable-harness
  evidence only. This pass performed a preserve-first App update to v0.2.1,
  a read-only startup check, low-risk and multi-device Assist canaries, and
  the explicitly authorized event-driven App/Core restart cycle.

The exact gates still open are the provider-dependent live portions of T059,
the complete T148 quickstart, and T149/T151 publication and canary evidence.
That includes a second-user and natural-TTL follow-up, installed AppArmor
enforcement, HACS, public
mirror/tag/release agreement, GHCR immutable multi-architecture provenance,
and installed rollback evidence. Local metadata, tests, a fixture, or a local
image cannot close any of those external gates.

All fixture, local App-image, and E2E output is sanitized disposable-harness
evidence. It must not be presented as proof of a public release, HACS/App
catalog acceptance, or a live production installation.
