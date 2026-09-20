from __future__ import annotations

import pytest

from ha_switchboard.redaction import (
    SensitiveDataError,
    opaque_id,
    require_secure_provider_endpoint,
    sanitize_for_gateway,
    sanitize_state,
)


def test_credentials_are_rejected() -> None:
    with pytest.raises(SensitiveDataError):
        sanitize_for_gateway({"authorization": "Bearer secret"})


@pytest.mark.parametrize(
    "field",
    ["apiKey", "API-KEY", "accessToken", "bearer_token", "X API Key", "fallback_api_key", "secret_key", "x-api-key"],
)
def test_credential_field_name_variants_are_rejected(field: str) -> None:
    with pytest.raises(SensitiveDataError):
        sanitize_for_gateway({field: "secret"})


def test_benign_words_containing_key_are_not_rejected() -> None:
    assert sanitize_for_gateway({"monkey": "a harmless value"}) == {"monkey": "a harmless value"}


def test_raw_entity_references_are_rejected() -> None:
    with pytest.raises(SensitiveDataError):
        sanitize_for_gateway({"entity_id": "light.living_room"})


@pytest.mark.parametrize("field", ["entityId", "ENTITY-ID", "deviceId", "configEntryId"])
def test_raw_reference_field_name_variants_are_rejected(field: str) -> None:
    with pytest.raises(SensitiveDataError):
        sanitize_for_gateway({field: "opaque-looking-but-raw"})


def test_private_state_is_removed_before_model_transport() -> None:
    assert sanitize_state({"temperature": 20, "occupancy": True}) == {"temperature": 20}


def test_opaque_ids_are_stable_and_do_not_contain_the_source() -> None:
    value = opaque_id("adapter", "light.living_room")
    assert value == opaque_id("adapter", "light.living_room")
    assert "living_room" not in value


def test_remote_http_with_provider_context_is_rejected_but_local_http_is_allowed() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        require_secure_provider_endpoint("http://provider.example.invalid/api", has_credentials=False, has_context=True)
    with pytest.raises(ValueError, match="must use HTTPS"):
        require_secure_provider_endpoint("http://evil/api", has_credentials=False, has_context=True)

    require_secure_provider_endpoint("http://supervisor/api", has_credentials=True, has_context=True)
    require_secure_provider_endpoint("http://local-reasoner:8090/decide", has_credentials=False, has_context=True)
    require_secure_provider_endpoint("http://192.168.1.20/api", has_credentials=True, has_context=True)
