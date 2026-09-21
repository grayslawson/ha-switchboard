from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import check_release_boundary


EXPORTER_PATH = Path(__file__).parents[1] / "tools" / "ha-switchboard-export-public.py"
if EXPORTER_PATH.exists():
    EXPORTER_SPEC = importlib.util.spec_from_file_location("ha_switchboard_export_public", EXPORTER_PATH)
    assert EXPORTER_SPEC is not None and EXPORTER_SPEC.loader is not None
    ha_switchboard_export_public = importlib.util.module_from_spec(EXPORTER_SPEC)
    EXPORTER_SPEC.loader.exec_module(ha_switchboard_export_public)
else:
    ha_switchboard_export_public = None


def test_product_release_boundary_is_clean() -> None:
    assert check_release_boundary.violations(Path(__file__).parents[1]) == []


def test_product_source_versions_are_consistent() -> None:
    assert check_release_boundary.source_version_violations(Path(__file__).parents[1]) == []


def test_source_version_check_rejects_divergent_or_missing_markers(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    for relative in (
        "app/config.yaml",
        "app/Dockerfile",
        "app/ha_switchboard/__init__.py",
        "app/CHANGELOG.md",
        "custom_components/ha_switchboard/manifest.json",
        "pyproject.toml",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)

    project = tmp_path / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            'version = "0.2.0"', 'version = "0.2.1"'
        ),
        encoding="utf-8",
    )
    dockerfile = tmp_path / "app/Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8")
        .replace("ARG BUILD_REVISION=local", "ARG BUILD_REVISION")
        .replace(
            'org.opencontainers.image.revision="${BUILD_REVISION}"',
            'org.opencontainers.image.revision="local"',
        ),
        encoding="utf-8",
    )
    changelog = tmp_path / "app/CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace(
            "## 0.2.0 — source release candidate (not published)",
            "## 0.1.0 — source release candidate (not published)",
        ),
        encoding="utf-8",
    )

    findings = check_release_boundary.source_version_violations(tmp_path)
    assert any("release source version mismatch" in finding for finding in findings)
    assert any("missing BUILD_REVISION build marker" in finding for finding in findings)
    assert any("revision label is not wired" in finding for finding in findings)
    assert any("app/CHANGELOG.md is missing release marker" in finding for finding in findings)


def test_source_version_check_fails_closed_on_malformed_metadata(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app/config.yaml").write_text("name: HA Switchboard\n", encoding="utf-8")
    findings = check_release_boundary.source_version_violations(tmp_path)
    assert "app/config.yaml: missing version marker" in findings
    assert any("missing release source file" in finding for finding in findings)


def test_boundary_rejects_private_runtime_reference(tmp_path: Path) -> None:
    for name in ("app", "custom_components", "standalone"):
        (tmp_path / name).mkdir()
    private_address = ".".join(("192", "168", "1", "20"))
    (tmp_path / "app" / "bad.py").write_text(
        f"BASE = 'http://{private_address}:8123'\n", encoding="utf-8"
    )
    findings = check_release_boundary.violations(tmp_path)
    assert findings
    assert "private address" in findings[0]


def test_public_export_omits_private_forgejo_workflows(tmp_path: Path) -> None:
    if ha_switchboard_export_public is None:
        pytest.skip("the exporter is private mirror infrastructure")
    source = tmp_path / "source"
    destination = tmp_path / "public"
    (source / ".forgejo" / "workflows").mkdir(parents=True)
    (source / ".agents").mkdir()
    (source / ".devcontainer").mkdir()
    (source / ".github").mkdir()
    (source / ".specify").mkdir()
    (source / "specs").mkdir()
    (source / ".vscode").mkdir()
    (source / "docs").mkdir()
    (source / "tools").mkdir()
    (source / "tools" / "local-fixtures").mkdir()
    (source / "README.md").write_text("public\n", encoding="utf-8")
    (source / "AGENTS.md").write_text("internal\n", encoding="utf-8")
    (source / ".agents" / "skill.md").write_text("internal\n", encoding="utf-8")
    (source / ".forgejo" / "workflows" / "private.yml").write_text(
        "name: private\n", encoding="utf-8"
    )
    (source / ".devcontainer" / "devcontainer.json").write_text("internal\n", encoding="utf-8")
    (source / ".github" / "actionlint.yaml").write_text("internal\n", encoding="utf-8")
    (source / ".specify" / "feature.json").write_text("internal\n", encoding="utf-8")
    (source / "specs" / "private.md").write_text("internal\n", encoding="utf-8")
    (source / ".vscode" / "tasks.json").write_text("internal\n", encoding="utf-8")
    (source / "docs" / "PUBLIC_REPOSITORY.md").write_text("internal\n", encoding="utf-8")
    (source / "tools" / "ha-switchboard-export-public.py").write_text(
        "internal\n", encoding="utf-8"
    )
    (source / "tools" / "local-dev.sh").write_text("internal\n", encoding="utf-8")
    (source / "tools" / "app-image-e2e.sh").write_text("internal\n", encoding="utf-8")
    (source / "tools" / "local-fixtures" / "local_api.py").write_text("internal\n", encoding="utf-8")
    subprocess.run(["git", "init", "--initial-branch=master"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", "README.md", ".forgejo", ".devcontainer", ".github", ".vscode", "docs", "tools"],
        cwd=source,
        check=True,
    )
    result = ha_switchboard_export_public.export(source, destination)
    assert result == []
    assert (destination / "README.md").is_file()
    assert not (destination / ".forgejo").exists()
    assert not (destination / ".agents").exists()
    assert not (destination / ".devcontainer").exists()
    assert not (destination / ".github").exists()
    assert not (destination / ".specify").exists()
    assert not (destination / "specs").exists()
    assert not (destination / ".vscode").exists()
    assert not (destination / "AGENTS.md").exists()
    assert not (destination / "docs" / "PUBLIC_REPOSITORY.md").exists()
    assert not (destination / "tools" / "ha-switchboard-export-public.py").exists()
    assert not (destination / "tools" / "local-dev.sh").exists()
    assert not (destination / "tools" / "app-image-e2e.sh").exists()
    assert not (destination / "tools" / "local-fixtures").exists()


def test_public_export_omits_tests_for_private_release_and_runtime_harnesses(
    tmp_path: Path,
) -> None:
    if ha_switchboard_export_public is None:
        pytest.skip("the exporter is private mirror infrastructure")

    destination = tmp_path / "public"
    assert ha_switchboard_export_public.export(Path(__file__).parents[1], destination) == []
    assert (destination / "tools/standalone-smoke.sh").is_file()
    for relative in (
        "tests/test_app_image_e2e.py",
        "tests/test_app_security.py",
        "tests/test_local_dev.py",
        "tests/test_local_fixtures.py",
        "tests/test_manual_scan_acceptance.py",
        "tests/test_native_miss_runtime.py",
        "tests/test_preserve_first_runtime.py",
        "tests/test_release_acceptance.py",
        "tests/test_restart_acceptance.py",
        "tests/test_release_workflows.py",
    ):
        assert not (destination / relative).exists(), relative
