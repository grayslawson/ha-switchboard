# Local Home Assistant fixtures for HA Switchboard

These fixtures belong only to the disposable Home Assistant devcontainer named
`busy_cohen`, published at `http://127.0.0.1:7123/`. Do not run these commands
against `ha.possumden.net` or another Home Assistant instance. The scripts
check the container name and port before installing the package. They do not
change the Switchboard App options or rebuild the App.

From this worktree root, with `busy_cohen` and its local Core running:

```bash
python3 tools/local-fixtures/install.py
python3 tools/local-fixtures/local_api.py startup
python3 tools/local-fixtures/local_api.py restart-cycle
docker cp custom_components/ha_switchboard/. \
  busy_cohen:/mnt/supervisor/homeassistant/custom_components/ha_switchboard/
docker exec busy_cohen ha core restart --raw-json
docker exec -i busy_cohen docker exec -i homeassistant python3 - area \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - metadata \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - expose \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - exposure \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - coverage \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - unsupported \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - configure \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - inspect \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - invoke \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - invoke-control \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - invoke-batch \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - invoke-batch-off \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - native \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - follow-up \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - profile \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - scan \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - lifecycle \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - verify \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - exercise \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - failures \
  < tools/local-fixtures/local_api.py
```

`startup` and `restart-cycle` are host-side, read-only checks. Run them with
the direct `python3` form shown above; they verify Docker's disposable
Supervisor container and then invoke the Core-side lifecycle evidence safely.
The other commands in the block are Core-side commands and are fed to Core's
Python process through standard input.

`install.py` copies `switchboard.yaml` into the **local** Core config, appends
one marked package include to its `configuration.yaml`, and runs `ha core
check`. Re-running it refreshes the YAML without duplicating the include. It
refuses to alter a configuration that already has an unmarked `homeassistant:`
section. The integration copy is needed when this local Core predates the
worktree's current `conversation.py` and unique ID. An existing HA Switchboard
integration config entry and a running local App are prerequisites; add the
integration in the local UI at Settings > Devices & services if absent. Do not
put a gateway token in fixture YAML or shell history.

`local_api.py` uses Core's REST and WebSocket APIs. Inside this disposable
local Core it mints a five-minute access token in memory from the existing
owner account's local auth record. It prints no token or auth material and
creates no credentials. It refuses to run unless exactly one existing owner
long-lived token is present. Host-side and Core-side harness output is
intentionally sanitized for issue/release evidence: it reports bounded counts,
states, event types, and status codes rather than raw entity IDs, raw
utterances, gateway tokens, or provider bodies. The script creates a separate
**HA Switchboard Fixture**
pipeline and leaves the preferred Home Assistant pipeline unchanged. Its
conversation engine is `conversation.ha_switchboard`; `invoke` sends a
read-only temperature question through the real Assist pipeline.
`profile` reads the local integration's gateway address and token in Core
memory, prints only profile status/count, and never displays either value.
`scan` performs one bounded, authenticated `POST /v1/profile/scan` against the
configured local gateway, then polls profile status for a settled active profile
for at most 12 seconds. It reports only HTTP status, freshness, revision
presence, counts, and pending-state counts. The endpoint is a
request/invalidating boundary: the `202` proves acceptance; only the subsequent
active/no-pending status is reported as settled.
`lifecycle` is a read-only startup/restart snapshot. Run it after a Core or App
restart to verify the existing config entry, local fixture count, conversation
agent presence, and redacted gateway profile state. It does not restart,
reload, reinstall, or mutate the local volume.
`restart-cycle` is a host-side recovery check and is read-only by default. It
verifies that Docker is pointing at the disposable `busy_cohen` Supervisor
volume, records a secret-free lifecycle snapshot, and exits without restarting
anything:

```bash
python3 tools/local-fixtures/local_api.py restart-cycle
```

Only when the disposable local environment is intentionally being tested may a
developer opt in to the bounded App-then-Core restart cycle:

```bash
python3 tools/local-fixtures/local_api.py restart-cycle --allow-restart
```

The opt-in command refuses an unknown container, a non-local port, a missing
Supervisor volume, missing existing App options, or a missing Switchboard
config entry/conversation agent. It compares the pre- and post-restart options,
config entry, fixture count, conversation agent, and active profile without
printing credentials. It never resets, recreates, uninstalls, or deletes the
Supervisor/Core volume. Do not use `--allow-restart` against a real Home
Assistant host. A command timeout or failed readiness check is a failure; it is
not a reason to retry in a loop.
`verify` is the safe installation/upgrade evidence command: it confirms that
exactly one `ha_switchboard` config entry exists, reports its source/title/
version, and reduces the gateway URL to host/port plus a boolean indicating
that a token is present. It never prints the URL path, token, or other config
entry secrets. Run it after installing or upgrading the integration and again
after a local Core restart.
`area` and `metadata` are repeat-safe: they create or reuse the fixture area,
two Core labels, and the bounded native light group without deleting or
rewriting unrelated registry entries. They derive assignment targets from the
existing entity registry, report the assigned count, and skip only the native
Core-only script and scene surfaces. Missing registered fixture entities still
fail the helper. `coverage` emits a JSON report for each
published operation-matrix row and exits non-zero when a required entity is
missing or not exposed to Assist. `failures` emits stable, secret-free
provider and parameter failure cases for deterministic fallback tests; it does
not call a provider or mutate Core.
`invoke-control` sends “Turn on the Switchboard Fixture light” through that
pipeline. It changes only the disposable fixture light. Check its state with
`inspect` after invoking it.
`invoke-batch` and `invoke-batch-off` send explicit all-lights requests through
the same Assist pipeline. Both fixture lights must be exposed; the response
should report 2 of 2 verified devices. `inspect` also shows the integration's
diagnostic sensors when installed.
`native` selects the existing **Switchboard** pipeline with
`prefer_local_intents` enabled and sends one routine light request through
Home Assistant's native intent path. It records only event types, speech
presence, a before/after fixture-state assertion, and the bounded Jev
diagnostic-count delta. The fixture light is restored to its original state
before the command returns. A zero Jev diagnostic delta proves that native
success bypassed the gateway for that request; the command fails closed if the
pipeline is missing, the action is not verified, or restoration fails.
`unsupported` verifies that the native script and scene fixtures remain
available in Core but are not exposed to Switchboard's Assist capability set.
`follow-up` exercises the bounded confirmation/cancellation/replay path in the
fixture conversation. By default it reports different-user and TTL-expiry
checks as unavailable. To run the additional live gates, supply an already
issued second Home Assistant user's short-lived access token only in memory:

```bash
: "${HA_SWITCHBOARD_FOLLOW_UP_SECOND_USER_ACCESS_TOKEN:?set this through your local secret mechanism}"
export HA_SWITCHBOARD_RUN_FOLLOW_UP=1
python3 -m pytest -q tests/test_e2e_harness.py -k live_follow_up_fixture
```

Set `HA_SWITCHBOARD_RUN_FOLLOW_UP_NATURAL_EXPIRY=1` as well to wait for the
Core continuation TTL. The wait is bounded; it is not a clock override. The
token is forwarded by environment name only, never printed or persisted, and
the probe does not create or modify Home Assistant users. The deterministic
source tests cover these boundaries without mutating auth. Do not enable the
second-user or natural-expiry options until the local fixture's state and the
test window are explicitly approved.

In the UI, go to **Settings > Voice assistants > HA Switchboard Fixture** and
check **Conversation agent: HA Switchboard**. To add one manually, use
**Settings > Voice assistants > Add assistant**, name it, and select
**HA Switchboard** under **Conversation agent**. The agent itself comes from
the integration at **Settings > Devices & services > HA Switchboard**.

## Coverage

| Fixture | Native backing | Verified local behavior | Switchboard boundary |
| --- | --- | --- | --- |
| Two lights | template lights + input booleans/number | on/off, 40% brightness | routine and bounded group operations |
| Switch and fan | template entities + input booleans | on/off | routine operations |
| Thermostat | generic thermostat + template heater + sensor | target 21°C; heat/off modes | routine operations |
| Player | universal media player + input select/number | idle, play, pause, off, volume 0.25 | routine operations |
| Cover, garage, and lock | template entities + input booleans | open/close and lock/unlock | confirmation required by Switchboard |
| Temperature and motion | template sensor/binary sensor | readable states | no action capability |
| Evening script and Calm scene | native script/scene | triggered against fixture light only | Native Core only; non-Switchboard fixture surfaces |
| Fixture Lab area, labels, and group | native registries + YAML group | primary entities assigned to area and labels; two-light group | area/label/group context for bounded selection |

The helper entities are not exposed to Assist. Eleven executable/read-only
fixture entities are exposed to the `conversation` assistant using the supported
`homeassistant/expose_entity` WebSocket command. The `exercise` command uses
native Core services with exact fixture entity IDs only; it restores mock
on/off states by the end. It does not prove Switchboard or Jev decided to
execute an action. There is no physical device, household action, or external
provider call in this test.
The `coverage` report contains exactly 24 executable Switchboard operation-matrix rows;
native script and scene surfaces are deliberately not rows and cannot create
coverage failures.

The native OpenRouter Decisions adapter is installed in this local App. The
read-only temperature question is answered from Core's current local snapshot,
without a provider call. The explicit two-light request has been verified
through the live Assist pipeline; its group decision still uses Jev. Fallback
models are disabled unless configured separately in App options with a privacy
mode that permits the route. App option changes and App rebuilds are outside
this fixture workflow.

The script and scene remain installed for native Core-service fixture tests.
They are not exposed to Assist, are not Switchboard capabilities, and are
excluded from the operation-matrix coverage report. The script's
`last_triggered` attribute is converted to an ISO timestamp before gateway
request context is built.

The profile status can be `stale` during App restarts or profile reconciliation.
Do not interpret a capability count alone as permission to execute; check for
`status: active` and a successful end-to-end action after the App adapter is
ready.

The manual scan acceptance path is intentionally split: source tests cover
authentication, serialized/coalesced Core scans, progress, bounded failure,
and stale-write refusal; `scan` proves the live gateway request was accepted;
`lifecycle` proves the currently running Core/App state after an externally
performed restart. Neither command prints gateway/provider credentials or
claims completion from an HTTP `202` alone.

`ha core logs --raw-json` shows the local Core log. After a fixture change,
run `install.py`, restart only Core, and check for new fixture errors. Warnings
that custom integrations have not been tested by Home Assistant are expected
in this development container.

The installer has a second safety gate: Docker must report the exact running
container name `busy_cohen` with host port 7123 mapped to Core port 80. It
refuses production hosts, other containers, and missing port mappings. It only
copies the fixture package and appends its marked include; it never resets,
recreates, or removes the existing Core volume.
