from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".forgejo" / "workflows" / name).read_text(encoding="utf-8")


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_release_candidate_has_separate_source_image_mirror_and_external_gates() -> None:
    build = _workflow("build-app.yml")
    mirror = _workflow("mirror-public.yml")
    validation = _workflow("validation.yml")
    hacs = _workflow("hacs.yml")

    assert build.index("Verify release source versions are consistent") < build.index("Build amd64 and arm64 images")
    assert build.index("Build amd64 and arm64 images") < build.index("Verify published multi-architecture image")
    assert mirror.index("Gate release on matching multi-architecture App image") < mirror.index("Push public master")
    assert mirror.index("Verify public mirror ref") < mirror.index("Create or update GitHub release from tag")
    assert "--revision" in build and "--revision" in mirror
    assert 'architecture="arm64"' not in build
    assert "hassfest@sha256" in validation
    assert "hacs/action@sha256" in hacs


def test_tag_publication_runs_the_bounded_app_e2e_gate_before_publication() -> None:
    mirror = _workflow("mirror-public.yml")

    assert "tools/app-image-e2e.sh" in mirror
    assert "timeout --kill-after=10s 300s bash tools/app-image-e2e.sh" in mirror
    assert mirror.index("tools/app-image-e2e.sh") < mirror.index("Push public master")


def test_release_version_gate_validates_the_changelog_authority() -> None:
    for name in ("build-app.yml", "mirror-public.yml"):
        workflow = _workflow(name)
        assert "app/CHANGELOG.md" in workflow
        assert "source release candidate (not published)" in workflow


def test_release_candidate_evidence_is_bounded_and_secret_sanitized() -> None:
    mirror = _workflow("mirror-public.yml")
    all_workflows = "\n".join(
        _workflow(path.name) for path in (ROOT / ".forgejo" / "workflows").glob("*.yml")
    )
    assert "for attempt in {1..12}" in mirror
    assert "sleep 10" in mirror
    assert "within 120 seconds" in mirror
    assert "timeout=30" in mirror
    assert "set -x" not in all_workflows
    assert 'echo "$GHCR_TOKEN"' not in all_workflows
    assert 'echo "$GH_MIRROR_TOKEN"' not in all_workflows
    assert "release-complete" not in all_workflows
    assert "release readiness" not in all_workflows.lower()


def test_public_export_and_release_claims_are_explicitly_separate() -> None:
    release = (ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    mirror = _workflow("mirror-public.yml")
    assert "A local version is not public-release evidence" in release
    assert "live Home Assistant canary" in release
    assert "Verify public mirror ref" in mirror
    assert "Verify GitHub release" in mirror
    assert "GHCR" in mirror


def test_source_release_metadata_is_consistent_without_claiming_publication() -> None:
    app_config = (ROOT / "app" / "config.yaml").read_text(encoding="utf-8")
    manifest = json.loads(
        (ROOT / "custom_components" / "ha_switchboard" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version: "0.2.1"' in app_config
    assert manifest["version"] == "0.2.1"
    assert 'version = "0.2.1"' in project
    assert "## 0.2.1" in (ROOT / "app" / "CHANGELOG.md").read_text(encoding="utf-8")
    release = (ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    assert "public-release evidence" in release
    assert "rollback" in release.lower()


def test_coordinated_source_version_and_public_metadata_are_truthful() -> None:
    config = _text("app/config.yaml")
    package = _text("app/ha_switchboard/__init__.py")
    dockerfile = _text("app/Dockerfile")
    manifest = json.loads(_text("custom_components/ha_switchboard/manifest.json"))
    project = tomllib.loads(_text("pyproject.toml"))
    versions = {
        "app/config.yaml": re.search(
            r"^version:\s*[\"']?([^\"'\s]+)", config, re.MULTILINE
        ).group(1),
        "app/ha_switchboard/__init__.py": re.search(
            r"^__version__\s*=\s*[\"']([^\"']+)[\"']", package, re.MULTILINE
        ).group(1),
        "app/Dockerfile": re.search(
            r"^ARG BUILD_VERSION=([^\s]+)", dockerfile, re.MULTILINE
        ).group(1),
        "custom_components/ha_switchboard/manifest.json": manifest["version"],
        "pyproject.toml": project["project"]["version"],
    }
    assert len(set(versions.values())) == 1
    version = next(iter(versions.values()))
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)

    changelog = _text("app/CHANGELOG.md")
    assert f"## {version} — source release candidate (not published)" in changelog
    assert "public tag" in changelog

    hacs = json.loads(_text("hacs.json"))
    assert hacs == {
        "name": "HA Switchboard",
        "render_readme": True,
        "zip_release": True,
    }
    repository = _text("repository.yaml")
    assert "name: HA Switchboard" in repository
    assert "url: https://github.com/grayslawson/ha-switchboard" in repository

    for relative in ("README.md", "app/README.md", "docs/RELEASE.md"):
        text = _text(relative).lower()
        assert "release candidate" in text
        assert "not a published" in text


def test_migration_rollback_provenance_and_canary_requirements_are_explicit() -> None:
    release = _text("docs/RELEASE.md")
    contract = _text("specs/001-ha-switchboard-completeness/contracts/release-validation.md")

    for heading in (
        "## Update, migration, and rollback evidence",
        "## Artifact provenance evidence",
        "## Live-canary evidence",
        "## External acceptance dependencies (T150)",
    ):
        assert heading in release

    for phrase in (
        "config entry",
        "profile status",
        "verified Supervisor backup or volume snapshot",
        "matching previous Core artifact",
        "immutable digest",
        "OCI source/revision labels",
        "amd64",
        "arm64",
        "read-only Assist/Conversation result",
        "low-risk exposed-device action",
        "cached Supervisor manifest",
        "T148",
        "T149",
        "T151",
    ):
        assert phrase.lower() in release.lower()

    for phrase in (
        "Update migration and rollback evidence",
        "External dependency review",
        "mutable `latest` tag",
        "without secrets",
        "T148, T149, and T151",
    ):
        assert phrase.lower() in contract.lower()


def test_external_dependency_review_keeps_app_core_provider_boundaries_clear() -> None:
    readme = _text("README.md")
    app_docs = _text("app/DOCS.md")
    public = _text("docs/PUBLIC_REPOSITORY.md")
    release = _text("docs/RELEASE.md")

    for text in (readme, app_docs):
        assert "App" in text and "Core integration" in text
        assert "native" in text.lower() and "Assist" in text
        assert "OpenRouter" in text and "TypeSafe" in text
        assert "local recovery" in text.lower() or "recovery" in text.lower()

    for dependency in ("Supervisor", "HACS", "Hassfest", "GHCR", "OpenRouter", "TypeSafe"):
        assert dependency in release
    assert "pending" in release.lower()
    assert "not proof of public publication" in public.lower() or "not proof" in public.lower()
    assert "custom repository" in readme.lower()


def test_core_translation_uses_hassfest_conversation_agent_shape() -> None:
    translation = json.loads(
        _text("custom_components/ha_switchboard/translations/en.json")
    )
    conversation = translation["conversation"]
    assert set(conversation) == {"agent"}
    assert isinstance(conversation["agent"], dict)
    assert set(conversation["agent"]) == {"done"}
    assert conversation["agent"].get("done")
