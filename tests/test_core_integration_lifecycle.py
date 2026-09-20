from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.ha_switchboard.capabilities import (
    OPERATION_SPECS,
    CapabilityMap,
    CapabilityTarget,
    OperationSpec,
    operation_spec,
)
from custom_components.ha_switchboard.client import GatewayClient, GatewayClientError
from custom_components.ha_switchboard.config_flow import (
    ConfigFlow,
    DiscoveryValidationError,
    validate_discovery_payload,
    validate_manual_input,
)
from custom_components.ha_switchboard.coordinator import ProfileCoordinator
from custom_components.ha_switchboard.execution import CoreHomeAssistantExecutor, ExecutionBoundary
from custom_components.ha_switchboard.opaque import adapter_ref, capability_id
from custom_components.ha_switchboard.profile_adapter import HomeAssistantProfileAdapter
from custom_components.ha_switchboard import ConfigEntryNotReady, async_setup_entry, async_unload_entry
from custom_components.ha_switchboard import async_migrate_entry
from custom_components.ha_switchboard.const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, DOMAIN


@pytest.fixture(autouse=True)
def fake_core_helpers_when_installed(monkeypatch):
    """Keep the fake Core fixture independent of installed HA registries."""

    try:
        from homeassistant.helpers import area_registry, device_registry, entity_registry, event, floor_registry, label_registry
    except ImportError:
        return
    for registry in (area_registry, device_registry, entity_registry, floor_registry, label_registry):
        monkeypatch.setattr(registry, "async_get", lambda _hass: SimpleNamespace())
    monkeypatch.setattr(
        HomeAssistantProfileAdapter,
        "_is_exposed",
        lambda _self, _entity_id, state: bool(state.attributes.get("exposed", False)),
    )
    monkeypatch.setattr(event, "async_track_time_interval", lambda *_args: lambda: None)


class FakeState:
    def __init__(self, entity_id: str, state: str, **attributes):
        self.entity_id = entity_id
        self.state = state
        self.attributes = {"exposed": True, **attributes}


class FakeStates:
    def __init__(self, states):
        self._states = {state.entity_id: state for state in states}

    def async_all(self):
        return list(self._states.values())

    def get(self, entity_id):
        return self._states.get(entity_id)


class FakeServices:
    def __init__(self, states: FakeStates):
        self.states = states
        self.calls = []

    async def async_call(self, domain, service, data, *, blocking):
        self.calls.append((domain, service, data, blocking))
        state = self.states.get(data["entity_id"])
        if service == "turn_on":
            state.state = "on"
        elif service == "turn_off":
            state.state = "off"


class FakeHass:
    def __init__(self):
        self.states = FakeStates([FakeState("light.living_room", "off")])
        self.services = FakeServices(self.states)


class OperationServices:
    def __init__(self, states: FakeStates):
        self.states = states
        self.calls = []

    async def async_call(self, domain, service, data, *, blocking, **_kwargs):
        self.calls.append((domain, service, data, blocking))
        state = self.states.get(data["entity_id"])
        if service == "turn_on":
            state.state = "on"
            if "brightness_pct" in data:
                state.attributes["brightness_pct"] = data["brightness_pct"]
        elif service == "turn_off":
            state.state = "off"
        elif service == "toggle":
            state.state = "off" if state.state == "on" else "on"
        elif service == "media_play":
            state.state = "playing"
        elif service == "media_pause":
            state.state = "paused"
        elif service == "media_stop":
            state.state = "idle"
        elif service == "volume_set":
            state.attributes["volume_level"] = data["volume_level"]
        elif service == "set_temperature":
            state.attributes["temperature"] = data["temperature"]
        elif service == "set_hvac_mode":
            state.attributes["hvac_mode"] = data["hvac_mode"]
        elif service == "lock":
            state.state = "locked"
        elif service == "unlock":
            state.state = "unlocked"
        elif service == "open_cover":
            state.state = "open"
        elif service == "close_cover":
            state.state = "closed"


class OperationHass:
    def __init__(self, domain: str, operation: str):
        entity_id = f"{domain}.fixture"
        state, attributes = self._initial_state(domain, operation)
        self.states = FakeStates([FakeState(entity_id, state, **attributes)])
        self.services = OperationServices(self.states)

    @staticmethod
    def _initial_state(domain: str, operation: str):
        if operation in {"turn_on", "set_brightness", "toggle"}:
            return "off", {}
        if operation == "turn_off":
            return "on", {}
        if operation == "play":
            return "paused", {}
        if operation == "pause":
            return "playing", {}
        if operation == "stop":
            return "playing", {}
        if operation == "set_volume":
            return "paused", {"volume_level": 0.2}
        if operation == "set_temperature":
            return "heat", {"temperature": 18}
        if operation == "set_hvac_mode":
            return "off", {"hvac_mode": "off"}
        if operation == "lock":
            return "unlocked", {}
        if operation == "unlock":
            return "locked", {}
        if operation == "open_cover":
            return "closed", {}
        if operation == "close_cover":
            return "open", {}
        raise AssertionError(f"unmodeled operation: {domain}.{operation}")


class FakeBus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, event_type, callback):
        listener = (event_type, callback)
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)


class FakeEntry:
    entry_id = "entry-one"
    unique_id = "supervisor-discovery-uuid"
    runtime_data = None

    def __init__(self):
        self.data = {CONF_GATEWAY_URL: "http://old-gateway:8099", CONF_GATEWAY_TOKEN: "old-token"}
        self.listeners = []
        self.unload_callbacks = []

    def add_update_listener(self, callback):
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback)

    def async_on_unload(self, callback):
        self.unload_callbacks.append(callback)

    async def update(self, hass, data):
        self.data = data
        for listener in list(self.listeners):
            await listener(hass, self)

    def unload(self):
        for callback in self.unload_callbacks:
            callback()
        self.unload_callbacks.clear()


class FakeConfigEntries:
    def __init__(self, hass):
        self.hass = hass
        self.forward_error = None
        self.reloads = []

    async def async_forward_entry_setups(self, _entry, _platforms):
        if self.forward_error is not None:
            raise self.forward_error

    async def async_unload_platforms(self, _entry, _platforms):
        return True

    async def async_reload(self, entry_id):
        self.reloads.append(entry_id)
        entry = self.hass.entry
        assert await async_unload_entry(self.hass, entry)
        entry.unload()
        return await async_setup_entry(self.hass, entry)


class FakeLifecycleHass(FakeHass):
    def __init__(self):
        super().__init__()
        self.bus = FakeBus()
        self.data = {}
        self.entry = FakeEntry()
        self.config_entries = FakeConfigEntries(self)


class FakeGateway:
    def __init__(self):
        self.reconciles = []
        self.invalidations = []
        self.revision = "profile-one"
        self.status_payload = None
        self.app_status_payload = {"profile_refresh_minutes": 15}

    async def health(self):
        return {"status": "ok"}

    async def reconcile(self, snapshot):
        self.reconciles.append(snapshot)
        return {"profile_revision": self.revision}

    async def invalidate(self, event_type):
        self.invalidations.append(event_type)
        return {"profile_revision": self.revision, "status": "stale"}

    async def status(self):
        return self.status_payload or {"profile_revision": self.revision, "status": "active", "monitor": {"pending_sections": []}}

    async def app_status(self):
        return self.app_status_payload


def test_recovery_watch_scans_after_app_restart_or_manual_request(monkeypatch):
    async def run():
        hass = FakeLifecycleHass()
        gateway = FakeGateway()
        monkeypatch.setattr(GatewayClient, "from_hass", lambda *_args: gateway)

        assert await async_setup_entry(hass, hass.entry)
        coordinator = hass.entry.runtime_data.coordinator
        assert len(gateway.reconciles) == 1

        gateway.status_payload = {
            "profile_revision": gateway.revision,
            "status": "stale",
            "monitor": {"pending_sections": ["entities"]},
        }
        gateway.app_status_payload = {"profile_refresh_minutes": 7}
        await coordinator._recovery_tick()
        assert len(gateway.reconciles) == 2
        assert coordinator.refresh_minutes == 7

        gateway.status_payload = {
            "profile_revision": gateway.revision,
            "status": "active",
            "monitor": {"pending_sections": []},
        }
        await coordinator._recovery_tick()
        assert len(gateway.reconciles) == 2
        assert await async_unload_entry(hass, hass.entry)

    asyncio.run(run())


def test_legacy_core_entry_migration_preserves_state_and_normalizes_keys():
    async def run():
        updates = []

        def update_entry(entry, **kwargs):
            updates.append(kwargs)
            entry.data = kwargs["data"]

        hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
        entry = SimpleNamespace(data={"url": "http://gateway:8099", "token": "rotated"}, version=0)
        assert await async_migrate_entry(hass, entry)
        assert entry.data == {CONF_GATEWAY_URL: "http://gateway:8099", CONF_GATEWAY_TOKEN: "rotated"}
        assert entry.version == 1
        assert updates == [{"data": entry.data, "version": 1}]

        canonical = SimpleNamespace(
            data={
                CONF_GATEWAY_URL: "http://current-gateway:8099",
                CONF_GATEWAY_TOKEN: "current-token",
                "url": "http://stale-gateway:8099",
                "token": "stale-token",
            },
            version=0,
        )
        assert await async_migrate_entry(hass, canonical)
        assert canonical.data == {
            CONF_GATEWAY_URL: "http://current-gateway:8099",
            CONF_GATEWAY_TOKEN: "current-token",
        }
        assert canonical.version == 1

    asyncio.run(run())


def test_legacy_entry_upgrade_restarts_with_an_active_profile(monkeypatch):
    async def run():
        hass = FakeLifecycleHass()
        hass.entry.data = {"url": "http://legacy-gateway:8099", "token": "legacy-token"}
        gateway = FakeGateway()
        monkeypatch.setattr(GatewayClient, "from_hass", lambda *_args: gateway)

        assert await async_setup_entry(hass, hass.entry)
        assert hass.entry.data == {
            CONF_GATEWAY_URL: "http://legacy-gateway:8099",
            CONF_GATEWAY_TOKEN: "legacy-token",
        }
        assert hass.entry.runtime_data.coordinator.profile_revision == gateway.revision
        assert hass.entry.runtime_data.coordinator.writes_allowed() is True
        assert await async_unload_entry(hass, hass.entry)
        hass.entry.unload()

    asyncio.run(run())


def test_core_entry_restart_recreates_client_and_reconciles_active_profile(monkeypatch):
    async def run():
        hass = FakeLifecycleHass()
        clients = []

        def client_from_hass(_hass, url, token):
            gateway = FakeGateway()
            gateway.base_url = url
            gateway.gateway_token = token
            clients.append(gateway)
            return gateway

        monkeypatch.setattr(GatewayClient, "from_hass", client_from_hass)
        original_data = dict(hass.entry.data)

        assert await async_setup_entry(hass, hass.entry)
        old_runtime = hass.entry.runtime_data
        old_coordinator = old_runtime.coordinator
        assert old_coordinator.writes_allowed() is True

        assert await async_unload_entry(hass, hass.entry)
        hass.entry.unload()
        assert old_coordinator._started is False
        assert hass.bus.listeners == []

        assert await async_setup_entry(hass, hass.entry)
        new_runtime = hass.entry.runtime_data
        assert new_runtime is not old_runtime
        assert new_runtime.client is clients[1]
        assert len(clients[0].reconciles) == len(clients[1].reconciles) == 1
        assert new_runtime.coordinator.profile_revision == clients[1].revision
        assert new_runtime.coordinator.writes_allowed() is True
        assert hass.entry.data == original_data
        assert hass.bus.listeners

        assert await async_unload_entry(hass, hass.entry)
        hass.entry.unload()

    asyncio.run(run())


def test_token_mismatch_fails_closed_then_rotated_token_recovers(monkeypatch):
    async def run():
        hass = FakeLifecycleHass()
        clients = []

        class TokenCheckingGateway(FakeGateway):
            async def health(self):
                if self.gateway_token != "current-token":
                    raise GatewayClientError("gateway rejected the token")
                return await super().health()

        def client_from_hass(_hass, url, token):
            gateway = TokenCheckingGateway()
            gateway.base_url = url
            gateway.gateway_token = token
            clients.append(gateway)
            return gateway

        monkeypatch.setattr(GatewayClient, "from_hass", client_from_hass)
        hass.entry.data[CONF_GATEWAY_TOKEN] = "stale-token"

        with pytest.raises(ConfigEntryNotReady, match="gateway or profile is unavailable"):
            await async_setup_entry(hass, hass.entry)
        assert hass.entry.runtime_data is None
        assert hass.bus.listeners == []

        hass.entry.data[CONF_GATEWAY_TOKEN] = "current-token"
        assert await async_setup_entry(hass, hass.entry)
        assert clients[-1].gateway_token == "current-token"
        assert hass.entry.runtime_data.coordinator.writes_allowed() is True
        assert await async_unload_entry(hass, hass.entry)
        hass.entry.unload()

    asyncio.run(run())


def test_discovery_update_reloads_endpoint_and_token(monkeypatch):
    async def run():
        hass = FakeLifecycleHass()
        clients = []

        def client_from_hass(_hass, url, token):
            client = FakeGateway()
            client.base_url = url
            client.gateway_token = token
            clients.append(client)
            return client

        monkeypatch.setattr(GatewayClient, "from_hass", client_from_hass)
        assert await async_setup_entry(hass, hass.entry)
        old_coordinator = hass.entry.runtime_data.coordinator
        assert hass.entry.runtime_data.client is clients[0]
        assert len(hass.entry.listeners) == 1
        assert hass.bus.listeners

        await hass.entry.update(
            hass,
            {CONF_GATEWAY_URL: "http://new-gateway:8099", CONF_GATEWAY_TOKEN: "new-token"},
        )

        assert hass.config_entries.reloads == [hass.entry.entry_id]
        assert old_coordinator._started is False
        assert hass.entry.unique_id == "supervisor-discovery-uuid"
        assert len(hass.entry.listeners) == 1
        assert hass.entry.runtime_data.client is clients[1]
        assert clients[1].base_url == "http://new-gateway:8099"
        assert clients[1].gateway_token == "new-token"
        assert await async_unload_entry(hass, hass.entry)
        hass.entry.unload()
        assert hass.bus.listeners == []
        assert hass.entry.listeners == []

    asyncio.run(run())


def test_repeated_supervisor_discovery_keeps_one_entry_identity_and_rotates_credentials(monkeypatch):
    async def run():
        hass = FakeLifecycleHass()
        clients = []

        def client_from_hass(_hass, url, token):
            gateway = FakeGateway()
            gateway.base_url = url
            gateway.gateway_token = token
            clients.append(gateway)
            return gateway

        monkeypatch.setattr(GatewayClient, "from_hass", client_from_hass)
        first = validate_discovery_payload(
            {"uuid": hass.entry.unique_id, "config": {"host": "switchboard", "port": 8099, "token": "first-token"}}
        )
        duplicate = validate_discovery_payload(
            {"uuid": hass.entry.unique_id, "config": {"host": "switchboard", "port": 8099, "token": "rotated-token"}}
        )
        assert first.unique_id == duplicate.unique_id == hass.entry.unique_id
        hass.entry.data = first.as_data()

        assert await async_setup_entry(hass, hass.entry)
        await hass.entry.update(hass, duplicate.as_data())

        assert hass.config_entries.reloads == [hass.entry.entry_id]
        assert len(clients) == 2
        assert hass.entry.runtime_data.client is clients[1]
        assert hass.entry.runtime_data.client.gateway_token == "rotated-token"
        assert hass.entry.unique_id == first.unique_id
        assert await async_unload_entry(hass, hass.entry)
        hass.entry.unload()

    asyncio.run(run())


def test_forward_failure_cleans_coordinator_and_runtime_data(monkeypatch):
    async def run():
        hass = FakeLifecycleHass()
        hass.config_entries.forward_error = RuntimeError("forward failed")
        monkeypatch.setattr(GatewayClient, "from_hass", lambda *_args: FakeGateway())

        with pytest.raises(RuntimeError, match="forward failed"):
            await async_setup_entry(hass, hass.entry)

        assert hass.bus.listeners == []
        assert hass.data.get(DOMAIN, {}) == {}
        assert hass.entry.runtime_data is None
        assert hass.entry.listeners == []
        assert hass.entry.unload_callbacks == []
        await asyncio.sleep(0)
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]

    asyncio.run(run())


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def json(self, **_kwargs):
        return {"status": "ok"}


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse()


def test_supervisor_discovery_reads_nested_config_and_preserves_uuid():
    endpoint = validate_discovery_payload(
        {
            "service": "ha_switchboard",
            "uuid": "supervisor-discovery-uuid",
            "config": {"host": "local-ha-switchboard", "port": 8099, "token": "secret"},
        }
    )
    assert endpoint.url == "http://local-ha-switchboard:8099"
    assert endpoint.unique_id == "supervisor-discovery-uuid"
    assert endpoint.token == "secret"


def test_hassio_discovery_update_leaves_reload_to_entry_listener(monkeypatch):
    if not hasattr(ConfigFlow, "_abort_if_unique_id_configured"):
        pytest.skip("Home Assistant config flow is not installed")

    async def run():
        observed = {}

        async def set_unique_id(_flow, unique_id):
            observed["unique_id"] = unique_id

        def abort_if_configured(_flow, **kwargs):
            observed.update(kwargs)

        monkeypatch.setattr(ConfigFlow, "async_set_unique_id", set_unique_id)
        monkeypatch.setattr(ConfigFlow, "_abort_if_unique_id_configured", abort_if_configured)
        monkeypatch.setattr(ConfigFlow, "async_show_form", lambda _flow, **kwargs: kwargs)
        flow = ConfigFlow()
        form = await flow.async_step_hassio(
            SimpleNamespace(
                uuid="supervisor-discovery-uuid",
                config={"host": "local-ha-switchboard", "port": 8099, "token": "new-token"},
                name="HA Switchboard",
            )
        )
        assert form["step_id"] == "hassio_confirm"
        assert observed == {
            "unique_id": "supervisor-discovery-uuid",
            "updates": {CONF_GATEWAY_URL: "http://local-ha-switchboard:8099", CONF_GATEWAY_TOKEN: "new-token"},
            "reload_on_update": False,
        }

    asyncio.run(run())


def test_discovery_without_an_endpoint_is_rejected():
    with pytest.raises(DiscoveryValidationError):
        validate_discovery_payload({"uuid": "missing-endpoint"})


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (" https://gateway.example:8099/// ", "https://gateway.example:8099"),
        ("http://[::1]:8099/", "http://[::1]:8099"),
    ],
)
def test_manual_gateway_url_is_normalized_without_changing_transport(raw_url, expected):
    endpoint = validate_manual_input({CONF_GATEWAY_URL: raw_url, CONF_GATEWAY_TOKEN: "token"})
    equivalent = validate_manual_input({CONF_GATEWAY_URL: expected, CONF_GATEWAY_TOKEN: "other-token"})
    assert endpoint.url == expected
    assert endpoint.unique_id == equivalent.unique_id


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://user:pass@gateway.example:8099",
        "https://gateway.example:8099?token=secret",
        "https://gateway.example:8099#fragment",
        "https://[::1",
        "ftp://gateway.example:8099",
    ],
)
def test_manual_gateway_url_rejects_unsafe_or_malformed_values(raw_url):
    with pytest.raises(DiscoveryValidationError):
        validate_manual_input({CONF_GATEWAY_URL: raw_url})


def test_manual_gateway_token_is_retained_only_as_entry_data():
    endpoint = validate_manual_input({CONF_GATEWAY_URL: "http://gateway.example:8099", CONF_GATEWAY_TOKEN: "secret"})
    assert endpoint.as_data() == {CONF_GATEWAY_URL: "http://gateway.example:8099", CONF_GATEWAY_TOKEN: "secret"}
    assert endpoint.title == "HA Switchboard"
    assert "secret" not in endpoint.title


def test_home_assistant_can_load_the_required_config_flow_class():
    assert ConfigFlow is not None


def test_gateway_client_uses_home_assistant_async_session():
    async def run():
        session = FakeSession()
        client = GatewayClient("http://gateway.local:8099", "secret", session=session)
        assert await client.health() == {"status": "ok"}
        assert await client.app_status() == {"status": "ok"}
        method, url, kwargs = session.calls[0]
        assert method == "GET"
        assert url == "http://gateway.local:8099/healthz"
        assert kwargs["headers"]["Authorization"] == "Bearer secret"
        assert session.calls[1][1] == "http://gateway.local:8099/v1/app/status"
        assert session.calls[1][2]["headers"]["Authorization"] == "Bearer secret"

    asyncio.run(run())


def test_profile_snapshot_is_sanitized_and_matches_core_target_map():
    async def run():
        hass = FakeHass()
        build = await HomeAssistantProfileAdapter(hass, "fixture").async_build()
        assert "light.living_room" not in repr(build.snapshot)
        reference = adapter_ref("light.living_room")
        target_id = capability_id(reference, "turn_on")
        assert target_id in build.targets
        assert build.targets[target_id].entity_id == "light.living_room"

        from ha_switchboard.profile import ProfileCompiler

        profile = ProfileCompiler().compile(build.snapshot)
        assert {item.capability_id for item in profile.capabilities} <= set(build.targets)

    asyncio.run(run())


def test_coordinator_supplies_context_and_does_not_reconcile_on_state_changes():
    async def run():
        hass = FakeHass()
        gateway = FakeGateway()
        entry = SimpleNamespace(data={"profile_refresh_minutes": 60}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))
        await coordinator.async_start()
        context = coordinator.request_context()
        assert context["profile_revision"] == "profile-one"
        assert context["candidates"]
        assert "light.living_room" not in repr(context)
        assert len(gateway.reconciles) == 1

        hass.states.get("light.living_room").state = "on"
        coordinator._on_event(
            {"event_type": "state_changed", "data": {"entity_id": "light.living_room", "new_state": hass.states.get("light.living_room")}}
        )
        assert gateway.invalidations == []
        assert len(gateway.reconciles) == 1
        updated = coordinator.request_context()
        assert any(value.get("state") == "on" for value in updated["sanitized_state"].values())
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_state_attributes_are_json_safe_after_a_script_runs():
    import json
    from datetime import datetime, timezone

    coordinator = object.__new__(ProfileCoordinator)
    coordinator._state_by_capability = {}
    target = SimpleNamespace(capability_id="opaque-script")
    state = {"state": "off", "attributes": {"last_triggered": datetime(2026, 9, 19, tzinfo=timezone.utc)}}

    coordinator._set_state(target, state)

    assert json.loads(json.dumps(coordinator._state_by_capability))["opaque-script"]["attributes"]["last_triggered"] == "2026-09-19T00:00:00+00:00"


def test_conversation_explains_low_confidence_instead_of_generic_failure():
    from custom_components.ha_switchboard.conversation import _response_text

    assert "one device" in _response_text({"response_key": "confidence_too_low"})
    assert "currently available" in _response_text({"response_key": "request_refused"})
    assert "cannot collect yet" in _response_text({"response_key": "confirmation_required"})


def test_registry_event_invalidates_and_reconciles():
    async def run():
        hass = FakeHass()
        gateway = FakeGateway()
        entry = SimpleNamespace(data={}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))
        await coordinator.async_start()
        await coordinator.async_handle_event("entity_registry_updated")
        assert gateway.invalidations == ["entity_registry_updated"]
        assert len(gateway.reconciles) == 2
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_home_assistant_started_event_triggers_complete_rescan():
    async def run():
        hass = FakeHass()
        gateway = FakeGateway()
        entry = SimpleNamespace(data={}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))
        await coordinator.async_start()
        await coordinator.async_handle_event("homeassistant_started")
        assert gateway.invalidations == ["homeassistant_started"]
        assert len(gateway.reconciles) == 2
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_core_execution_validates_parameters_before_calling_home_assistant():
    async def run():
        hass = FakeHass()
        reference = adapter_ref("light.living_room")
        target = CapabilityTarget(
            capability_id(reference, "turn_on"),
            reference,
            "light.living_room",
            "light",
            "turn_on",
            operation_spec("light", "turn_on"),
        )
        mapping = CapabilityMap()
        mapping.replace("profile-one", {target.capability_id: target})
        boundary = ExecutionBoundary(CoreHomeAssistantExecutor(hass, mapping))
        invalid = await boundary.execute_proposal(
            capability_id=target.capability_id,
            parameters={"unexpected": "value"},
            expected_profile_revision="profile-one",
            current_profile_revision="profile-one",
            confirmed=False,
        )
        assert invalid["response_key"] == "invalid_parameters"
        valid = await boundary.execute_proposal(
            capability_id=target.capability_id,
            parameters={},
            expected_profile_revision="profile-one",
            current_profile_revision="profile-one",
            confirmed=False,
        )
        assert valid["response_key"] == "execute_verified"
        assert hass.services.calls[0][2]["entity_id"] == "light.living_room"

    asyncio.run(run())


_REMAINING_SINGLE_DEVICE_OPERATIONS = tuple(sorted(set(OPERATION_SPECS) - {("light", "turn_on")}))


@pytest.mark.parametrize(("domain", "operation"), _REMAINING_SINGLE_DEVICE_OPERATIONS)
def test_core_verifies_every_remaining_single_device_routine_operation(domain, operation):
    async def run():
        hass = OperationHass(domain, operation)
        spec = operation_spec(domain, operation)
        assert spec is not None
        target = CapabilityTarget(
            f"{domain}:{operation}",
            f"fixture:{domain}",
            f"{domain}.fixture",
            domain,
            operation,
            spec,
        )
        mapping = CapabilityMap()
        mapping.replace("profile-one", {target.capability_id: target})
        parameters = {
            "brightness": 42,
            "volume": 0.4,
            "temperature": 21,
            "hvac_mode": "heat",
        }
        properties = spec.parameter_schema.get("properties", {})
        parameters = {key: value for key, value in parameters.items() if key in properties}
        boundary = ExecutionBoundary(CoreHomeAssistantExecutor(hass, mapping))

        result = await boundary.execute_proposal(
            capability_id=target.capability_id,
            parameters=parameters,
            expected_profile_revision="profile-one",
            current_profile_revision="profile-one",
            confirmed=spec.risk_class == "confirm",
            request_id=f"routine-{domain}-{operation}",
        )

        assert result["ok"] is True
        assert result["response_key"] == "execute_verified"
        assert result["result"] == {"ok": True}
        assert result["post_state"]["state"] not in {"unknown", "unavailable"}
        assert len(hass.services.calls) == 1
        service_domain, service, data, blocking = hass.services.calls[0]
        assert (service_domain, service) == (spec.service_domain, spec.service)
        assert data["entity_id"] == target.entity_id
        assert blocking is True

    asyncio.run(run())


def test_app_refresh_option_does_not_replace_explicit_core_override():
    async def run():
        hass = FakeHass()
        gateway = FakeGateway()
        gateway.app_status_payload = {"profile_refresh_minutes": 3}
        entry = SimpleNamespace(data={"profile_refresh_minutes": 60}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))
        await coordinator.async_start()
        await coordinator._recovery_tick()
        assert coordinator.refresh_minutes == 60
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_empty_app_options_do_not_block_core_profile_recovery():
    async def run():
        hass = FakeHass()
        gateway = FakeGateway()
        gateway.app_status_payload = {}
        entry = SimpleNamespace(data={}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))

        await coordinator.async_start()
        assert coordinator.profile_revision == gateway.revision
        assert coordinator.last_error is None
        assert coordinator.status()["scan_state"] == "completed"
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_provider_outage_keeps_last_active_profile_and_records_recovery_error():
    async def run():
        class OutageGateway(FakeGateway):
            async def status(self):
                raise GatewayClientError("provider unavailable")

        hass = FakeHass()
        gateway = OutageGateway()
        entry = SimpleNamespace(data={}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))

        await coordinator.async_start()
        revision = coordinator.profile_revision
        await coordinator._recovery_tick()

        assert coordinator.profile_revision == revision == gateway.revision
        assert len(gateway.reconciles) == 1
        assert coordinator.last_error == "GatewayClientError"
        assert coordinator.writes_allowed() is True
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_reconcile_does_not_publish_build_from_an_older_generation():
    async def run():
        hass = FakeHass()
        gateway = FakeGateway()
        entry = SimpleNamespace(data={}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))
        original_build = coordinator.adapter.async_build
        first = True

        async def build_with_invalidation():
            nonlocal first
            result = await original_build()
            if first:
                first = False
                coordinator._profile_generation += 1
                coordinator._stale = True
            return result

        coordinator.adapter.async_build = build_with_invalidation
        await coordinator.async_reconcile()
        assert len(gateway.reconciles) == 2
        assert coordinator.profile_revision == gateway.revision
        assert coordinator.writes_allowed() is False

    asyncio.run(run())


def test_core_denies_blocked_and_unsupported_routine_targets_even_when_confirmed():
    async def run():
        hass = FakeHass()
        mapping = CapabilityMap()
        blocked = CapabilityTarget(
            "blocked", "blocked", "lock.front_door", "lock", "lock",
            OperationSpec("lock", "lock", {"properties": {}}, "blocked"),
        )
        script = CapabilityTarget(
            "script", "script", "script.goodnight", "script", "activate", operation_spec("script", "activate")
        )
        mapping.replace("profile-one", {"blocked": blocked, "script": script})
        boundary = ExecutionBoundary(CoreHomeAssistantExecutor(hass, mapping))

        blocked_result = await boundary.execute_proposal(
            capability_id="blocked", parameters={}, expected_profile_revision="profile-one",
            current_profile_revision="profile-one", confirmed=True,
        )
        script_result = await boundary.execute_proposal(
            capability_id="script", parameters={}, expected_profile_revision="profile-one",
            current_profile_revision="profile-one", confirmed=True,
        )
        assert blocked_result["response_key"] == "policy_denied"
        assert script_result["response_key"] == "candidate_not_allowed"
        assert hass.services.calls == []

    asyncio.run(run())


def test_startup_reconciles_before_refresh_timer_and_manual_scan_is_bounded():
    async def run():
        hass = FakeHass()
        gateway = FakeGateway()
        entry = SimpleNamespace(data={}, entry_id="entry-one")
        coordinator = ProfileCoordinator(hass, entry, gateway, HomeAssistantProfileAdapter(hass, "fixture"))
        await coordinator.async_start()
        assert len(gateway.reconciles) == 1
        assert coordinator.profile_revision == gateway.revision
        await coordinator.async_shutdown()

    asyncio.run(run())


def test_core_batch_partial_failure_reports_verified_targets_for_request():
    class Executor:
        def __init__(self):
            self.writes = []
            self.targets = {
                key: CapabilityTarget(
                    key, key, f"light.fixture_{key}", "light", "turn_on", operation_spec("light", "turn_on")
                )
                for key in ("one", "two", "three")
            }
            self.states = {key: "off" for key in self.targets}

        def profile_current(self, _revision):
            return True

        async def resolve_capability(self, capability_id):
            return self.targets.get(capability_id)

        async def read_state(self, target):
            return {"state": self.states[target.capability_id], "attributes": {}}

        async def execute(self, target, _parameters):
            self.writes.append(target.capability_id)
            if target.capability_id != "two":
                self.states[target.capability_id] = "on"
            return {"ok": True}

        def verify(self, _target, _parameters, _before, after, _result):
            return after["state"] == "on"

    async def run():
        executor = Executor()
        result = await ExecutionBoundary(executor).execute_batch_proposal(
            capability_ids=("one", "two", "three"),
            expected_profile_revision="current",
            current_profile_revision="current",
            request_id="batch-partial",
        )
        assert result == {
            "ok": False,
            "response_key": "batch_partial_failure",
            "verified_count": 1,
            "total_count": 3,
            "target_results": [{"capability_id": "one", "display_name": "light", "verified": True}],
        }
        assert executor.writes == ["one", "two"]

    asyncio.run(run())


def test_core_batch_success_reports_each_verified_target_for_request():
    class Executor:
        def __init__(self):
            self.targets = {
                key: CapabilityTarget(
                    key,
                    key,
                    f"light.fixture_{key}",
                    "light",
                    "turn_on",
                    operation_spec("light", "turn_on"),
                    display_name=f"Fixture {key}",
                )
                for key in ("one", "two")
            }
            self.states = {key: "off" for key in self.targets}

        def profile_current(self, _revision):
            return True

        async def resolve_capability(self, capability_id):
            return self.targets.get(capability_id)

        async def read_state(self, target):
            return {"state": self.states[target.capability_id], "attributes": {}}

        async def execute(self, target, _parameters):
            self.states[target.capability_id] = "on"
            return {"ok": True}

        def verify(self, _target, _parameters, _before, after, result):
            return result["ok"] and after["state"] == "on"

    async def run():
        result = await ExecutionBoundary(Executor()).execute_batch_proposal(
            capability_ids=("one", "two"),
            expected_profile_revision="current",
            current_profile_revision="current",
            request_id="batch-success",
        )
        assert result == {
            "ok": True,
            "response_key": "batch_execute_verified",
            "verified_count": 2,
            "total_count": 2,
            "target_results": [
                {"capability_id": "one", "display_name": "Fixture one", "verified": True},
                {"capability_id": "two", "display_name": "Fixture two", "verified": True},
            ],
        }

    asyncio.run(run())
