from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "tools" / "verify-ghcr-image.py"
SPEC = importlib.util.spec_from_file_location("verify_ghcr_image", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _registry_with_labels(revision: str):
    registry = object.__new__(MODULE.Registry)
    registry.repository = "grayslawson/ha-switchboard"

    def fake_json(path: str, _accept: str):
        if path.endswith("/manifests/0.1.3"):
            return (
                {"manifests": [
                    {"platform": {"os": "linux", "architecture": arch}, "digest": f"sha256:{arch}"}
                    for arch in ("amd64", "arm64")
                ]},
                "sha256:index",
            )
        for arch in ("amd64", "arm64"):
            if path.endswith(f"/manifests/sha256:{arch}"):
                return {"config": {"digest": f"sha256:config-{arch}"}}, None
            if path.endswith(f"/blobs/sha256:config-{arch}"):
                return {
                    "config": {
                        "Labels": {
                            "org.opencontainers.image.source": "https://github.com/grayslawson/ha-switchboard",
                            "org.opencontainers.image.revision": revision,
                        }
                    }
                }, None
        raise AssertionError(f"unexpected registry path: {path}")

    registry.json = fake_json
    return registry


def test_release_image_gate_requires_both_platforms_at_exact_revision() -> None:
    registry = _registry_with_labels("forgejo-commit-1")
    assert registry.verify(
        "0.1.3",
        {"amd64", "arm64"},
        "https://github.com/grayslawson/ha-switchboard",
        "forgejo-commit-1",
    ) == "sha256:index"


def test_release_image_gate_rejects_stale_image_revision() -> None:
    registry = _registry_with_labels("older-commit")
    with pytest.raises(ValueError, match="does not match source revision"):
        registry.verify(
            "0.1.3",
            {"amd64", "arm64"},
            "https://github.com/grayslawson/ha-switchboard",
            "forgejo-commit-1",
        )
