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

    build = _workflow("build-app.yml")
    assert 'test "$source_revision" = "$(git rev-parse \'HEAD^{commit}\')"' in build
    assert 'test "$tag_commit" = "$source_revision"' in build


def test_build_ancestry_gate_precedes_ghcr_login_and_public_tag_gate_precedes_push() -> None:
    build = _workflow("build-app.yml")
    assert build.index("Verify release tag is an ancestor") < build.index("Log in to GitHub Container Registry")
    assert build.index("Verify release source versions are consistent") < build.index("Log in to GitHub Container Registry")
    assert 'test "${ref_name#v}" = "$version"' in build
    assert build.index('test "${ref_name#v}" = "$version"') < build.index("Log in to GitHub Container Registry")
    assert build.index("Run bounded App image E2E before versioned image publication") < build.index(
        "Push versioned multi-architecture image"
    )

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
    for name in ("build-app.yml", "mirror-public.yml", "hacs.yml"):
        text = _workflow(name)
        assert "set -x" not in text
        assert "echo \"$GHCR_TOKEN\"" not in text
        assert "echo \"$GH_MIRROR_TOKEN\"" not in text


def test_ci_and_metadata_workflows_validate_the_public_export() -> None:
    ci = _workflow("ci.yml")
    validation = _workflow("validation.yml")
    hacs = _workflow("hacs.yml")
    mirror = _workflow("mirror-public.yml")
    for text in (ci, validation, hacs, mirror):
        assert "ha-switchboard-export-public.py" in text
        assert 'check_release_boundary.py" --root "$RUNNER_TEMP/public"' in text
        assert 'test ! -e "$RUNNER_TEMP/public/.forgejo"' in text
    assert validation.index("Export and validate public tree") < validation.index("hassfest@sha256")
    assert hacs.index("Export and validate public tree") < hacs.index("hacs/action@sha256")


def test_release_publication_requires_static_and_external_metadata_evidence() -> None:
    mirror = _workflow("mirror-public.yml")
    assert mirror.index("Validate release workflows before publication") < mirror.index("Push public master")
    assert mirror.index("Validate exported Core metadata with Hassfest") < mirror.index("Push public master")
    assert mirror.index("Gate release on matching multi-architecture App image") < mirror.index("Push public master")
    assert mirror.index("Verify public mirror ref") < mirror.index("Validate published Core metadata with HACS")
    assert mirror.index("Validate published Core metadata with HACS") < mirror.index("Create or update GitHub release from tag")
    assert "actionlint -config-file" in mirror
    assert "hassfest@sha256" in mirror
    assert "hacs/action@sha256" in mirror
    assert "sleep 10" in mirror
    assert "for attempt in {1..3}" in mirror


def test_release_workflows_use_exact_source_revision_and_release_paths() -> None:
    build = _workflow("build-app.yml")
    mirror = _workflow("mirror-public.yml")
    assert '--revision "$REVISION"' in build
    assert '--revision "$source_revision"' in mirror
    assert 'test "${ref_name#v}" = "$version"' in build
    assert 'test "${ref_name#v}" = "$version"' in mirror
    assert 'git merge-base --is-ancestor "$tag_commit" "$master_ref"' in mirror
    assert 'test "$tag_commit" = "$source_revision"' in mirror
    assert '--revision "$source_revision"' in mirror
    assert 'test "$(git -C "$RUNNER_TEMP/public" show -s --format=%B HEAD)" = "Mirror Forgejo $source_revision"' in mirror
    assert "push --force github HEAD:master" in mirror


def test_release_gate_dependencies_trigger_the_workflows_that_consume_them() -> None:
    build = _workflow("build-app.yml")
    mirror = _workflow("mirror-public.yml")

    # Every mirror input must also build an image for a tag at that revision;
    # otherwise the mirror can wait for provenance that no build produced.
    for path in (
        ".forgejo/workflows/mirror-public.yml",
        "tests/test_release_boundary.py",
        "tests/test_ghcr_revision_gate.py",
        "tools/check_release_boundary.py",
        "tools/ha-switchboard-scan.py",
        "tools/ha-switchboard-export-public.py",
        "tools/app-image-smoke.sh",
        "tools/app-image-e2e.sh",
        "tools/verify-ghcr-image.py",
    ):
        entry = f'      - "{path}"'
        assert entry in build, path
        assert entry in mirror, path


def test_release_tag_runtime_gate_is_anchored_before_public_tag_push() -> None:
    mirror = _workflow("mirror-public.yml")
    image_gate = mirror.index("Gate release on matching multi-architecture App image")
    e2e_step = mirror.index("- name: Run bounded App image E2E gate before tag publication")
    public_push = mirror.index("- name: Push public master")
    assert image_gate < e2e_step
    assert e2e_step < public_push
    assert mirror.index("timeout --kill-after=10s 300s bash tools/app-image-e2e.sh", e2e_step) < public_push


def test_build_revision_provenance_uses_one_checked_revision_and_bounded_readback() -> None:
    build = _workflow("build-app.yml")
    assert 'source_revision="${GITHUB_SHA:-}"' in build
    assert 'source_revision="${FORGEJO_SHA:-}"' in build
    assert "printf 'revision=%s\\n' \"$source_revision\" >> \"$FORGEJO_OUTPUT\"" in build
    assert '--build-arg "BUILD_REVISION=${REVISION}"' in build
    assert '--revision "$REVISION"' in build
    assert "for attempt in {1..3}; do" in build
    assert "sleep 10" in build


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
