#!/usr/bin/env python3
"""Verify GHCR image provenance, or a supplied read-only provenance record."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)
INDEX_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }
)
IMAGE_MANIFEST_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    }
)
CONFIG_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.config.v1+json",
        "application/vnd.docker.container.image.v1+json",
    }
)
RELEASE_ARCHITECTURES = frozenset({"amd64", "arm64"})
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _required_digest(value: Any, field: str) -> str:
    digest = _required_text(value, field)
    if not SHA256_DIGEST.fullmatch(digest):
        raise ValueError(f"{field} must be an immutable sha256 digest")
    return digest


def _required_media_type(value: Any, allowed: frozenset[str], field: str) -> str:
    media_type = _required_text(value, field)
    if media_type not in allowed:
        raise ValueError(f"{field} is not a supported OCI media type")
    return media_type


def _required_architectures(value: Any, field: str = "architecture set") -> set[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} is required")
    architectures = set(value)
    if len(architectures) != len(value):
        raise ValueError(f"{field} contains duplicates")
    return architectures


def _verify_image_facts(
    *,
    expected_architectures: set[str],
    source_url: str,
    revision: str,
    image_digest: Any,
    platforms: dict[str, dict[str, Any]],
    release_metadata: dict[str, Any] | None = None,
    image_tag: str | None = None,
) -> str:
    if not expected_architectures:
        raise ValueError("at least one architecture is required")
    if not all(
        isinstance(architecture, str) and architecture
        for architecture in expected_architectures
    ):
        raise ValueError("architecture set contains an invalid architecture")
    source_url = _required_text(source_url, "source URL")
    revision = _required_text(revision, "source revision")
    digest = _required_digest(image_digest, "published image digest")

    actual_architectures = set(platforms)
    if actual_architectures != expected_architectures:
        missing = sorted(expected_architectures - actual_architectures)
        unexpected = sorted(actual_architectures - expected_architectures)
        raise ValueError(
            "published architecture set does not match expected set"
            f" (missing={missing}, unexpected={unexpected})"
        )

    for architecture in sorted(expected_architectures):
        details = platforms.get(architecture)
        if not isinstance(details, dict):
            raise ValueError(f"linux/{architecture} image metadata is invalid")
        if details.get("os") != "linux":
            raise ValueError(f"linux/{architecture} descriptor is not a Linux image")
        _required_media_type(
            details.get("descriptor_media_type"),
            IMAGE_MANIFEST_MEDIA_TYPES,
            f"linux/{architecture} descriptor media type",
        )
        _required_digest(details.get("digest"), f"linux/{architecture} manifest digest")
        _required_media_type(
            details.get("config_media_type"),
            CONFIG_MEDIA_TYPES,
            f"linux/{architecture} config media type",
        )
        _required_digest(details.get("config_digest"), f"linux/{architecture} config digest")
        if details.get("source") != source_url:
            raise ValueError(f"linux/{architecture} image has an unexpected source label")
        if details.get("revision") != revision:
            raise ValueError(f"linux/{architecture} image does not match source revision")

    if release_metadata is not None:
        if not isinstance(release_metadata, dict):
            raise ValueError("public release metadata must be an object")
        if image_tag is None:
            raise ValueError("image tag is required for public release metadata")
        release_repository = _required_text(
            release_metadata.get("repository"), "public release repository"
        )
        if release_repository != source_url:
            raise ValueError("public release repository does not match source URL")
        release_tag = _required_text(release_metadata.get("tag"), "public release tag")
        expected_release_tag = f"v{image_tag.removeprefix('v')}"
        if release_tag != expected_release_tag:
            raise ValueError("public release tag does not match image tag")
        if release_metadata.get("target_revision") != revision:
            raise ValueError("public release target revision does not match source revision")
        if release_metadata.get("image_revision") != revision:
            raise ValueError("public release image revision does not match source revision")
        if (
            _required_digest(release_metadata.get("image_digest"), "public release image digest")
            != digest
        ):
            raise ValueError("public release image digest does not match image digest")
        if _required_architectures(
            release_metadata.get("architectures"), "public release architecture set"
        ) != expected_architectures:
            raise ValueError(
                "public release architecture set does not match image architecture set"
            )
        if release_metadata.get("draft") is not False:
            raise ValueError("public release must not be a draft")
        if release_metadata.get("prerelease") is not False:
            raise ValueError("public release must not be a prerelease")
        if release_metadata.get("published") is not True:
            raise ValueError("public release must be published")

    return digest


def verify_provenance_record(record: Any) -> tuple[str, set[str]]:
    """Validate a sanitized, already-collected release record without I/O."""

    if not isinstance(record, dict):
        raise ValueError("provenance record must be an object")
    candidate_revision = _required_text(
        record.get("candidate_revision"), "candidate source revision"
    )
    source_url = _required_text(record.get("source_url"), "candidate source URL")
    expected_architectures = _required_architectures(record.get("expected_architectures"))
    if expected_architectures != RELEASE_ARCHITECTURES:
        raise ValueError("offline release must declare linux/amd64 and linux/arm64")
    image = record.get("image")
    if not isinstance(image, dict):
        raise ValueError("image metadata is required")
    if "public_release" not in record:
        raise ValueError("public release metadata is required")
    image_tag = _required_text(image.get("tag"), "image tag")
    image_digest = _required_digest(image.get("digest"), "published image digest")
    _required_media_type(
        image.get("media_type"), INDEX_MEDIA_TYPES, "published image media type"
    )
    raw_platforms = image.get("platforms")
    if not isinstance(raw_platforms, dict):
        raise ValueError("image platform metadata is required")
    platforms: dict[str, dict[str, Any]] = {}
    for architecture, details in raw_platforms.items():
        if not isinstance(architecture, str) or not isinstance(details, dict):
            raise ValueError("image platform metadata is invalid")
        platforms[architecture] = details
    _verify_image_facts(
        expected_architectures=expected_architectures,
        source_url=source_url,
        revision=candidate_revision,
        image_digest=image_digest,
        platforms=platforms,
        release_metadata=record["public_release"],
        image_tag=image_tag,
    )
    return image_digest, expected_architectures


class Registry:
    def __init__(self, image: str, username: str = "", password: str = "") -> None:
        registry, separator, repository = image.partition("/")
        if not separator or "." not in registry:
            raise ValueError("image must include a registry host")
        self.registry = registry
        self.repository = repository
        if bool(username) != bool(password):
            raise ValueError("registry username and token must be provided together")
        headers: dict[str, str] = {}
        if username and password:
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        query = urllib.parse.urlencode(
            {
                "service": registry,
                "scope": f"repository:{repository}:pull",
            }
        )
        request = urllib.request.Request(f"https://{registry}/token?{query}", headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        token = payload.get("token") or payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("registry token response did not contain a token")
        self.token = token

    def json(self, path: str, accept: str) -> tuple[dict[str, Any], str | None]:
        request = urllib.request.Request(
            f"https://{self.registry}{path}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": accept},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError(f"registry response was not an object: {path}")
        return payload, response.headers.get("Docker-Content-Digest")

    def verify(
        self, tag: str, expected_architectures: set[str], source_url: str, revision: str = ""
    ) -> str:
        if not expected_architectures:
            raise ValueError("at least one architecture is required")
        if not source_url:
            raise ValueError("source URL is required")
        if not revision:
            raise ValueError("source revision is required")
        prefix = f"/v2/{self.repository}"
        index, index_digest = self.json(
            f"{prefix}/manifests/{urllib.parse.quote(tag, safe='')}", MANIFEST_ACCEPT
        )
        _required_media_type(
            index.get("mediaType"), INDEX_MEDIA_TYPES, "published image media type"
        )
        manifests = index.get("manifests")
        if not isinstance(manifests, list):
            raise ValueError("published image is not a multi-architecture manifest")

        platforms: dict[str, dict[str, Any]] = {}
        for descriptor in manifests:
            if not isinstance(descriptor, dict):
                continue
            platform = descriptor.get("platform")
            if not isinstance(platform, dict) or platform.get("os") != "linux":
                continue
            architecture = platform.get("architecture")
            digest = descriptor.get("digest")
            if not isinstance(architecture, str) or not architecture:
                raise ValueError("linux manifest has no architecture")
            if architecture in platforms:
                raise ValueError(f"duplicate linux/{architecture} manifest")
            manifest_digest = _required_digest(digest, f"linux/{architecture} manifest digest")
            child, child_digest = self.json(
                f"{prefix}/manifests/{manifest_digest}", MANIFEST_ACCEPT
            )
            if child_digest != manifest_digest:
                raise ValueError(f"linux/{architecture} manifest digest does not match descriptor")
            descriptor_media_type = child.get("mediaType")
            _required_media_type(
                descriptor_media_type,
                IMAGE_MANIFEST_MEDIA_TYPES,
                f"linux/{architecture} manifest media type",
            )
            config_descriptor = child.get("config")
            if not isinstance(config_descriptor, dict) or not isinstance(
                config_descriptor.get("digest"), str
            ):
                raise ValueError(f"linux/{architecture} manifest has no config")
            config_media_type = config_descriptor.get("mediaType")
            _required_media_type(
                config_media_type,
                CONFIG_MEDIA_TYPES,
                f"linux/{architecture} config media type",
            )
            config_digest = _required_digest(
                config_descriptor["digest"], f"linux/{architecture} config digest"
            )
            config, config_response_digest = self.json(
                f"{prefix}/blobs/{config_digest}", "application/json"
            )
            if config_response_digest != config_digest:
                raise ValueError(f"linux/{architecture} config digest does not match descriptor")
            config_metadata = config.get("config")
            if not isinstance(config_metadata, dict):
                raise ValueError(f"linux/{architecture} image has no OCI config metadata")
            labels = config_metadata.get("Labels", {})
            if not isinstance(labels, dict):
                raise ValueError(f"linux/{architecture} image has no OCI labels")
            platforms[architecture] = {
                "os": "linux",
                "descriptor_media_type": descriptor_media_type,
                "digest": manifest_digest,
                "config_media_type": config_media_type,
                "config_digest": config_digest,
                "source": labels.get("org.opencontainers.image.source"),
                "revision": labels.get("org.opencontainers.image.revision"),
            }

        digest = _verify_image_facts(
            expected_architectures=expected_architectures,
            source_url=source_url,
            revision=revision,
            image_digest=index_digest,
            platforms=platforms,
        )
        print(
            f"GHCR {self.repository}:{tag}: PASS architectures={sorted(platforms)} digest={digest}"
        )
        return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--provenance-file",
        type=Path,
        help="validate a sanitized local read-only provenance JSON record; no network access",
    )
    source.add_argument("--image", help="explicit read-only registry image reference")
    parser.add_argument("--tag")
    parser.add_argument("--source-url")
    parser.add_argument("--revision")
    parser.add_argument("--username-env", default="GHCR_USERNAME")
    parser.add_argument("--token-env", default="GHCR_TOKEN")
    parser.add_argument("--architecture", action="append", dest="architectures")
    args = parser.parse_args()
    if args.provenance_file is not None:
        try:
            with args.provenance_file.open(encoding="utf-8") as handle:
                record = json.load(handle)
        except OSError as error:
            raise SystemExit(f"could not read provenance file: {error}") from error
        except json.JSONDecodeError as error:
            raise SystemExit(f"provenance file is not valid JSON: {error.msg}") from error
        digest, architectures = verify_provenance_record(record)
        print(f"offline provenance PASS architectures={sorted(architectures)} digest={digest}")
        return 0

    if not args.tag or not args.source_url or not args.revision:
        parser.error("--image requires --tag, --source-url, and --revision")
    username = os.environ.get(args.username_env, "")
    token = os.environ.get(args.token_env, "")
    architectures = set(args.architectures or ("amd64", "arm64"))
    Registry(args.image, username, token).verify(
        args.tag, architectures, args.source_url, args.revision
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
