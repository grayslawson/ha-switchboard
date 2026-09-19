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
pytest -q tests
python3 tools/check_release_boundary.py
```

The release pipeline builds the App for `amd64` and `arm64` and publishes the
multi-architecture image referenced by `app/config.yaml` to
`ghcr.io/grayslawson/ha-switchboard`. The source tree and image are independent
of any particular Home Assistant installation, CI host, or private network.
Registry credentials used by automation must be narrowly scoped to the
published package and must never be committed to the repository.

Before requesting inclusion in HACS's default catalog, pass the HACS and
Hassfest jobs in Forgejo, publish a full GitHub Release through the Forgejo
mirror workflow (not only a tag), and submit the repository to the integration
list in `hacs/default`. HACS requires the repository to be public on GitHub and
a full GitHub Release to be available; a tag alone is not sufficient for the
normal update flow.

When Docker/AppArmor is available, use the official Home Assistant Apps test
harness (or an equivalent local harness), install the local `app/`, and
verify:

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

The local test harness may require privileged Docker/AppArmor support. That is
test infrastructure, not an App runtime permission. The App manifest must
remain non-privileged, non-host-networked, and free of broad
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
