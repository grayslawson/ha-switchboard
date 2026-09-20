from __future__ import annotations

import json
import os
import stat
from types import SimpleNamespace

import pytest

from ha_switchboard.store import ProfileStore, STATE_SCHEMA_VERSION


def test_legacy_profile_is_migrated_atomically_and_survives_new_store(tmp_path) -> None:
    legacy = {"profile_id": "fixture-profile", "revision": "fixture-revision", "status": "stale"}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    store = ProfileStore(tmp_path)
    assert store.load_profile() == legacy

    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated == {"profile": legacy, "schema_version": STATE_SCHEMA_VERSION}
    assert ProfileStore(tmp_path).load_profile() == legacy


def test_options_snapshot_is_secret_free_backup_safe_and_restart_safe(tmp_path) -> None:
    store = ProfileStore(tmp_path)
    first = {"gateway_mode": "adapter_only", "privacy_mode": "local_only"}
    second = {"gateway_mode": "adapter_only", "privacy_mode": "hosted_allowed"}

    store.save_options_snapshot(first)
    assert ProfileStore(tmp_path).load_options_snapshot() == first
    store.save_options_snapshot(second)

    assert ProfileStore(tmp_path).load_options_snapshot() == second
    backup = json.loads((tmp_path / "options-state.previous.json").read_text(encoding="utf-8"))
    assert backup == {"options": first, "schema_version": STATE_SCHEMA_VERSION}

    (tmp_path / "options-state.json").write_text("{broken", encoding="utf-8")
    assert ProfileStore(tmp_path).load_options_snapshot() == first


def test_empty_options_remain_a_valid_non_provider_snapshot(tmp_path) -> None:
    store = ProfileStore(tmp_path)
    store.save_options_snapshot({})

    assert ProfileStore(tmp_path).load_options_snapshot() == {}


def test_state_writes_are_private_and_failed_writes_keep_previous_value(tmp_path) -> None:
    store = ProfileStore(tmp_path)
    store.save_status({"status": "active"})
    previous = store.status_path.read_text(encoding="utf-8")

    with pytest.raises(TypeError):
        store._atomic_write(store.status_path, {"status": SimpleNamespace()})

    assert store.status_path.read_text(encoding="utf-8") == previous
    assert stat.S_IMODE(store.status_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path).st_mode) == 0o700


def test_options_snapshot_rejects_credential_fields(tmp_path) -> None:
    store = ProfileStore(tmp_path)

    with pytest.raises(ValueError):
        store.save_options_snapshot({"gateway_token": "fixture-value"})
