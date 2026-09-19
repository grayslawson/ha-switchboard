from __future__ import annotations

import importlib.util
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
    (source / ".devcontainer").mkdir()
    (source / ".github").mkdir()
    (source / "docs").mkdir()
    (source / "tools").mkdir()
    (source / "README.md").write_text("public\n", encoding="utf-8")
    (source / ".forgejo" / "workflows" / "private.yml").write_text(
        "name: private\n", encoding="utf-8"
    )
    (source / ".devcontainer" / "devcontainer.json").write_text("internal\n", encoding="utf-8")
    (source / ".github" / "actionlint.yaml").write_text("internal\n", encoding="utf-8")
    (source / "docs" / "PUBLIC_REPOSITORY.md").write_text("internal\n", encoding="utf-8")
    (source / "tools" / "ha-switchboard-export-public.py").write_text(
        "internal\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "--initial-branch=master"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", "README.md", ".forgejo", ".devcontainer", ".github", "docs", "tools"],
        cwd=source,
        check=True,
    )
    result = ha_switchboard_export_public.export(source, destination)
    assert result == []
    assert (destination / "README.md").is_file()
    assert not (destination / ".forgejo").exists()
    assert not (destination / ".devcontainer").exists()
    assert not (destination / ".github").exists()
    assert not (destination / "docs" / "PUBLIC_REPOSITORY.md").exists()
    assert not (destination / "tools" / "ha-switchboard-export-public.py").exists()
