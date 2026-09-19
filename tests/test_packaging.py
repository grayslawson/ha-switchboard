from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def test_app_manifest_declares_portable_least_privilege_defaults() -> None:
    manifest = (ROOT / "app" / "config.yaml").read_text(encoding="utf-8")
    assert 'slug: "ha_switchboard"' in manifest
    assert "amd64" in manifest and "aarch64" in manifest
    assert "homeassistant_api: false" in manifest
    assert "hassio_api: false" in manifest
    assert "host_network: false" in manifest
    assert "privileged: []" in manifest
    # Supervisor expects this setting to be a boolean. The custom profile name
    # is taken from app/apparmor.txt and must match the app slug.
    assert "apparmor: true" in manifest
    assert "ingress: true" in manifest
    assert "backup: hot" in manifest
    assert "ingress_only: true" in manifest
    assert "ingress_only: bool" in manifest


def test_app_entrypoint_is_executable_under_custom_apparmor_profile() -> None:
    dockerfile = (ROOT / "app" / "Dockerfile").read_text(encoding="utf-8")
    apparmor = (ROOT / "app" / "apparmor.txt").read_text(encoding="utf-8")
    entrypoint = ROOT / "app" / "run.sh"

    assert entrypoint.stat().st_mode & 0o111
    assert "RUN chmod 0555 /run.sh" in dockerfile
    for rule in ("/run.sh rix", "/bin/sh rix", "/bin/busybox rix", "/usr/local/bin/python3 rix"):
        assert rule in apparmor


def test_devcontainer_is_development_only() -> None:
    if not (ROOT / ".devcontainer").exists():
        pytest.skip("the development-only App harness is private infrastructure")
    config = json.loads((ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))
    assert config["image"].startswith("ghcr.io/home-assistant/devcontainer:")
    assert "--privileged" in config["runArgs"]
    manifest = (ROOT / "app" / "config.yaml").read_text(encoding="utf-8")
    assert "--privileged" not in manifest


def test_standalone_path_has_explicit_persistence_and_healthcheck() -> None:
    compose = (ROOT / "standalone" / "compose.yaml").read_text(encoding="utf-8")
    assert ":/data" in compose
    assert "healthcheck:" in compose
    assert "JEV_ENDPOINT" in compose
