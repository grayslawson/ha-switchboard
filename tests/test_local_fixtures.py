from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tools" / "local-fixtures"

pytestmark = pytest.mark.local_fixture


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coverage_report_matches_every_published_matrix_row() -> None:
    api = load_module("local_fixture_api", FIXTURE / "local_api.py")
    states = {entity_id: {"state": "off"} for _, _, entity_id in api.PUBLISHED_MATRIX}
    exposed = {entity_id: {"conversation": True} for entity_id in states}

    report = api.coverage_report(states, exposed)

    assert report["matrix_rows"] == 24
    assert report["matrix_rows"] == len(api.PUBLISHED_MATRIX)
    assert report["covered_rows"] == 24
    assert report["missing_entities"] == []
    assert report["unexposed_entities"] == []
    assert {row["operation"] for row in report["rows"]} >= {"set_brightness", "set_volume"}
    assert {row["domain"] for row in report["rows"]} == {
        "light", "switch", "fan", "media_player", "climate", "cover", "garage", "lock",
    }
    assert not {row["domain"] for row in report["rows"]} & {"script", "scene"}


def test_config_entry_report_is_secret_free_and_requires_one_entry() -> None:
    api = load_module("local_fixture_api_config_entry", FIXTURE / "local_api.py")
    entries = [{
        "domain": "ha_switchboard",
        "source": "hassio",
        "title": "HA Switchboard",
        "version": 1,
        "data": {"gateway_url": "http://local-ha-switchboard:8099", "gateway_token": "secret"},
    }]

    report = api.config_entry_report(entries)

    assert report == {
        "domain": "ha_switchboard",
        "source": "hassio",
        "title": "HA Switchboard",
        "version": 1,
        "has_gateway_token": True,
        "gateway_host": "local-ha-switchboard",
        "gateway_port": 8099,
    }
    assert "secret" not in repr(report)
    with pytest.raises(RuntimeError, match="exactly one"):
        api.config_entry_report([])


def test_discovery_fixture_covers_current_domains_and_typed_parameters() -> None:
    import json

    discovery = json.loads((ROOT / "tests" / "fixtures" / "home-assistant-discovery.json").read_text())
    domains = {item["domain"] for item in discovery["entities"]}
    assert {"light", "switch", "fan", "media_player", "climate", "cover", "lock", "sensor", "binary_sensor"} <= domains
    assert discovery["entities"][0]["parameter_schemas"]["set_brightness"]["properties"]["brightness"]["maximum"] == 100


def test_native_script_and_scene_surfaces_are_not_matrix_rows() -> None:
    api = load_module("local_fixture_api_native", FIXTURE / "local_api.py")

    assert api.NATIVE_HASS_SURFACES == (
        ("script", "activate", "script.switchboard_fixture_evening"),
        ("scene", "activate", "scene.switchboard_fixture_calm"),
    )
    assert not set(api.NATIVE_HASS_SURFACES) & set(api.PUBLISHED_MATRIX)


def test_registry_metadata_targets_skip_only_native_core_surfaces() -> None:
    api = load_module("local_fixture_api_registry", FIXTURE / "local_api.py")
    registry = [{"entity_id": entity_id} for entity_id in api.PRIMARY_ENTITIES]
    registry = [
        item for item in registry
        if item["entity_id"] not in api.NATIVE_CORE_ONLY_ENTITY_IDS
    ]

    supported, skipped = api.registry_supported_entities(registry)

    assert len(supported) == len(api.PRIMARY_ENTITIES) - 2
    assert skipped == (
        "script.switchboard_fixture_evening",
        "scene.switchboard_fixture_calm",
    )
    assert set(supported).isdisjoint(skipped)


def test_registry_metadata_targets_fail_on_missing_non_native_fixture() -> None:
    api = load_module("local_fixture_api_registry_missing", FIXTURE / "local_api.py")
    missing = "light.switchboard_fixture_lamp"
    registry = [
        {"entity_id": entity_id}
        for entity_id in api.PRIMARY_ENTITIES
        if entity_id != missing
    ]

    with pytest.raises(RuntimeError, match="light.switchboard_fixture_lamp"):
        api.registry_supported_entities(registry)


def test_coverage_report_identifies_missing_or_unexposed_fixture() -> None:
    api = load_module("local_fixture_api_coverage", FIXTURE / "local_api.py")
    entity_id = "cover.switchboard_fixture_garage"
    states = {entity_id: {"state": "closed"} for _, _, entity_id in api.PUBLISHED_MATRIX}

    exposed = {
        candidate: {"conversation": True}
        for _, _, candidate in api.PUBLISHED_MATRIX
        if candidate != entity_id
    }
    report = api.coverage_report(states, exposed)

    assert report["missing_entities"] == []
    assert report["unexposed_entities"] == [entity_id]


def test_deterministic_failure_cases_are_secret_free_and_bounded() -> None:
    api = load_module("local_fixture_api_failures", FIXTURE / "local_api.py")

    assert set(api.DETERMINISTIC_FAILURES) == {
        "provider_unavailable", "provider_malformed", "parameter_missing",
        "parameter_out_of_range", "unknown_capability",
    }
    assert api.DETERMINISTIC_FAILURES["parameter_out_of_range"]["maximum"] == 100
    assert "token" not in repr(api.DETERMINISTIC_FAILURES).lower()
    assert "secret" not in repr(api.DETERMINISTIC_FAILURES).lower()


def test_fixture_yaml_contains_all_supported_domains_and_bounded_group() -> None:
    text = (FIXTURE / "switchboard.yaml").read_text(encoding="utf-8")

    for marker in (
        "Switchboard Fixture Light", "Switchboard Fixture Switch", "Switchboard Fixture Fan",
        "Switchboard Fixture Player", "Switchboard Fixture Thermostat",
        "Switchboard Fixture Cover", "Switchboard Fixture Garage", "Switchboard Fixture Lock",
        "Switchboard Fixture Evening", "Switchboard Fixture Calm",
    ):
        assert marker in text
    assert "switchboard_fixture_lights:" in text
    assert "light.switchboard_fixture_light" in text
    assert "light.switchboard_fixture_lamp" in text


def test_named_fixture_group_is_in_profile_and_selects_only_explicitly() -> None:
    from custom_components.ha_switchboard.opaque import adapter_ref
    from ha_switchboard.profile import ProfileCompiler

    api = load_module("local_fixture_api_named_group", FIXTURE / "local_api.py")
    discovery = {
        "entities": [
            {
                "entity_id": "light.switchboard_fixture_light",
                "name": "Switchboard Fixture Light",
                "domain": "light",
                "exposed": True,
                "available": True,
                "operations": ["turn_on", "turn_off"],
            },
            {
                "entity_id": "light.switchboard_fixture_lamp",
                "name": "Switchboard Fixture Lamp",
                "domain": "light",
                "exposed": True,
                "available": True,
                "operations": ["turn_on", "turn_off"],
            },
        ],
        "organization": {
            "groups": [{
                "adapter_ref": "adapter-fixture-lights-group",
                "name": api.FIXTURE_GROUP,
                "members": [
                    adapter_ref("light.switchboard_fixture_light"),
                    adapter_ref("light.switchboard_fixture_lamp"),
                ],
            }],
        },
    }
    profile = ProfileCompiler().compile(discovery)

    report = api.named_group_acceptance(profile)

    assert report == {
        "group_name": api.FIXTURE_GROUP,
        "group_count": 1,
        "group_present": True,
        "group_valid": True,
        "member_count": 2,
        "selected": True,
        "operation": "turn_on",
        "error": None,
        "selected_member_count": 2,
    }
    assert "switchboard_fixture" not in repr(report).lower()
    assert "adapter-" not in repr(report).lower()


def test_named_fixture_group_rejects_unknown_and_invalid_selection() -> None:
    from custom_components.ha_switchboard.opaque import adapter_ref
    from ha_switchboard.profile import ProfileCompiler

    api = load_module("local_fixture_api_named_group_failures", FIXTURE / "local_api.py")
    entity = {
        "entity_id": "light.switchboard_fixture_light",
        "name": "Switchboard Fixture Light",
        "domain": "light",
        "exposed": True,
        "available": True,
        "operations": ["turn_on", "turn_off"],
    }
    base = {"entities": [entity], "organization": {"groups": []}}
    unknown_profile = ProfileCompiler().compile(base)
    unknown = api.named_group_acceptance(unknown_profile)
    assert unknown["group_present"] is False
    assert unknown["error"] == "batch_group_unknown"
    assert unknown["selected"] is False

    invalid = {
        "entities": [entity],
        "organization": {"groups": [{
            "adapter_ref": "adapter-fixture-lights-group",
            "name": api.FIXTURE_GROUP,
            "members": [adapter_ref("adapter-not-an-entity")],
        }]},
    }
    invalid_report = api.named_group_acceptance(ProfileCompiler().compile(invalid))
    assert invalid_report["group_present"] is True
    assert invalid_report["group_valid"] is False
    assert invalid_report["error"] == "batch_group_invalid"
    assert invalid_report["selected"] is False


def test_readme_labels_native_script_and_scene_outside_switchboard_matrix() -> None:
    text = (FIXTURE / "README.md").read_text(encoding="utf-8")

    assert "Native Core only; non-Switchboard fixture surfaces" in text
    assert "not exposed to Assist" in text
    assert "24 executable Switchboard operation-matrix rows" in text


def test_native_acceptance_command_proves_bypass_and_restores_fixture_state() -> None:
    text = (FIXTURE / "local_api.py").read_text(encoding="utf-8")

    assert '"native"' in text
    assert '"prefer_local_intents": True' in text
    assert '"native_provider_bypass": "proved"' in text
    assert 'after_state != before_state' in text
    assert '/v1/diagnostics?limit=1&route_class=jev' in text
    assert 'if command != "native":' in text


def test_follow_up_harness_output_is_redacted_before_issue_or_release_evidence() -> None:
    text = (FIXTURE / "local_api.py").read_text(encoding="utf-8")

    assert '"fixture_entity_count": len(fixtures)' in text
    assert '"diagnostic_sensor_count": len(diagnostic_sensors)' in text
    assert '"Fixture entities:"' not in text
    assert '[(name, states[name]["state"]) for name in fixtures]' not in text


def test_installer_accepts_only_running_busy_cohen_on_local_port() -> None:
    installer = load_module("local_fixture_installer", FIXTURE / "install.py")
    base = {
        "Name": "/busy_cohen",
        "State": {"Running": True},
        "NetworkSettings": {"Ports": {"80/tcp": [{"HostPort": "7123"}]}},
    }
    installer.validate_local_container(base)

    for bad in (
        {**base, "Name": "/homeassistant"},
        {**base, "State": {"Running": False}},
        {**base, "NetworkSettings": {"Ports": {"80/tcp": [{"HostPort": "8123"}]}}},
    ):
        try:
            installer.validate_local_container(bad)
        except SystemExit as error:
            assert "Refusing" in str(error)
        else:
            raise AssertionError("unsafe container was accepted")


def test_installer_is_non_destructive_and_include_is_marked() -> None:
    text = (FIXTURE / "install.py").read_text(encoding="utf-8")

    assert "docker" in text
    assert "docker volume rm" not in text
    assert "docker rm" not in text
    assert "docker compose down" not in text
    assert "MARKER" in text
    assert "if marker not in original" in text
    assert "Existing homeassistant section needs manual merge" in text
