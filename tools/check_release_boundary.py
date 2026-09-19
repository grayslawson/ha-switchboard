#!/usr/bin/env python3
"""Reject operator-specific or privileged dependencies from release artifacts."""

from __future__ import annotations

import argparse
import ipaddress
import re
from pathlib import Path


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".sh", ".txt", ".md", ".toml", ".env"}

FORBIDDEN_TERMS = (
    "pd-nixos",
    "possumden",
    "kilocli",
    "kilo/",
    "sops",
    "/home/deploy",
    "/etc/nixos",
    "secrets/homelab",
    "local-fast",
)
PRIVATE_IP = re.compile(r"(?<![\d.])(?:10|192\.168|172\.(?:1[6-9]|2\d|3[0-1]))\.\d{1,3}\.\d{1,3}(?![\d.])")
ALLOWED_PLATFORM_ADDRESSES = frozenset({"172.30.32.2"})
FORBIDDEN_IMPORT = re.compile(r"(?:from|import)\s+pd[_-]nixos")


def _is_private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_private and not address.is_loopback


def violations(root: Path = PRODUCT_ROOT) -> list[str]:
    findings: list[str] = []
    release_dirs = tuple(root / name for name in ("app", "custom_components", "standalone"))
    for directory in release_dirs:
        if not directory.exists():
            findings.append(f"missing release directory: {directory.relative_to(root)}")
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append(f"non-UTF8 release file: {path.relative_to(root)}")
                continue
            lowered = text.lower()
            for term in FORBIDDEN_TERMS:
                if term in lowered:
                    findings.append(f"{path.relative_to(root)} contains forbidden term {term!r}")
            if FORBIDDEN_IMPORT.search(text):
                findings.append(f"{path.relative_to(root)} imports pd-nixos")
            for match in PRIVATE_IP.finditer(text):
                if _is_private_ip(match.group(0)) and match.group(0) not in ALLOWED_PLATFORM_ADDRESSES:
                    findings.append(f"{path.relative_to(root)} contains private address {match.group(0)!r}")
            if ".sops." in lowered or "decrypted" in lowered:
                findings.append(f"{path.relative_to(root)} references encrypted/decrypted secret material")
            if "custom_components" in path.parts and re.search(r"(?:copy|cp|shutil\.copy).*(?:custom_components|config_dir)", lowered):
                findings.append(f"{path.relative_to(root)} attempts automatic integration installation")
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PRODUCT_ROOT)
    args = parser.parse_args()
    findings = violations(args.root.resolve())
    if findings:
        print("release boundary: FAIL")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1
    print("release boundary: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
