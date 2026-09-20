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

The App, Core, and Python package version in this checkout is `0.2.0`.
A local version is not public-release evidence. Verify the matching tag,
multi-architecture image, and GitHub Release before announcing availability.

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
action execution, parameter schemas, and post-action verification. The App
receives only sanitized snapshots and opaque candidate IDs. The current Jev
question set does not elicit action parameters; a compatible Jev service or
adapter must supply typed values for parameterized controls. A standalone
Container install uses the same contract without Supervisor.

## Evidence states

Passing unit tests and a local App build establish source/fixture validation;
they do not establish a public release, an App repository review, or a live
Home Assistant canary. Record those states separately before claiming release
readiness.

Local evidence must be reported as checkout/harness evidence, not public or
live-install evidence. HACS installation/update behavior remains unverified
until its public repository flow is exercised. Refresh or reinstall an App
before treating a cached Supervisor manifest as proof of current source
permissions.
