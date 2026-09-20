# Local Home Assistant fixtures for HA Switchboard

These fixtures belong only to the disposable Home Assistant devcontainer named
`busy_cohen`, published at `http://127.0.0.1:7123/`. Do not run these commands
against `ha.possumden.net` or another Home Assistant instance. The scripts
check the container name and port before installing the package. They do not
change the Switchboard App options or rebuild the App.

From this worktree root, with `busy_cohen` and its local Core running:

```bash
python3 tools/local-fixtures/install.py
docker cp custom_components/ha_switchboard/. \
  busy_cohen:/mnt/supervisor/homeassistant/custom_components/ha_switchboard/
docker exec busy_cohen ha core restart --raw-json
docker exec -i busy_cohen docker exec -i homeassistant python3 - area \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - expose \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - exposure \
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
docker exec -i busy_cohen docker exec -i homeassistant python3 - profile \
  < tools/local-fixtures/local_api.py
docker exec -i busy_cohen docker exec -i homeassistant python3 - exercise \
  < tools/local-fixtures/local_api.py
```

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
owner's local auth record. It prints no token or auth material and creates no
credentials. It refuses to run unless exactly one existing owner long-lived
token is present. The script creates a separate **HA Switchboard Fixture**
pipeline and leaves the preferred Home Assistant pipeline unchanged. Its
conversation engine is `conversation.ha_switchboard`; `invoke` sends a
read-only temperature question through the real Assist pipeline.
`profile` reads the local integration's gateway address and token in Core
memory, prints only profile status/count, and never displays either value.
`invoke-control` sends “Turn on the Switchboard Fixture light” through that
pipeline. It changes only the disposable fixture light. Check its state with
`inspect` after invoking it.
`invoke-batch` and `invoke-batch-off` send explicit all-lights requests through
the same Assist pipeline. Both fixture lights must be exposed; the response
should report 2 of 2 verified devices. `inspect` also shows the integration's
diagnostic sensors when installed.

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
| Cover and lock | template entities + input booleans | open/close and lock/unlock | confirmation required by Switchboard |
| Temperature and motion | template sensor/binary sensor | readable states | no action capability |
| Evening script and Calm scene | native script/scene | triggered against fixture light only | scene exposed as routine; script held out pending Core fix |
| Fixture Lab area | native area registry | seven fixture entities assigned | area context for bounded group selection |

The helper entities are not exposed to Assist. Eleven primary entities are
exposed to the `conversation` assistant using the supported
`homeassistant/expose_entity` WebSocket command. The `exercise` command uses
native Core services with exact fixture entity IDs only; it restores mock
on/off states by the end. It does not prove Switchboard or Jev decided to
execute an action. There is no physical device, household action, or external
provider call in this test.

The native OpenRouter Decisions adapter is installed in this local App. The
read-only temperature question is answered from Core's current local snapshot,
without a provider call. The explicit two-light request has been verified
through the live Assist pipeline; its group decision still uses Jev. Fallback
models are disabled unless configured separately in App options with a privacy
mode that permits the route. App option changes and App rebuilds are outside
this fixture workflow.

The script remains installed and is exercised through Core services, but it
is intentionally not exposed to Switchboard. A local test found that its
`last_triggered` attribute is a Python `datetime`; a source fix now converts
that value to an ISO timestamp before building gateway request context.
Re-expose the script only after the updated integration is synced and the
local Assist test passes. The scene remains exposed for routine coverage.

The profile status can be `stale` during App restarts or profile reconciliation.
Do not interpret a capability count alone as permission to execute; check for
`status: active` and a successful end-to-end action after the App adapter is
ready.

`ha core logs --raw-json` shows the local Core log. After a fixture change,
run `install.py`, restart only Core, and check for new fixture errors. Warnings
that custom integrations have not been tested by Home Assistant are expected
in this development container.
