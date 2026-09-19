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
- `.devcontainer/` is test infrastructure only and is not copied into an App
  image.
- `hacs.json`, `custom_components/ha_switchboard/`, and the HACS/Hassfest
  workflows make the Core integration installable as a HACS custom repository.

## Required checks

```bash
python3 -m compileall app/ha_switchboard custom_components/ha_switchboard
pytest -q tests
python3 tools/check_release_boundary.py
```

The private Forgejo workflow builds the App on the dedicated `ha-switchboard`
runner, publishes the `amd64` and `arm64` manifest to
`ghcr.io/grayslawson/ha-switchboard`, and leaves GitHub responsible for the
sanitized source mirror and full GitHub Release. The image reference in
`config.yaml` is therefore a generic multi-architecture manifest, as required
by the Home Assistant App publishing guidance.

The Forgejo repository needs a narrowly scoped `GITHUB_PACKAGE_TOKEN` secret
with permission to publish only the `grayslawson/ha-switchboard` package. It
is separate from the mirror token. The dedicated runner must provide
rootless Podman and support building the checked-in Dockerfile for both target
architectures; the release source does not depend on that runner or any
homelab service at runtime.

Before requesting inclusion in HACS's default catalog, run the HACS and
Hassfest workflows on GitHub, publish a full GitHub Release (not only a tag),
and submit the repository to the integration list in `hacs/default`. HACS
requires the repository to be public on GitHub; the private Forgejo source is
not an HACS distribution source.

When Docker/AppArmor is available, open the product in the official Home
Assistant Apps devcontainer, run `supervisor_run`, install the local `app/`,
and verify:

- Supervisor starts the App on `amd64` and `aarch64` declarations;
- ingress reaches the gateway health/status surface;
- AppArmor permits only the declared runtime behavior;
- `/data` survives restart and App hot backup/restore;
- empty options start without a provider credential; and
- no App action copies files into Home Assistant `custom_components`.

Ingress is Supervisor-only: the App gateway rejects every source address other
than `172.30.32.2`. The standalone Compose path explicitly disables that
Supervisor ingress restriction and must be protected by the user's own network
boundary and gateway token.

The devcontainer itself may require privileged Docker/AppArmor support. That
is a property of the local test harness, not a release permission. The App
manifest must remain non-privileged, non-host-networked, and free of broad
Supervisor/Home Assistant API access unless a separately reviewed feature
changes that boundary.

## Installation contract

The user installs the App and companion integration independently. The
integration owns Home Assistant credentials, entity IDs, event subscriptions,
action execution, and post-action verification. The App receives only
sanitized snapshots and opaque candidate IDs. A standalone Container install
uses the same contract without Supervisor.

## Evidence states

Passing unit tests and a local App build establish source/fixture validation;
they do not establish a public release, an App repository review, or a live
Home Assistant canary. Record those states separately before claiming release
readiness.
