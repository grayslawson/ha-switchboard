from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "tools" / "verify-ghcr-image.py"
SPEC = importlib.util.spec_from_file_location("verify_ghcr_image", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


SOURCE_URL = "https://github.com/grayslawson/ha-switchboard"
IMAGE_DIGEST = "sha256:" + "0" * 64
PLATFORM_DIGESTS = {
    "amd64": "sha256:" + "1" * 64,
    "arm64": "sha256:" + "2" * 64,
}
CONFIG_DIGESTS = {
    "amd64": "sha256:" + "3" * 64,
    "arm64": "sha256:" + "4" * 64,
}


def _registry_with_labels(
    revision: str,
    *,
    config_metadata=None,
    index_digest=IMAGE_DIGEST,
    child_digest=...,
    config_response_digest=...,
):
    registry = object.__new__(MODULE.Registry)
    registry.repository = "grayslawson/ha-switchboard"

    def fake_json(path: str, _accept: str):
        if path.endswith("/manifests/0.1.3"):
            return (
                {"manifests": [
                    {
                        "platform": {"os": "linux", "architecture": arch},
                        "digest": PLATFORM_DIGESTS[arch],
                    }
                    for arch in ("amd64", "arm64")
                ]},
                index_digest,
            )
        for arch in ("amd64", "arm64"):
            if path.endswith(f"/manifests/{PLATFORM_DIGESTS[arch]}"):
                response_digest = PLATFORM_DIGESTS[arch] if child_digest is ... else child_digest
                return {"config": {"digest": CONFIG_DIGESTS[arch]}}, response_digest
            if path.endswith(f"/blobs/{CONFIG_DIGESTS[arch]}"):
                if config_metadata is not None:
                    response_digest = CONFIG_DIGESTS[arch] if config_response_digest is ... else config_response_digest
                    return config_metadata, response_digest
                response_digest = CONFIG_DIGESTS[arch] if config_response_digest is ... else config_response_digest
                return {
                    "config": {
                        "Labels": {
                            "org.opencontainers.image.source": SOURCE_URL,
                            "org.opencontainers.image.revision": revision,
                        }
                    }
                }, response_digest
        raise AssertionError(f"unexpected registry path: {path}")

    registry.json = fake_json
    return registry


def test_release_image_gate_requires_both_platforms_at_exact_revision() -> None:
    registry = _registry_with_labels("forgejo-commit-1")
    assert registry.verify(
        "0.1.3",
        {"amd64", "arm64"},
        SOURCE_URL,
        "forgejo-commit-1",
    ) == IMAGE_DIGEST


def test_release_image_gate_rejects_stale_image_revision() -> None:
    registry = _registry_with_labels("older-commit")
    with pytest.raises(ValueError, match="does not match source revision"):
        registry.verify(
            "0.1.3",
            {"amd64", "arm64"},
            SOURCE_URL,
            "forgejo-commit-1",
        )


def test_release_image_gate_requires_revision_and_architecture() -> None:
    registry = _registry_with_labels("forgejo-commit-1")
    with pytest.raises(ValueError, match="source revision is required"):
        registry.verify("0.1.3", {"amd64", "arm64"}, SOURCE_URL)
    with pytest.raises(ValueError, match="at least one architecture"):
        registry.verify("0.1.3", set(), SOURCE_URL, "forgejo-commit-1")


def test_release_image_gate_rejects_malformed_oci_config_metadata() -> None:
    registry = _registry_with_labels("forgejo-commit-1", config_metadata={"config": []})
    with pytest.raises(ValueError, match="no OCI config metadata"):
        registry.verify(
            "0.1.3",
            {"amd64", "arm64"},
            SOURCE_URL,
            "forgejo-commit-1",
        )


def test_release_image_gate_rejects_missing_immutable_index_digest() -> None:
    registry = _registry_with_labels("forgejo-commit-1", index_digest=None)
    with pytest.raises(ValueError, match="published image digest"):
        registry.verify(
            "0.1.3",
            {"amd64", "arm64"},
            SOURCE_URL,
            "forgejo-commit-1",
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"child_digest": None}, "manifest digest does not match descriptor"),
        ({"child_digest": IMAGE_DIGEST}, "manifest digest does not match descriptor"),
        ({"config_response_digest": None}, "config digest does not match descriptor"),
        ({"config_response_digest": IMAGE_DIGEST}, "config digest does not match descriptor"),
    ],
)
def test_release_image_gate_rejects_missing_or_mismatched_child_digests(kwargs, message) -> None:
    registry = _registry_with_labels("forgejo-commit-1", **kwargs)
    with pytest.raises(ValueError, match=message):
        registry.verify(
            "0.1.3",
            {"amd64", "arm64"},
            SOURCE_URL,
            "forgejo-commit-1",
        )


def _provenance_record() -> dict:
    revision = "forgejo-commit-1"
    return {
        "candidate_revision": revision,
        "source_url": SOURCE_URL,
        "expected_architectures": ["amd64", "arm64"],
        "image": {
            "tag": "0.2.0",
            "digest": IMAGE_DIGEST,
            "platforms": {
                arch: {
                    "digest": PLATFORM_DIGESTS[arch],
                    "source": SOURCE_URL,
                    "revision": revision,
                }
                for arch in ("amd64", "arm64")
            },
        },
        "public_release": {
            "repository": SOURCE_URL,
            "tag": "v0.2.0",
            "target_revision": revision,
            "image_revision": revision,
            "image_digest": IMAGE_DIGEST,
            "architectures": ["amd64", "arm64"],
            "draft": False,
            "prerelease": False,
            "published": True,
        },
    }


def test_offline_provenance_file_needs_no_credentials_or_network(
    tmp_path, monkeypatch, capsys
) -> None:
    record_path = tmp_path / "provenance.json"
    record_path.write_text(json.dumps(_provenance_record()), encoding="utf-8")

    def fail_if_contacted(*_args, **_kwargs):
        raise AssertionError("offline provenance validation contacted a remote")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fail_if_contacted)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--provenance-file", str(record_path)])

    assert MODULE.main() == 0
    assert "offline provenance PASS" in capsys.readouterr().out


def _mutate_digest(record: dict) -> None:
    record["public_release"].update(image_digest="sha256:" + "f" * 64)


def _mutate_revision(record: dict) -> None:
    record["public_release"].update(target_revision="stale")


def _mutate_architecture(record: dict) -> None:
    record["image"]["platforms"].update(
        {
            "s390x": {
                "digest": PLATFORM_DIGESTS["amd64"],
                "source": SOURCE_URL,
                "revision": "forgejo-commit-1",
            }
        }
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_mutate_digest, "public release image digest"),
        (_mutate_revision, "public release target revision"),
        (_mutate_architecture, "architecture set"),
    ],
)
def test_offline_provenance_file_fails_closed_on_mismatch(mutate, message) -> None:
    record = _provenance_record()
    mutate(record)
    with pytest.raises(ValueError, match=message):
        MODULE.verify_provenance_record(record)


def test_offline_provenance_file_requires_public_release_metadata() -> None:
    record = _provenance_record()
    del record["public_release"]
    with pytest.raises(ValueError, match="public release metadata is required"):
        MODULE.verify_provenance_record(record)
