from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.ha_switchboard.client import GatewayClient
from custom_components.ha_switchboard.const import PROFILE_EVENT_TYPES
from custom_components.ha_switchboard.coordinator import ProfileCoordinator
from custom_components.ha_switchboard.profile_adapter import HomeAssistantProfileAdapter


class _State:
    def __init__(self, entity_id: str, state: str = "off", **attributes):
        self.entity_id = entity_id
        self.state = state
        self.attributes = {"exposed": True, **attributes}


class _States:
    def __init__(self, values):
        self.values = {item.entity_id: item for item in values}

    def async_all(self):
        return list(self.values.values())

    def get(self, entity_id):
        return self.values.get(entity_id)


class _Services:
    def async_services(self):
        return {"light": {"turn_on": {}, "turn_off": {}, "toggle": {}}}


class _Hass:
    def __init__(self):
        self.states = _States([_State("light.kitchen")])
        self.services = _Services()
        self.data = {"assist_surfaces": [{"kind": "assist_pipeline", "name": "Fixture", "capabilities": ["conversation"]}]}


class _Gateway:
    def __init__(self):
        self.reconciles = 0
        self.scans = 0
        self.revision = "profile-one"

    async def health(self):
        return {"status": "ok"}

    async def app_status(self):
        return {"profile_refresh_minutes": 15}

    async def scan(self):
        self.scans += 1
        await asyncio.sleep(0)
        return {"status": "scan_requested"}

    async def reconcile(self, _snapshot):
        self.reconciles += 1
        await asyncio.sleep(0)
        return {"profile_revision": self.revision}

    async def status(self):
        return {"status": "active", "profile_revision": self.revision}

    async def invalidate(self, _event):
        return {"status": "stale", "profile_revision": self.revision}


def test_profile_adapter_exports_groups_assist_surfaces_and_opaque_members():
    async def run():
        hass = _Hass()
        group = _State("group.downstairs", friendly_name="Downstairs")
        group.attributes["entity_id"] = ["light.kitchen"]
        hass.states.values["group.downstairs"] = group
        build = await HomeAssistantProfileAdapter(hass, "fixture").async_build()
        organization = build.snapshot["organization"]
        assert organization["groups"][0]["name"] == "Downstairs"
        assert "light.kitchen" not in repr(organization["groups"])
        assert build.snapshot["assist_surfaces"] == [
            {"kind": "assist_pipeline", "name": "Fixture", "capabilities": ["conversation"]}
        ]

    asyncio.run(run())


def test_profile_adapter_keeps_routines_and_service_shape_warnings_bounded():
    async def run():
        hass = _Hass()
        routine = _State("script.goodnight", state="off", friendly_name="Good night")
        climate = _State("climate.downstairs", state="heat", hvac_modes="not-a-list", min_temp="bad")
        hass.states.values.update({routine.entity_id: routine, climate.entity_id: climate})

        class Services:
            def async_services(self):
                return {
                    "light": {
                        "turn_on": {"fields": {"brightness": {}}},
                        "turn_off": {"fields": []},
                        "toggle": {},
                    }
                }

        hass.services = Services()
        build = await HomeAssistantProfileAdapter(hass, "fixture").async_build()
        assert build.snapshot["routines"] == [
            {"adapter_ref": build.snapshot["routines"][0]["adapter_ref"], "name": "Good night", "kind": "script", "exposed": True}
        ]
        warnings = build.snapshot["warnings"]
        assert "service_shape_unrecognized:light:turn_off" in warnings
        assert "attribute_shape:climate:hvac_modes" in warnings
        assert "attribute_shape:climate:min_temp" in warnings

    asyncio.run(run())


def test_manual_scans_are_requested_once_and_coalesced():
    async def run():
        hass = _Hass()
        gateway = _Gateway()
        coordinator = ProfileCoordinator(
            hass, SimpleNamespace(data={}, entry_id="entry"), gateway, HomeAssistantProfileAdapter(hass, "fixture")
        )
        await coordinator.async_start()
        first, second = await asyncio.gather(coordinator.async_scan(), coordinator.async_scan())
        assert first["profile_revision"] == second["profile_revision"] == "profile-one"
        assert gateway.scans == 1
        assert coordinator.status()["scan_state"] == "completed"
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_events_arriving_during_reconcile_are_drained_by_one_flush():
    async def run():
        hass = _Hass()

        class RacingGateway(_Gateway):
            coordinator = None
            injected = False
            invalidations = []

            async def reconcile(self, snapshot):
                self.reconciles += 1
                if self.coordinator is not None and not self.injected:
                    self.injected = True
                    self.coordinator._on_event({"event_type": "area_registry_updated"})
                await asyncio.sleep(0)
                return {"profile_revision": self.revision}

            async def invalidate(self, event_type):
                self.invalidations.append(event_type)
                return {"profile_revision": self.revision}

        gateway = RacingGateway()
        coordinator = ProfileCoordinator(
            hass, SimpleNamespace(data={}, entry_id="entry"), gateway, HomeAssistantProfileAdapter(hass, "fixture")
        )
        gateway.coordinator = coordinator
        await coordinator.async_start()
        if coordinator._flush_task is not None:
            await coordinator._flush_task
        assert gateway.invalidations == ["area_registry_updated"]
        # The startup reconcile retries once for the generation race, then
        # the coalesced event flush performs the replacement reconcile.
        assert gateway.reconciles == 3
        assert coordinator.status()["pending_events"] == []
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_lifecycle_event_contract_includes_all_profile_surfaces():
    assert {
        "exposure_updated", "service_schema_updated", "assist_surface_updated",
        "routine_updated", "reconnect", "restart",
    } <= set(PROFILE_EVENT_TYPES)


def test_gateway_client_scan_uses_authenticated_profile_endpoint():
    class Response:
        status = 202

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def json(self, **_kwargs):
            return {"status": "scan_requested"}

    class Session:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return Response()

    async def run():
        session = Session()
        client = GatewayClient("http://gateway", "secret", session=session)
        assert await client.scan() == {"status": "scan_requested"}
        method, url, kwargs = session.calls[0]
        assert method == "POST"
        assert url == "http://gateway/v1/profile/scan"
        assert kwargs["headers"]["Authorization"] == "Bearer secret"

    asyncio.run(run())
