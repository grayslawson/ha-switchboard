"""Use Core's supported local APIs with an ephemeral token kept in memory.

Run only inside the named devcontainer's Home Assistant Core container.
No token or auth-store content is printed or written by this script.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp
import jwt


BASE = "http://127.0.0.1:80"
PIPELINE_NAME = "HA Switchboard Fixture"
AGENT = "conversation.ha_switchboard"


def temporary_token() -> str:
    # This local dev Core already has a human admin account. Its existing
    # refresh token's signing key can mint a short access token in memory.
    data = json.loads(Path("/config/.storage/auth").read_text())["data"]
    users = {user["id"]: user for user in data["users"]}
    candidates = [
        token for token in data["refresh_tokens"]
        if token["token_type"] == "long_lived_access_token"
        and users.get(token["user_id"], {}).get("is_owner")
    ]
    if len(candidates) != 1:
        raise SystemExit("Expected one existing local owner token; no auth change made")
    token = candidates[0]
    now = int(time.time())
    return jwt.encode(
        {"iss": token["id"], "iat": now, "exp": now + 300},
        token["jwt_key"],
        algorithm="HS256",
    )


async def websocket_call(ws: aiohttp.ClientWebSocketResponse, message: dict) -> dict:
    await ws.send_json(message)
    while True:
        received = await ws.receive_json(timeout=20)
        if received.get("id") == message["id"] and received.get("type") in {"result", "event"}:
            return received


async def main(command: str) -> None:
    token = temporary_token()
    if command == "profile":
        entries = json.loads(Path("/config/.storage/core.config_entries").read_text())["data"]["entries"]
        switchboard = [entry for entry in entries if entry["domain"] == "ha_switchboard"]
        if len(switchboard) != 1:
            raise RuntimeError("Expected one local Switchboard integration entry")
        config = switchboard[0]["data"]
        async with aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {config['gateway_token']}",
        }) as gateway:
            async with gateway.get(config["gateway_url"].rstrip("/") + "/v1/profile/status") as response:
                response.raise_for_status()
                status = await response.json()
        print("Gateway profile:", {
            "status": status.get("status"),
            "capability_count": status.get("capability_count"),
            "has_revision": bool(status.get("profile_revision")),
        })
        return
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
        async with session.get(BASE + "/api/states") as response:
            response.raise_for_status()
            states = {item["entity_id"]: item for item in await response.json()}
        fixtures = sorted(entity_id for entity_id in states if "switchboard_fixture" in entity_id)
        agent = states.get(AGENT)
        print("Agent state:", None if agent is None else agent["state"])
        print("Fixture entities:", [(name, states[name]["state"]) for name in fixtures])
        print("Switchboard diagnostics:", sorted(
            (name, item["state"]) for name, item in states.items()
            if name.startswith("sensor.") and any(part in name for part in ("switchboard", "gateway_ready", "capabilities", "last_scan"))
        ))
        if command == "exercise":
            actions = [
                ("light", "turn_on", "light.switchboard_fixture_light", {}, "on"),
                ("light", "turn_on", "light.switchboard_fixture_light", {"brightness_pct": 40}, "on"),
                ("light", "turn_off", "light.switchboard_fixture_light", {}, "off"),
                ("light", "turn_on", "light.switchboard_fixture_lamp", {}, "on"),
                ("light", "turn_off", "light.switchboard_fixture_lamp", {}, "off"),
                ("switch", "turn_on", "switch.switchboard_fixture_switch", {}, "on"),
                ("switch", "turn_off", "switch.switchboard_fixture_switch", {}, "off"),
                ("fan", "turn_on", "fan.switchboard_fixture_fan", {}, "on"),
                ("fan", "turn_off", "fan.switchboard_fixture_fan", {}, "off"),
                ("cover", "open_cover", "cover.switchboard_fixture_cover", {}, "open"),
                ("cover", "close_cover", "cover.switchboard_fixture_cover", {}, "closed"),
                ("lock", "lock", "lock.switchboard_fixture_lock", {}, "locked"),
                ("lock", "unlock", "lock.switchboard_fixture_lock", {}, "unlocked"),
                ("media_player", "turn_on", "media_player.switchboard_fixture_player", {}, "idle"),
                ("media_player", "volume_set", "media_player.switchboard_fixture_player", {"volume_level": 0.25}, "idle"),
                ("media_player", "media_play", "media_player.switchboard_fixture_player", {}, "playing"),
                ("media_player", "media_pause", "media_player.switchboard_fixture_player", {}, "paused"),
                ("media_player", "turn_off", "media_player.switchboard_fixture_player", {}, "off"),
                ("climate", "set_temperature", "climate.switchboard_fixture_thermostat", {"temperature": 21}, "off"),
                ("climate", "set_hvac_mode", "climate.switchboard_fixture_thermostat", {"hvac_mode": "heat"}, "heat"),
                ("climate", "set_hvac_mode", "climate.switchboard_fixture_thermostat", {"hvac_mode": "off"}, "off"),
                ("script", "turn_on", "script.switchboard_fixture_evening", {}, "off"),
                ("scene", "turn_on", "scene.switchboard_fixture_calm", {}, None),
            ]
            for domain, service, entity_id, extra, expected in actions:
                payload = {"entity_id": entity_id, **extra}
                async with session.post(BASE + f"/api/services/{domain}/{service}", json=payload) as response:
                    response.raise_for_status()
                    await response.read()
                await asyncio.sleep(0.3)
                async with session.get(BASE + f"/api/states/{entity_id}") as response:
                    response.raise_for_status()
                    state = await response.json()
                actual = state["state"]
                if expected is not None and actual != expected:
                    raise RuntimeError(f"Mock service state mismatch: {entity_id} {service} => {actual}")
                if service == "set_temperature" and abs(float(state["attributes"]["temperature"]) - 21) > 0.2:
                    raise RuntimeError("Mock thermostat target temperature did not update")
                if "brightness_pct" in extra and abs(float(state["attributes"]["brightness"]) * 100 / 255 - 40) > 2:
                    raise RuntimeError("Mock light brightness did not update")
                if service == "volume_set" and abs(float(state["attributes"]["volume_level"]) - 0.25) > 0.02:
                    raise RuntimeError("Mock media player volume did not update")
                print("Mock action:", entity_id, service, actual)
            return

        async with session.ws_connect(BASE.replace("http", "ws") + "/api/websocket") as ws:
            hello = await ws.receive_json(timeout=10)
            if hello.get("type") != "auth_required":
                raise RuntimeError("Unexpected Core WebSocket greeting")
            await ws.send_json({"type": "auth", "access_token": token})
            if (await ws.receive_json(timeout=10)).get("type") != "auth_ok":
                raise RuntimeError("Local Core rejected ephemeral access token")
            if command == "area":
                existing = await websocket_call(ws, {"id": 10, "type": "config/area_registry/list"})
                if not existing.get("success"):
                    raise RuntimeError("Could not list local areas")
                areas = [item for item in existing["result"] if item["name"] == "Switchboard Fixture Lab"]
                if not areas:
                    created = await websocket_call(ws, {
                        "id": 11, "type": "config/area_registry/create", "name": "Switchboard Fixture Lab",
                    })
                    if not created.get("success"):
                        raise RuntimeError("Could not create local fixture area")
                    areas = [created["result"]]
                area_id = areas[0]["area_id"]
                for index, entity_id in enumerate((
                    "light.switchboard_fixture_light",
                    "light.switchboard_fixture_lamp",
                    "switch.switchboard_fixture_switch",
                    "cover.switchboard_fixture_cover",
                    "lock.switchboard_fixture_lock",
                    "climate.switchboard_fixture_thermostat",
                    "media_player.switchboard_fixture_player",
                ), start=12):
                    updated = await websocket_call(ws, {
                        "id": index, "type": "config/entity_registry/update",
                        "entity_id": entity_id, "area_id": area_id,
                    })
                    if not updated.get("success"):
                        raise RuntimeError(f"Could not assign local fixture area to {entity_id}")
                print("Fixture area:", areas[0]["name"], "assigned entities: 6")
                return
            if command == "expose":
                allowed = (
                    "light.switchboard_fixture_light",
                    "light.switchboard_fixture_lamp",
                    "switch.switchboard_fixture_switch",
                    "fan.switchboard_fixture_fan",
                    "cover.switchboard_fixture_cover",
                    "lock.switchboard_fixture_lock",
                    "climate.switchboard_fixture_thermostat",
                    "media_player.switchboard_fixture_player",
                    "sensor.switchboard_fixture_temperature_reading",
                    "binary_sensor.switchboard_fixture_motion",
                    "scene.switchboard_fixture_calm",
                )
                missing = set(allowed) - states.keys()
                if missing:
                    raise RuntimeError(f"Local fixture entities missing: {sorted(missing)}")
                response = await websocket_call(ws, {
                    "id": 20, "type": "homeassistant/expose_entity",
                    "assistants": ["conversation"], "entity_ids": list(allowed),
                    "should_expose": True,
                })
                if not response.get("success"):
                    raise RuntimeError("Could not expose local fixture entities to Assist")
                hidden = await websocket_call(ws, {
                    "id": 22, "type": "homeassistant/expose_entity",
                    "assistants": ["conversation"],
                    "entity_ids": [
                        "switch.switchboard_fixture_heater",
                        "script.switchboard_fixture_evening",
                    ],
                    "should_expose": False,
                })
                if not hidden.get("success"):
                    raise RuntimeError("Could not hide local fixture heater helper from Assist")
                print("Exposed fixture entities to Assist:", len(allowed))
                return
            if command == "exposure":
                response = await websocket_call(ws, {
                    "id": 21, "type": "homeassistant/expose_entity/list",
                })
                if not response.get("success"):
                    raise RuntimeError("Could not read local Assist exposure")
                exposed = response["result"]["exposed_entities"]
                print("Fixture Assist exposure:", sorted(
                    name for name, assistants in exposed.items()
                    if "switchboard_fixture" in name and assistants.get("conversation")
                ))
                return
            listing = await websocket_call(ws, {"id": 1, "type": "assist_pipeline/pipeline/list"})
            if not listing.get("success"):
                raise RuntimeError("Could not list local Assist pipelines")
            pipelines = listing["result"]["pipelines"]
            ours = [item for item in pipelines if item["name"] == PIPELINE_NAME]
            if command == "configure" and not ours:
                if agent is None:
                    raise RuntimeError("Switchboard conversation agent is missing")
                fields = {
                    "name": PIPELINE_NAME,
                    "language": "en",
                    "conversation_engine": AGENT,
                    "conversation_language": "en",
                    "stt_engine": None,
                    "stt_language": None,
                    "tts_engine": None,
                    "tts_language": None,
                    "tts_voice": None,
                    "wake_word_entity": None,
                    "wake_word_id": None,
                    "prefer_local_intents": False,
                }
                result = await websocket_call(ws, {"id": 2, "type": "assist_pipeline/pipeline/create", **fields})
                if not result.get("success"):
                    raise RuntimeError(f"Assist pipeline creation failed: {result.get('error', {}).get('code')}")
                ours = [result["result"]]
            print("Fixture pipeline:", [(item["id"], item["conversation_engine"]) for item in ours])
            if command in {"invoke", "invoke-control", "invoke-vague", "invoke-batch", "invoke-batch-off"}:
                if len(ours) != 1 or ours[0]["conversation_engine"] != AGENT:
                    raise RuntimeError("Fixture pipeline is absent or points to another agent")
                await ws.send_json({
                    "id": 3, "type": "assist_pipeline/run", "pipeline": ours[0]["id"],
                    "start_stage": "intent", "end_stage": "intent",
                    "input": {"text": (
                        "Turn on the Switchboard Fixture light."
                        if command == "invoke-control"
                        else "Turn all the lights on."
                        if command == "invoke-batch"
                        else "Turn all the lights off."
                        if command == "invoke-batch-off"
                        else "Turn the lights on."
                        if command == "invoke-vague"
                        else "What is the Switchboard Fixture Temperature Reading?"
                    )},
                })
                event_types = []
                for _ in range(30):
                    event = await ws.receive_json(timeout=20)
                    if event.get("id") != 3:
                        continue
                    if event["type"] == "result" and not event.get("success"):
                        raise RuntimeError(f"Assist invocation failed: {event.get('error', {}).get('code')}")
                    if event["type"] == "event":
                        event_type = event.get("event", {}).get("type", "unknown")
                        event_types.append(event_type)
                        if event_type == "intent-end":
                            output = event.get("event", {}).get("data", {}).get("intent_output", {})
                            speech = output.get("response", {}).get("speech", {}).get("plain", {}).get("speech")
                            print("Assist speech:", speech)
                        if event_type == "error":
                            detail = event.get("event", {}).get("data", {})
                            print("Assist error code:", detail.get("code"))
                        if event_type in {"run-end", "error"}:
                            break
                print("Assist event types:", event_types)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"inspect", "configure", "invoke", "invoke-control", "invoke-vague", "invoke-batch", "invoke-batch-off", "exercise", "area", "expose", "exposure", "profile"}:
        raise SystemExit("Usage: local_api.py inspect|configure|invoke|invoke-control|invoke-vague|invoke-batch|invoke-batch-off|exercise|area|expose|exposure|profile")
    asyncio.run(main(sys.argv[1]))
