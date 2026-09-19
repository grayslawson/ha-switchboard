from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from tools import check_release_boundary


EXPORTER_PATH = Path(__file__).parents[1] / "tools" / "ha-switchboard-export-public.py"
EXPORTER_SPEC = importlib.util.spec_from_file_location("ha_switchboard_export_public", EXPORTER_PATH)
assert EXPORTER_SPEC is not None and EXPORTER_SPEC.loader is not None
ha_switchboard_export_public = importlib.util.module_from_spec(EXPORTER_SPEC)
EXPORTER_SPEC.loader.exec_module(ha_switchboard_export_public)


def test_product_release_boundary_is_clean() -> None:
    assert check_release_boundary.violations(Path(__file__).parents[1]) == []


def test_boundary_rejects_private_runtime_reference(tmp_path: Path) -> None:
    for name in ("app", "custom_components", "standalone"):
        (tmp_path / name).mkdir()
    (tmp_path / "app" / "bad.py").write_text("BASE = 'http://192.168.1.20:8123'\n", encoding="utf-8")
    findings = check_release_boundary.violations(tmp_path)
    assert findings
    assert "private address" in findings[0]


def test_public_export_omits_private_forgejo_workflows(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "public"
    (source / ".forgejo" / "workflows").mkdir(parents=True)
    (source / "README.md").write_text("public\n", encoding="utf-8")
    (source / ".forgejo" / "workflows" / "private.yml").write_text(
        "name: private\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "--initial-branch=master"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "add", "README.md", ".forgejo"], cwd=source, check=True)
    result = ha_switchboard_export_public.export(source, destination)
    assert result == []
    assert (destination / "README.md").is_file()
    assert not (destination / ".forgejo").exists()
