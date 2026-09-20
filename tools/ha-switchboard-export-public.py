#!/usr/bin/env python3
"""Export the allowlisted release surface for the public GitHub mirror.

The private Forgejo repository may contain development-only material in the
future. This exporter intentionally copies tracked files only and refuses
unknown paths instead of guessing whether they are safe to publish.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path, PurePosixPath


ROOT_FILES = frozenset(
    {
        ".dockerignore",
        ".gitignore",
        "LICENSE",
        "README.md",
        "hacs.json",
        "pyproject.toml",
        "repository.yaml",
    }
)
ALLOWED_DIRECTORIES = frozenset(
    {"app", "custom_components", "standalone", "tests"}
)
ALLOWED_FILES = frozenset(
    {
        "docs/RELEASE.md",
        "docs/PUBLIC_REPOSITORY.md",
        "tools/__init__.py",
        "tools/check_release_boundary.py",
        "tools/ha-switchboard-scan.py",
        "tools/ha-switchboard-export-public.py",
        "tools/app-image-smoke.sh",
        "tools/verify-ghcr-image.py",
    }
)
EXCLUDED_DIRECTORIES = frozenset({".devcontainer", ".forgejo", ".github", ".vscode"})
EXCLUDED_FILES = frozenset(
    {
        "docs/PUBLIC_REPOSITORY.md",
        "tools/ha-switchboard-export-public.py",
        "tools/app-image-e2e.sh",
        "tools/local-dev.sh",
        "tests/test_e2e_harness.py",
        "tests/test_release_workflows.py",
    }
)


def tracked_files(root: Path) -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [PurePosixPath(item) for item in result.stdout.decode("utf-8").split("\0") if item]


def is_allowed(path: PurePosixPath) -> bool:
    if str(path) in ROOT_FILES or str(path) in ALLOWED_FILES:
        return True
    return bool(path.parts and path.parts[0] in ALLOWED_DIRECTORIES)


def is_excluded(path: PurePosixPath) -> bool:
    return (
        bool(path.parts and path.parts[0] in EXCLUDED_DIRECTORIES)
        or path.parts[:2] == ("tools", "local-fixtures")
        or str(path) in EXCLUDED_FILES
    )


def export(root: Path, destination: Path) -> list[str]:
    files = tracked_files(root)
    rejected = sorted(
        str(path) for path in files if not is_allowed(path) and not is_excluded(path)
    )
    if rejected:
        return rejected
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"public export destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for relative in files:
        if is_excluded(relative):
            continue
        source = root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"refusing non-regular tracked file: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    destination = args.destination.resolve()
    rejected = export(root, destination)
    if rejected:
        print("public export: FAIL")
        print("unallowlisted tracked paths:")
        print("\n".join(f"- {path}" for path in rejected))
        return 1
    print(f"public export: PASS ({len(tracked_files(root))} tracked files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
