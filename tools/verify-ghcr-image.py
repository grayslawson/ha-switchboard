#!/usr/bin/env python3
"""Verify a published GHCR image's manifest, platforms, and source label."""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.parse
import urllib.request
from typing import Any


MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)


class Registry:
    def __init__(self, image: str, username: str, password: str) -> None:
        registry, separator, repository = image.partition("/")
        if not separator or "." not in registry:
            raise ValueError("image must include a registry host")
        self.registry = registry
        self.repository = repository
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        query = urllib.parse.urlencode(
            {
                "service": registry,
                "scope": f"repository:{repository}:pull",
            }
        )
        request = urllib.request.Request(
            f"https://{registry}/token?{query}",
            headers={"Authorization": f"Basic {credentials}"},
        )
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

    def verify(self, tag: str, expected_architectures: set[str], source_url: str, revision: str = "") -> str:
        prefix = f"/v2/{self.repository}"
        index, index_digest = self.json(
            f"{prefix}/manifests/{urllib.parse.quote(tag, safe='')}", MANIFEST_ACCEPT
        )
        manifests = index.get("manifests")
        if not isinstance(manifests, list):
            raise ValueError("published image is not a multi-architecture manifest")

        found: set[str] = set()
        for descriptor in manifests:
            if not isinstance(descriptor, dict):
                continue
            platform = descriptor.get("platform")
            if not isinstance(platform, dict) or platform.get("os") != "linux":
                continue
            architecture = platform.get("architecture")
            digest = descriptor.get("digest")
            if not isinstance(architecture, str) or not isinstance(digest, str):
                continue
            if architecture not in expected_architectures:
                continue
            if architecture in found:
                raise ValueError(f"duplicate linux/{architecture} manifest")
            found.add(architecture)
            child, _ = self.json(f"{prefix}/manifests/{digest}", MANIFEST_ACCEPT)
            config_descriptor = child.get("config")
            if not isinstance(config_descriptor, dict) or not isinstance(
                config_descriptor.get("digest"), str
            ):
                raise ValueError(f"linux/{architecture} manifest has no config")
            config, _ = self.json(
                f"{prefix}/blobs/{config_descriptor['digest']}", "application/json"
            )
            labels = config.get("config", {}).get("Labels", {})
            if not isinstance(labels, dict) or labels.get("org.opencontainers.image.source") != source_url:
                raise ValueError(f"linux/{architecture} image has an unexpected source label")
            if revision and labels.get("org.opencontainers.image.revision") != revision:
                raise ValueError(f"linux/{architecture} image does not match source revision")

        missing = expected_architectures - found
        if missing:
            raise ValueError(f"published image is missing architectures: {sorted(missing)}")
        digest = index_digest or "unknown"
        print(f"GHCR {self.repository}:{tag}: PASS architectures={sorted(found)} digest={digest}")
        return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--revision", default="")
    parser.add_argument("--username-env", default="GHCR_USERNAME")
    parser.add_argument("--token-env", default="GHCR_TOKEN")
    parser.add_argument("--architecture", action="append", default=["amd64", "arm64"])
    args = parser.parse_args()
    username = os.environ.get(args.username_env, "")
    token = os.environ.get(args.token_env, "")
    if not username or not token:
        raise SystemExit("registry username and token environment variables are required")
    Registry(args.image, username, token).verify(
        args.tag, set(args.architecture), args.source_url, args.revision
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
