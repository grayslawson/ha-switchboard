from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".forgejo" / "workflows" / name).read_text(encoding="utf-8")


def test_release_workflows_fetch_full_history_and_gate_master_ancestry() -> None:
    for name in ("build-app.yml", "mirror-public.yml"):
        text = _workflow(name)
        assert "fetch-depth: 0" in text
        assert "refs/heads/master:refs/remotes/origin/master" in text
        assert 'git merge-base --is-ancestor "$tag_commit" "$master_ref"' in text
        assert 'if: ${{ forgejo.ref_type == \'tag\' }}' in text


def test_build_ancestry_gate_precedes_ghcr_login_and_public_tag_gate_precedes_push() -> None:
    build = _workflow("build-app.yml")
    assert build.index("Verify release tag is an ancestor") < build.index("Log in to GitHub Container Registry")
    assert build.index("Verify release source versions are consistent") < build.index("Log in to GitHub Container Registry")
    assert 'test "${ref_name#v}" = "$version"' in build
    assert build.index('test "${ref_name#v}" = "$version"') < build.index("Log in to GitHub Container Registry")

    mirror = _workflow("mirror-public.yml")
    assert mirror.index("Verify release tag is an ancestor") < mirror.index("Push public master")
    assert mirror.index("Verify release source versions are consistent") < mirror.index("Push public master")
    assert mirror.index("Verify release tag is an ancestor") < mirror.index("Create or update GitHub release from tag")
    assert 'test "${ref_name#v}" = "$version"' in mirror


def test_release_version_gate_names_all_source_version_authorities() -> None:
    required = (
        "app/config.yaml",
        "app/ha_switchboard/__init__.py",
        "app/Dockerfile",
        "custom_components/ha_switchboard/manifest.json",
        "pyproject.toml",
    )
    for name in ("build-app.yml", "mirror-public.yml"):
        text = _workflow(name)
        for path in required:
            assert path in text
        assert "release source version mismatch" in text


def test_release_gates_do_not_print_credentials() -> None:
    for name in ("build-app.yml", "mirror-public.yml"):
        text = _workflow(name)
        assert "set -x" not in text
        assert "echo \"$GHCR_TOKEN\"" not in text
        assert "echo \"$GH_MIRROR_TOKEN\"" not in text


def test_release_source_versions_are_consistent() -> None:
    config = (ROOT / "app/config.yaml").read_text(encoding="utf-8")
    package = (ROOT / "app/ha_switchboard/__init__.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "app/Dockerfile").read_text(encoding="utf-8")
    manifest = json.loads(
        (ROOT / "custom_components/ha_switchboard/manifest.json").read_text(encoding="utf-8")
    )
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    versions = {
        "app/config.yaml": re.search(r"^version:\s*[\"']?([^\"'\s]+)", config, re.MULTILINE).group(1),
        "app/ha_switchboard/__init__.py": re.search(
            r"^__version__\s*=\s*[\"']([^\"']+)[\"']", package, re.MULTILINE
        ).group(1),
        "app/Dockerfile": re.search(r"^ARG BUILD_VERSION=([^\s]+)", dockerfile, re.MULTILINE).group(1),
        "custom_components/ha_switchboard/manifest.json": manifest["version"],
        "pyproject.toml": project["project"]["version"],
    }
    assert len(set(versions.values())) == 1
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", next(iter(versions.values())))
