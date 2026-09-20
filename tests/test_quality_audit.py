from __future__ import annotations

from pathlib import Path

from tools import check_release_boundary


ROOT = Path(__file__).parents[1]


def _minimal_tree(root: Path) -> None:
    (root / "app" / "ha_switchboard").mkdir(parents=True)
    (root / "custom_components" / "ha_switchboard").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "standalone").mkdir()


def test_repository_quality_audit_is_clean() -> None:
    assert check_release_boundary.quality_violations(ROOT) == []


def test_fr016_traceability_records_legacy_migration_not_an_active_option() -> None:
    traceability = (ROOT / "specs" / "001-ha-switchboard-completeness" / "traceability.md").read_text(
        encoding="utf-8"
    )
    fr016 = next(line for line in traceability.splitlines() if line.startswith("| FR-016 |"))
    assert "Implemented at source" in fr016
    assert "persisted `supervisor_read_only` values are migrated" in fr016
    assert "accepted inert option" not in fr016


def test_audit_rejects_placeholders_broad_handlers_unbounded_loops_and_raw_ids(tmp_path: Path) -> None:
    _minimal_tree(tmp_path)
    (tmp_path / "app" / "ha_switchboard" / "bad.py").write_text(
        """
import logging

LOG = logging.getLogger(__name__)

def process(value):
    # TODO: replace with your token
    LOG.info("token=%s", value)
    try:
        while True:
            return {"entity_id": value}
    except Exception:
        pass
""",
        encoding="utf-8",
    )
    findings = check_release_boundary.quality_violations(tmp_path)
    assert any("placeholder marker" in item for item in findings)
    assert any("broad exception handler" in item for item in findings)
    assert any("unbounded loop" in item for item in findings)
    assert any("raw Home Assistant ID" in item for item in findings)
    assert any("secret in log" in item for item in findings)


def test_audit_allows_core_raw_id_adapter_and_ignores_fixtures(tmp_path: Path) -> None:
    _minimal_tree(tmp_path)
    (tmp_path / "app" / "ha_switchboard" / "profile.py").write_text(
        'payload = {"entity_id": "light.kitchen"}\n', encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixture.py").write_text(
        'TOKEN = "your-token"\nwhile True:\n    pass\n', encoding="utf-8"
    )
    assert check_release_boundary.quality_violations(tmp_path) == []


def test_audit_rejects_option_and_documentation_drift(tmp_path: Path) -> None:
    _minimal_tree(tmp_path)
    (tmp_path / "app" / "config.yaml").write_text(
        "options:\n  stale_option: false\nschema:\n  stale_option: bool\n  undocumented_option: str\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("See [missing](missing.md).\n", encoding="utf-8")
    (tmp_path / "app" / "DOCS.md").write_text("stale_option\n", encoding="utf-8")
    findings = check_release_boundary.quality_violations(tmp_path)
    assert any("undocumented_option" in item for item in findings)
    assert any("broken documentation link" in item for item in findings)
    assert any("missing docs/RELEASE.md" in item for item in findings)


def test_public_export_boundary_does_not_require_private_repository_policy_doc(tmp_path: Path) -> None:
    _minimal_tree(tmp_path)
    (tmp_path / "README.md").write_text(
        "See [release evidence](docs/RELEASE.md#evidence-states).\n", encoding="utf-8"
    )
    (tmp_path / "app" / "DOCS.md").write_text("local app options\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "RELEASE.md").write_text("release evidence\n", encoding="utf-8")

    findings = check_release_boundary.quality_violations(tmp_path)

    assert not any("missing docs/PUBLIC_REPOSITORY.md" in item for item in findings)


def test_audit_rejects_prohibited_response_language(tmp_path: Path) -> None:
    _minimal_tree(tmp_path)
    (tmp_path / "custom_components" / "ha_switchboard" / "conversation.py").write_text(
        'MESSAGE = "I could not safely complete that request."\n', encoding="utf-8"
    )
    findings = check_release_boundary.quality_violations(tmp_path)
    assert any("prohibited generic response language" in item for item in findings)


def test_audit_rejects_unbounded_local_harness_subprocesses(tmp_path: Path) -> None:
    _minimal_tree(tmp_path)
    tools = tmp_path / "tools"
    bounded = """
run_bounded() {
  timeout --kill-after=5s "$@"
}
"""
    (tools / "app-image-e2e.sh").write_text(bounded, encoding="utf-8")
    (tools / "app-image-smoke.sh").write_text(
        bounded + 'else\n    "$@"\n', encoding="utf-8"
    )
    (tools / "local-dev.sh").write_text(bounded, encoding="utf-8")

    findings = check_release_boundary.quality_violations(tmp_path)

    assert any("timeout fallback runs an unbounded command" in item for item in findings)
    assert sum("missing bounded subprocess boundary" in item for item in findings) == 4
