from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def test_core_integration_binds_empty_config_schema_to_domain() -> None:
    """Keep the integration compatible with current Home Assistant helpers."""

    source = (ROOT / "custom_components" / "ha_switchboard" / "__init__.py").read_text(
        encoding="utf-8"
    )
    module = ast.parse(source)
    schema_assignments = [
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CONFIG_SCHEMA" for target in node.targets)
    ]

    assert any(
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "empty_config_schema"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id == "DOMAIN"
        for value in schema_assignments
    )


def test_python_distribution_scopes_only_the_gateway_package() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '[tool.setuptools.packages.find]' in project
    assert 'where = ["app"]' in project
    assert 'include = ["ha_switchboard*"]' in project


def test_app_manifest_declares_portable_least_privilege_defaults() -> None:
    manifest = (ROOT / "app" / "config.yaml").read_text(encoding="utf-8")
    assert 'slug: "ha_switchboard"' in manifest
    assert "amd64" in manifest and "aarch64" in manifest
    assert "homeassistant_api: false" in manifest
    # Scoped Supervisor API access is required for App discovery registration.
    assert "hassio_api: true" in manifest
    assert "host_network: false" in manifest
    assert "privileged: []" in manifest
    # Supervisor expects this setting to be a boolean. The custom profile name
    # is taken from app/apparmor.txt and must match the app slug.
    assert "apparmor: true" in manifest
    assert "ingress: true" in manifest
    assert "backup: hot" in manifest
    assert "ingress_only: true" in manifest
    assert "ingress_only: bool" in manifest
    options = manifest.split("options:", 1)[1].split("schema:", 1)[0]
    assert "jev_endpoint:" not in options


def test_app_entrypoint_is_executable_under_custom_apparmor_profile() -> None:
    dockerfile = (ROOT / "app" / "Dockerfile").read_text(encoding="utf-8")
    apparmor = (ROOT / "app" / "apparmor.txt").read_text(encoding="utf-8")
    entrypoint = ROOT / "app" / "run.sh"

    assert entrypoint.stat().st_mode & 0o111
    assert "RUN chmod 0555 /run.sh" in dockerfile
    assert "USER 0:0" in dockerfile
    assert "_prepare_data_dir_and_drop_privileges" in (ROOT / "app" / "ha_switchboard" / "server.py").read_text(encoding="utf-8")
    for rule in ("capability chown", "capability setgid", "capability setuid", "/data/ rw"):
        assert rule in apparmor
    for rule in ("/run.sh rix", "/bin/sh rix", "/bin/busybox rix", "/usr/local/bin/python3 rix"):
        assert rule in apparmor
    for rule in (
        "/lib/** mr",
        "/usr/lib/** mr",
        "/usr/local/lib/** mr",
    ):
        assert rule in apparmor
    assert "/app/** r," in apparmor
    assert "/app/** rix," not in apparmor


def test_devcontainer_is_development_only() -> None:
    if not (ROOT / ".devcontainer").exists():
        pytest.skip("the development-only App harness is private infrastructure")
    config = json.loads((ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))
    assert config["image"].startswith("ghcr.io/home-assistant/devcontainer:")
    assert "--privileged" in config["runArgs"]
    assert "7123:80" in config["appPort"]
    manifest = (ROOT / "app" / "config.yaml").read_text(encoding="utf-8")
    assert "--privileged" not in manifest


def test_standalone_path_has_explicit_persistence_and_healthcheck() -> None:
    compose = (ROOT / "standalone" / "compose.yaml").read_text(encoding="utf-8")
    assert ":/data" in compose
    assert "healthcheck:" in compose
    assert "JEV_ENDPOINT" in compose
    assert 'PRIVACY_MODE: "${PRIVACY_MODE:-local_only}"' in compose
    assert 'FALLBACK_PROVIDER: "${FALLBACK_PROVIDER:-disabled}"' in compose
    assert "FALLBACK_ENDPOINT" in compose
    assert "FALLBACK_API_KEY" in compose
    assert '"127.0.0.1:${HA_SWITCHBOARD_PORT:-8099}:8099"' in compose
    assert "read_only: true" in compose
    assert "/tmp:rw,noexec,nosuid,nodev" in compose
