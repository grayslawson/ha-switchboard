# Release and portability checklist

This is the release boundary for HA Switchboard. It is
intentionally independent from any operator's NixOS or Home Assistant setup.

## Artifacts

- `app/` is the Home Assistant Supervisor App build context.
- `app/README.md`, `app/DOCS.md`, and `app/CHANGELOG.md` are the App Store
  introduction, usage documentation, and release history.
- `custom_components/ha_switchboard/` is a separate Home Assistant Core
  integration artifact.
- `standalone/compose.yaml` runs the same gateway image for Home Assistant
  Container users.
- `hacs.json`, `custom_components/ha_switchboard/`, and the Forgejo validation
  workflow make the Core integration installable as a HACS custom repository.

## Required checks

```bash
python3 -m compileall app/ha_switchboard custom_components/ha_switchboard
python3 -m pytest -q tests
# Private Forgejo checkout: lint the self-hosted workflows.
actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml
python3 tools/check_release_boundary.py
tools/app-image-smoke.sh
```

The checked-in image smoke harness is intentionally local and credential-free.
It builds the App image with Podman or Docker, checks the non-root runtime
identity and gateway health/readiness behavior, reconciles a sanitized fixture,
and recreates the container to confirm persisted state returns stale and
fail-closed. Forgejo runs the same amd64 smoke path on trusted repository
events; pull requests from untrusted forks do not execute submitted container
code on the self-hosted runner.

The actionlint command applies to the private Forgejo source checkout; the
public export intentionally omits the private `.forgejo/` workflows and their
runner configuration.

The private completeness quickstart provides a preserve-first local
acceptance walkthrough when working from the full source checkout. It
identifies which commands may restart or reconfigure the disposable harness
and keeps incomplete live/provider/public gates explicitly open.

The release pipeline builds the App for `amd64` and `arm64` and publishes the
multi-architecture image referenced by `app/config.yaml` to
`ghcr.io/grayslawson/ha-switchboard`. The source tree and image are independent
of any particular Home Assistant installation, CI host, or private network.
Registry credentials used by automation must be narrowly scoped to the
published package and must never be committed to the repository.

Branch builds publish `latest` only. A matching `v<app/config.yaml version>`
tag publishes the versioned image. The image carries the source revision label,
and the GitHub mirror release waits for both architectures at that exact
revision before creating its public tag and Release. Existing public release
tags are not force-moved on reruns. These are release gates, not a substitute
for a live Home Assistant canary.

The coordinated source version in this checkout is `0.2.1`. It is a source
release candidate, not a published or complete release. The App remains
marked `experimental`, and the limitations below are part of the contract.
A local version is not public-release evidence. Verify the matching tag,
multi-architecture image, and GitHub Release before announcing availability.

### Version policy

Use one semantic version for the App, image tag, Python package, Core
manifest, and changelog entry. The release authorities are, in order:

1. `app/config.yaml` and `app/Dockerfile` for the Supervisor App and image;
2. `app/ha_switchboard/__init__.py` and `pyproject.toml` for the gateway
   package;
3. `custom_components/ha_switchboard/manifest.json` for the Core artifact; and
4. `app/CHANGELOG.md` for the human-readable source history.

The private Forgejo revision is the source identity. A `v<version>` tag may be
created only from protected `master`, and the public mirror, GitHub Release,
and GHCR image must all point to that same revision. A source edit, local image,
branch, or changelog entry must never be described as a published release.
When a version changes, update all authorities in one reviewed change and
re-run the source-version checks before any external publication.

The OCI source label proves image provenance but does not by itself connect a
package that was pushed with a personal access token to the GitHub repository.
After the first GHCR publication, the package owner must use GitHub's package
page to connect `ha-switchboard` to `grayslawson/ha-switchboard`; the repository
sidebar may otherwise continue to show “No packages published” even while the
public image and its tags are pullable. Do not delete and recreate the package
just to change this association.

For a HACS **custom repository**, [GitHub Releases are optional](https://www.hacs.xyz/docs/publish/integration/):
HACS can install the default branch. Before requesting inclusion in HACS's
**default catalog**, publish a full GitHub Release, run and pass the public
GitHub HACS and Hassfest Actions required by the
[default repository rules](https://www.hacs.xyz/docs/publish/include/), and
submit the repository to `hacs/default`. Private Forgejo jobs alone do not
satisfy that public Actions requirement. Keep the custom-repository path until
those gates are proven on the exported GitHub tree.

This project enables HACS release-archive installation with
`hacs.json`'s `filename: "ha_switchboard.zip"`. The public mirror workflow
creates that asset from the exported `custom_components/ha_switchboard/`
directory and attaches it to each tagged GitHub Release. The asset name and
archive layout are release-contract values; changing either requires updating
the workflow and the HACS metadata together.

When Docker/AppArmor is available, use the official Home Assistant Apps test
harness (or an equivalent local harness), install the local `app/`, and
verify:

- Supervisor starts the App on `amd64` and `aarch64` declarations;
- browser ingress reaches the gateway UI and health/status surface;
- AppArmor permits only the declared runtime behavior;
- `/data` survives restart and App hot backup/restore;
- empty options start without a provider credential; and
- no App action copies files into Home Assistant `custom_components`.

The browser UI is Supervisor-ingress-only (`172.30.32.2`). The companion Core
integration reaches the gateway over the internal App network with a matching
gateway bearer token; unauthenticated direct API calls are rejected. The
standalone Compose path has no Supervisor ingress boundary and must be
protected by the user's own network controls and token. Compose passes the Jev
model, privacy mode, and separate fallback settings; its privacy default is
`local_only`, so hosted Jev/fallback behavior requires an explicit privacy
choice.

The local test harness may require privileged Docker/AppArmor support. That is
test infrastructure, not an App runtime permission. The source App manifest
must remain non-privileged, non-host-networked, and free of broad Supervisor
and Home Assistant API access unless a separately reviewed feature changes
that boundary. The current runtime still uses Supervisor's scoped self-
information and discovery endpoints for option loading and registration.

## Installation contract

The user installs the App and companion integration independently. The
integration owns Home Assistant credentials, entity IDs, event subscriptions,
action execution, parameter schemas, follow-up authorization, and post-action
verification. The App receives only sanitized snapshots and opaque candidate
IDs. Core-local clarification, parameter, and confirmation context is
short-lived, user-bound, and one-time consumed; it is not persisted by the App
or sent to providers. The current native OpenRouter Decisions question set
does not elicit action parameters; a compatible Jev service or adapter must
supply typed values for parameterized controls. A standalone Container install
uses the same contract without Supervisor.

Home Assistant's own Conversation/Assist intent matching remains the fast path
for clear built-in commands. The integration does not replace those native
handlers, and Jev is not a universal simple-command classifier. Assist from
the mobile app or dashboards, voice satellites/Wyoming or ESPHome, native
Conversation, and `conversation.process` remain the supported Home Assistant
channels. Switchboard's Conversation entity adds bounded routing for requests
that need ambiguity, compound-action, or risk judgment; configured fallback is
reserved for open-ended requests and cannot execute Home Assistant services.

Provider configuration must keep its contracts separate: direct TypeSafe
System One uses the runtime `JEV_PROVIDER=typesafe`, base URL, API key, and
model inputs; OpenRouter Decisions uses the exact alpha Decisions URL and App
`jev_*` options; a generic Jev URL must return Switchboard's typed decision
envelope; and the `openrouter` fallback is a generic OpenAI-compatible
chat-completions route with its own endpoint, API key, and model. Do not claim
that one URL or model setting configures all four contracts.

## Evidence states

Passing unit tests and a local App build establish source/fixture validation;
they do not establish a public release, an App repository review, or a live
Home Assistant canary. Record those states separately before claiming release
readiness.

For this 0.2.1 checkout, the documented supported boundary is the bounded
Conversation/profile/provider behavior in the root README. Complete live
follow-up acceptance, native OpenRouter parameter extraction, executable
script/scene activation, full Home Assistant surface coverage, and HACS/App
repository acceptance are not release-complete claims. A release candidate
must either add evidence for those requirements or keep them explicitly listed
as limitations.

Local evidence must be reported as checkout/harness evidence, not public or
live-install evidence. HACS installation/update behavior remains unverified
until its public repository flow is exercised. Refresh or reinstall an App
before treating a cached Supervisor manifest as proof of current source
permissions.

For each release candidate, record these evidence items independently:

| Gate | Required evidence | What it does not prove |
| --- | --- | --- |
| Source and tests | Version consistency, compile, focused/full pytest, release-boundary and quality checks | A published image or public mirror |
| App artifact | Local non-root image smoke plus amd64/arm64 GHCR manifest at the exact source revision | That Supervisor has refreshed a cached App |
| Core integration | HACS/Hassfest validation on the exported public tree and local config-entry/Assist fixture verification | Production Home Assistant compatibility for every integration |
| Migration and rollback | Upgrade from the previous version, preserved config entry/profile state, and a documented rollback to the previous image/tag | That a rollback was safe without testing the target installation's backup |
| Public publication | Matching GitHub mirror commit, tag, GitHub Release, GHCR tags/digest/source label, and package association | Download or usage counts from Docker/GitHub unless those services expose them |
| Canary | A disposable or explicitly approved Home Assistant App/Core installation with profile reconciliation and a read-only then low-risk Assist action | General production readiness |

The fixture command `tools/local-fixtures/local_api.py verify` provides the
Core config-entry portion of local evidence without printing gateway tokens.
It is not a substitute for the public HACS/Hassfest gate or a live canary.

## Update, migration, and rollback evidence

An update is accepted only as a coordinated App/Core pair. Before changing
anything, record the current App version and image digest, Core integration
version/source revision, config-entry presence, profile status/generation, and
the verified Supervisor backup or volume snapshot identifier. Redact tokens,
API keys, hostnames, entity IDs, and raw Home Assistant conversation content.
The ordinary local development loop must keep the existing Supervisor/Core
volume; do not reset, recreate, or uninstall it to make an update appear
successful.

After installing the candidate App and matching Core artifact, record the
candidate version/revision, App `readyz`, Core config-entry state, a complete
`profile_reconciled` result, and one read-only Assist/Conversation result before
trying a low-risk control. A cached Supervisor manifest is not migration
evidence: refresh or reinstall the App and verify the installed metadata and
image digest.

Rollback evidence must name the exact previous App image tag/digest and the
matching previous Core artifact. Restore the verified backup or snapshot if a
schema migration is not reversible; then confirm the same config entry,
profile recovery, readiness, and read-only check. Never roll back only the App
or only the Core integration. A failed migration, missing config entry,
stale/unreconciled profile, or unverified image blocks publication and is
recorded as pending rather than silently worked around.

## Artifact provenance evidence

For the candidate and the rollback target, retain a secret-free record of the
Forgejo commit SHA, protected-master ancestry result, semantic version, image
reference and immutable digest, `amd64` and `arm64` manifest entries, and OCI
source/revision labels. Compare the GHCR result with the exact source revision
using `tools/verify-ghcr-image.py`; a successful local build or a mutable
`latest` tag is not enough. The verifier checks a registry-provided
`Docker-Content-Digest` when present and hashes the exact response bytes when a
registry such as GHCR omits that optional blob header; either path must match
the manifest's immutable config descriptor. Then record the public mirror ref,
GitHub tag and Release, and package-to-repository association separately.
Missing, stale, or unreadable external metadata is a failed gate, not a reason
to infer success.

## Live-canary evidence

Live-canary evidence is separate from unit tests, a local fixture, image smoke,
HACS, Hassfest, or a source checkout. It must identify the installed App/Core
pair and timestamp, while omitting secrets and household identifiers. The
minimum canary is: App ready; Core integration configured; complete profile
reconciled; native Home Assistant read-only Assist path checked; then one
explicitly low-risk exposed-device action checked for Core execution and
post-action verification. Capture the observed states and exact revision or
digest, not raw requests or provider responses. If the target Supervisor,
public HACS flow, provider contract, or App/Core installation is unavailable,
the canary remains pending and the release is not complete.

## External acceptance dependencies (T150)

These dependencies are reviewed separately because none is proven by local
source tests:

| Dependency | Required external check | Current status in this checkout |
| --- | --- | --- |
| Home Assistant App repository/Supervisor | Public repository index, App metadata refresh, `amd64`/`aarch64` image pull, AppArmor/ingress, update and hot-backup/restore | Pending public App publication and installed canary; local harness evidence is not a public App review |
| HACS custom repository | Exported public tree, HACS validation, Core manifest/install/update path, and GitHub authentication | Pending HACS/App acceptance; custom-repository instructions remain the supported path |
| Hassfest and public mirror | Hassfest on the exported tree plus matching GitHub mirror commit/tag/Release | Pending T149/T151 |
| GHCR | Immutable multi-architecture manifest and OCI source/revision labels, with package association | Pending external registry evidence |
| Jev/TypeSafe and OpenRouter | Provider availability, authentication, exact wire contract, privacy-mode eligibility, bounded response, and failure behavior | Pending provider-specific canary; no provider credential or availability claim is stored here |
| OpenAI-compatible or typed HTTP fallback | Endpoint contract, model/key separation, hosted privacy policy, refusal of tool calls, and bounded proposal behavior | Source-tested contract; live provider acceptance is pending |

The remaining release gates are intentionally explicit: T148 (complete
quickstart evidence), T149 (all source/image/runtime/HACS/Hassfest/mirror/GHCR
and canary gates), and T151 (protected-master publication only after those
artifacts agree). This checkout does not publish, tag, push, or call `0.2.1`
complete.
