# HA Switchboard

HA Switchboard is a portable decision and control layer for
Home Assistant. It discovers the user's supported capabilities, keeps a
versioned profile current, uses Jev for bounded typed decisions, and hands
open-ended requests to a user-approved traditional LLM only when policy allows
it.

The product is deliberately an enhancement layer. Home Assistant remains the
source of truth and the execution authority. Existing Assist pipelines,
Wyoming/ESPHome satellites, STT/TTS engines, companion apps, dashboards,
HACS-installed projects, and conversation agents remain usable.

## Release boundary

The distributable product consists of:

1. `app/`: a Supervisor-managed Home Assistant App and the portable gateway
   image;
2. `custom_components/ha_switchboard/`: a thin integration installed into Home
   Assistant Core separately; and
3. `standalone/compose.yaml`: a Home Assistant Container deployment path using
   the same gateway image.

The release tree contains no operator-specific NixOS service wiring, personal
Home Assistant configuration, private network endpoints, secret material, or
provider credentials. The App does not copy the custom integration into a Home
Assistant configuration directory. The user installs and updates the two
artifacts independently.

The `.devcontainer/` directory is development-only. It uses the official Home
Assistant Apps devcontainer and Supervisor harness to test the App locally;
its Docker/AppArmor privileges are not product runtime permissions.

## Install in Home Assistant

The App and the Core integration are separate artifacts. The App hosts the
gateway; the integration connects Home Assistant Assist and Conversation to
that gateway and owns the Home Assistant-side execution boundary.

### Home Assistant OS / Supervisor App

1. In **Settings → Add-ons → Add-on store**, open the three-dot menu and add
   `https://github.com/grayslawson/ha-switchboard` as a repository.
2. Install **HA Switchboard**, start it, and open its Web UI if needed.
3. Configure Jev, privacy, and the optional downstream route in the App
   options. Empty provider options are supported for local contract testing.

The App repository is separate from HACS. It does not install files into
`custom_components`.

### HACS integration

Until the integration is accepted into HACS's default catalog, add
`grayslawson/ha-switchboard` as a HACS **Integration** custom repository (or
use the [HACS repository link](https://my.home-assistant.io/redirect/hacs_repository/?owner=grayslawson&repository=ha-switchboard&category=integration)).
Install **HA Switchboard**, restart Home Assistant, and add it from
**Settings → Devices & services → Add integration**. Enter the App gateway URL
and the optional gateway token from the App configuration.

HACS tracks the `custom_components/ha_switchboard/` directory and does not
install or manage the Supervisor App. Releases are published as full GitHub
Releases so HACS can offer versioned updates.

## Boundaries

- The companion integration owns Home Assistant credentials, entity IDs,
  registry/event access, action execution, and post-action verification.
- The gateway receives sanitized snapshots, opaque capability IDs, bounded
  conversation context, and minimized state only.
- Jev returns typed decisions. It does not generate prose, YAML, service JSON,
  credentials, or arbitrary tool plans.
- A traditional LLM receives at most one bounded handoff per turn and can
  return only bounded prose or an advisory typed capability proposal.
- All proposals re-enter policy, confirmation, allowlist, freshness,
  idempotency, execution, and post-state verification before a Home Assistant
  write.

## Local checks

```bash
python3 -m compileall app/ha_switchboard custom_components/ha_switchboard
pytest -q tests
python3 tools/check_release_boundary.py
```

The optional Supervisor/App acceptance loop is documented in
`docs/RELEASE.md` and uses the checked-in `.devcontainer/devcontainer.json`.

Repository synchronization and the public release boundary are documented in
`docs/PUBLIC_REPOSITORY.md`.

The repository is licensed under [Apache 2.0](LICENSE).
