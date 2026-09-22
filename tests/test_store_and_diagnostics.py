from __future__ import annotations

import json

import pytest

from ha_switchboard.store import ProfileStore


def test_store_migrates_v1_profile_and_writes_versioned_envelope(tmp_path) -> None:
    store = ProfileStore(tmp_path)
    legacy = {"profile_id": "p", "revision": "r"}
    store.profile_path.write_text(json.dumps(legacy), encoding="utf-8")
    assert store.load_profile() == legacy
    store._atomic_write(store.status_path, {"schema_version": 2, "status": {"ok": True}})
    assert store.load_status() == {"ok": True}


def test_store_rejects_oversized_or_secret_state(tmp_path) -> None:
    store = ProfileStore(tmp_path)
    with pytest.raises(ValueError):
        store.save_status({"gateway_token": "secret"})
    store.status_path.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ValueError):
        store.load_status()


def test_store_rejects_symlinked_state_and_directory(tmp_path) -> None:
    store = ProfileStore(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"status": {"safe": True}}), encoding="utf-8")
    store.status_path.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        store.load_status()

    linked_dir = tmp_path / "linked"
    target = tmp_path / "target"
    target.mkdir()
    linked_dir.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        ProfileStore(linked_dir)
