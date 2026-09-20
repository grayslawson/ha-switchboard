from types import SimpleNamespace

from custom_components.ha_switchboard.read_only import read_only_answer


class States:
    def __init__(self, values):
        self.values = values

    def get(self, entity_id):
        return self.values.get(entity_id)


class Target:
    def __init__(self, adapter_ref, entity_id):
        self.adapter_ref = adapter_ref
        self.entity_id = entity_id


class Targets:
    def __init__(self, values):
        self.values_ = values

    def values(self):
        return tuple(self.values_)


def profile(*rows):
    return {"entities": list(rows)}


def row(name, ref, domain="light", area="Kitchen", aliases=()):
    return {"name": name, "adapter_ref": ref, "domain": domain, "area": area,
            "aliases": list(aliases), "exposed": True, "available": True}


def test_answers_one_exposed_entity_without_gateway_or_raw_id():
    hass = SimpleNamespace(states=States({"light.kitchen": SimpleNamespace(state="on", attributes={})}))
    result = read_only_answer(hass, "Is the kitchen light on?", profile(row("Kitchen light", "r1")), Targets([Target("r1", "light.kitchen")]))
    assert result == "Kitchen light is on."
    assert "light.kitchen" not in result


def test_answers_temperature_from_core_state():
    hass = SimpleNamespace(states=States({"climate.fixture": SimpleNamespace(state="heat", attributes={"temperature": 21})}))
    result = read_only_answer(hass, "What is the fixture temperature?", profile(row("Fixture temperature", "r1", "climate")), Targets([Target("r1", "climate.fixture")]))
    assert result == "Fixture temperature is heat at 21 degrees."


def test_answers_exposed_sensor_without_action_capability():
    hass = SimpleNamespace(states=States({"sensor.fixture_temperature": SimpleNamespace(state="20.5", attributes={})}))
    result = read_only_answer(
        hass,
        "What is the Fixture Temperature Reading?",
        profile(row("Fixture Temperature Reading", "sensor-ref", "sensor")),
        Targets([]),
        {"sensor-ref": "sensor.fixture_temperature"},
    )
    assert result == "Fixture Temperature Reading is 20.5."


def test_ambiguous_name_returns_none():
    hass = SimpleNamespace(states=States({"light.a": SimpleNamespace(state="on", attributes={}), "light.b": SimpleNamespace(state="off", attributes={})}))
    rows = profile(row("Kitchen light", "a"), row("Kitchen light", "b"))
    assert read_only_answer(hass, "Is the kitchen light on?", rows, Targets([Target("a", "light.a"), Target("b", "light.b")])) is None


def test_mutating_request_is_not_intercepted():
    hass = SimpleNamespace(states=States({"light.kitchen": SimpleNamespace(state="off", attributes={})}))
    assert read_only_answer(hass, "Turn the kitchen light on", profile(row("Kitchen light", "r1")), Targets([Target("r1", "light.kitchen")])) is None


def test_unexposed_and_unknown_entity_are_not_answered():
    hass = SimpleNamespace(states=States({"light.kitchen": SimpleNamespace(state="on", attributes={})}))
    hidden = row("Kitchen light", "r1"); hidden["exposed"] = False
    assert read_only_answer(hass, "Is the kitchen light on?", profile(hidden), Targets([Target("r1", "light.kitchen")])) is None
