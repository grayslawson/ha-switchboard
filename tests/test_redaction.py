from __future__ import annotations

import pytest

from ha_switchboard.redaction import SensitiveDataError, opaque_id, sanitize_for_gateway, sanitize_state


def test_credentials_are_rejected() -> None:
    with pytest.raises(SensitiveDataError):
        sanitize_for_gateway({"authorization": "Bearer secret"})


def test_raw_entity_references_are_rejected() -> None:
    with pytest.raises(SensitiveDataError):
        sanitize_for_gateway({"entity_id": "light.living_room"})


def test_private_state_is_removed_before_model_transport() -> None:
    assert sanitize_state({"temperature": 20, "occupancy": True}) == {"temperature": 20}


def test_opaque_ids_are_stable_and_do_not_contain_the_source() -> None:
    value = opaque_id("adapter", "light.living_room")
    assert value == opaque_id("adapter", "light.living_room")
    assert "living_room" not in value
