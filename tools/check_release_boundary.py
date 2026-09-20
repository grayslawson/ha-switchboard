#!/usr/bin/env python3
"""Reject operator-specific or privileged dependencies from release artifacts."""

from __future__ import annotations

import argparse
import ast
import ipaddress
import re
from pathlib import Path


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".sh", ".txt", ".md", ".toml", ".env"}

FORBIDDEN_TERMS = (
    "operator-nixos",
    "operator-private",
    "kilocli",
    "kilo/",
    "sops",
    "/home/deploy",
    "/etc/nixos",
    "secrets/private",
    "operator-network",
    "local-fast",
)
PRIVATE_IP = re.compile(r"(?<![\d.])(?:10|192\.168|172\.(?:1[6-9]|2\d|3[0-1]))\.\d{1,3}\.\d{1,3}(?![\d.])")
ALLOWED_PLATFORM_ADDRESSES = frozenset({"172.30.32.2"})
FORBIDDEN_IMPORT = re.compile(r"(?:from|import)\s+operator[_-]nixos")

# These checks deliberately operate on source, not tests, fixtures, generated
# metadata, or documentation examples.  The Core integration is the one place
# where raw Home Assistant references are expected: it resolves opaque adapter
# references back to HA-local IDs before calling Home Assistant.
_QUALITY_SUFFIXES = {".py", ".sh", ".yaml", ".yml", ".json", ".toml"}
_QUALITY_ROOTS = ("app", "custom_components", "tools", "standalone")
_SKIP_PARTS = frozenset({".git", ".pytest_cache", "__pycache__", "generated", "fixtures", "local-fixtures"})
_RAW_REFERENCE_KEYS = ("entity_id", "device_id", "area_id", "unique_id", "config_entry_id")
_BOUNDARY_MODULES = frozenset(
    {
        "app/ha_switchboard/profile.py",
        "app/ha_switchboard/redaction.py",
        "custom_components/ha_switchboard/conversation.py",
        "custom_components/ha_switchboard/profile_adapter.py",
        "custom_components/ha_switchboard/read_only.py",
        "custom_components/ha_switchboard/opaque.py",
    }
)
_INTENTIONAL_BROAD_EXCEPTIONS = frozenset(
    {
        "custom_components/ha_switchboard/__init__.py:async_setup_entry",
        "custom_components/ha_switchboard/coordinator.py:_recovery_tick",
        "custom_components/ha_switchboard/coordinator.py:_periodic_refresh",
        "custom_components/ha_switchboard/coordinator.py:_refresh_app_options",
        "custom_components/ha_switchboard/coordinator.py:async_reconcile",
        "custom_components/ha_switchboard/coordinator.py:async_scan",
        "custom_components/ha_switchboard/coordinator.py:run",
        "custom_components/ha_switchboard/coordinator.py:async_handle_event",
        "custom_components/ha_switchboard/coordinator.py:_flush_events",
        "custom_components/ha_switchboard/execution.py:execute_batch_proposal",
        "custom_components/ha_switchboard/execution.py:execute_proposal",
        "app/ha_switchboard/gateway.py:process",
        "app/ha_switchboard/server.py:do_POST",
    }
)
_INTENTIONAL_LIFECYCLE_LOOPS = frozenset(
    {
        "custom_components/ha_switchboard/coordinator.py:_recovery_loop",
        "custom_components/ha_switchboard/coordinator.py:_periodic_loop",
    }
)
_PLACEHOLDER = re.compile(
    r"(?:\b(?:todo|fixme|xxx|changeme|replace[-_ ]?me)\b|"
    r"\b(?:your|replace[-_ ]?with)[-_ ](?:token|api[-_ ]?key|password|secret)\b|"
    r"\bexample[-_ ]?(?:token|api[-_ ]?key|password|secret)\b)",
    re.IGNORECASE,
)
_PROHIBITED_RESPONSE = re.compile(
    r"i\s+could\s+not\s+safely\s+complete\s+that\s+request\s*\.?", re.IGNORECASE
)
_SECRET_LOG = re.compile(
    r"(?:\b(?:print|pprint)\s*\(|\b(?:log|logger|_log|_LOG)\s*\.\w+\s*\()"
    r"[^\n]*(?:token|api[_ -]?key|password|secret|authorization|bearer)",
    re.IGNORECASE,
)
_DOC_LINK = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")


def _bounded_tool_violations(root: Path) -> list[str]:
    """Reject local harnesses that can wait forever on external processes."""

    findings: list[str] = []
    scripts = (
        root / "tools" / "app-image-e2e.sh",
        root / "tools" / "app-image-smoke.sh",
        root / "tools" / "local-dev.sh",
    )
    for path in scripts:
        if not path.exists():
            continue
        relative = _relative(path, root)
        text = path.read_text(encoding="utf-8")
        if "run_bounded()" not in text or "--kill-after=5s" not in text:
            findings.append(f"{relative}: external operations are not fail-closed bounded")
        if relative == "tools/app-image-smoke.sh" and "else\n    \"$@\"" in text:
            findings.append(f"{relative}: timeout fallback runs an unbounded command")
        if relative == "tools/local-dev.sh":
            required = (
                "run_bounded \"$DEVCONTAINER_TIMEOUT_SECONDS\"",
                "run_bounded \"$DOCKER_TIMEOUT_SECONDS\" docker",
                "run_bounded \"$DEVCONTAINER_TIMEOUT_SECONDS\" rsync",
                "run_in_container_foreground",
            )
            for marker in required:
                if marker not in text:
                    findings.append(f"{relative}: missing bounded subprocess boundary {marker!r}")
    return findings


def _quality_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for name in _QUALITY_ROOTS:
        directory = root / name
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in _QUALITY_SUFFIXES and not (_SKIP_PARTS & set(path.parts)):
                files.append(path)
    return sorted(files)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _function_name(tree: ast.AST, node: ast.AST) -> str:
    parents: list[str] = []
    # The audit only needs the nearest function; nested callbacks are still
    # reported against their containing function when possible.
    for candidate in ast.walk(tree):
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)) and node in ast.walk(candidate):
            parents.append(candidate.name)
    return parents[-1] if parents else "<module>"


def _option_keys(config: str, section: str) -> set[str]:
    match = re.search(rf"^{section}:\s*$((?:\n^[ ]{{2,}}[^\n]+)*)", config, re.MULTILINE)
    if not match:
        return set()
    return {
        line.strip().split(":", 1)[0]
        for line in match.group(1).splitlines()
        if line.strip() and not line.lstrip().startswith("#") and ":" in line
    }


def quality_violations(root: Path = PRODUCT_ROOT) -> list[str]:
    """Return conservative, sanitized static quality findings.

    This is intentionally a finding API rather than a test-only assertion so
    CI and release tooling can consume the same fail-closed result.
    """

    root = root.resolve()
    findings: list[str] = []
    findings.extend(_bounded_tool_violations(root))
    source_files = _quality_files(root)
    parsed: list[tuple[Path, str, ast.AST]] = []
    for path in source_files:
        relative = _relative(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{relative}: non-UTF8 source")
            continue
        if path.suffix == ".py":
            try:
                tree = ast.parse(text, filename=relative)
            except SyntaxError as exc:
                findings.append(f"{relative}:{exc.lineno}: syntax error")
                continue
            parsed.append((path, relative, tree))
        if _PLACEHOLDER.search(text) and relative != "tools/check_release_boundary.py" and not relative.endswith("/config.yaml"):
            findings.append(f"{relative}: placeholder marker")
        if relative.startswith("app/") or relative.startswith("custom_components/"):
            if _PROHIBITED_RESPONSE.search(text):
                findings.append(f"{relative}: prohibited generic response language")
            if _SECRET_LOG.search(text):
                findings.append(f"{relative}: possible secret in log/print expression")
        if relative in {item for item in _BOUNDARY_MODULES}:
            continue
        if relative.startswith("app/ha_switchboard/") and any(
            re.search(rf"[\"']{re.escape(key)}[\"']", text) for key in _RAW_REFERENCE_KEYS
        ):
            findings.append(f"{relative}: raw Home Assistant ID crosses the gateway boundary")

    for path, relative, tree in parsed:
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                broad = node.type is None or (
                    isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
                )
                identity = f"{relative}:{_function_name(tree, node)}"
                if broad and identity not in _INTENTIONAL_BROAD_EXCEPTIONS:
                    findings.append(f"{relative}:{node.lineno}: broad exception handler")
            if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True:
                identity = f"{relative}:{_function_name(tree, node)}"
                if identity not in _INTENTIONAL_LIFECYCLE_LOOPS:
                    findings.append(f"{relative}:{node.lineno}: unbounded loop")

    config_path = root / "app" / "config.yaml"
    if config_path.exists():
        config = config_path.read_text(encoding="utf-8")
        options = _option_keys(config, "options")
        schema = _option_keys(config, "schema")
        if missing := sorted(options - schema):
            findings.append(f"app/config.yaml: options missing schema entries: {', '.join(missing)}")
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in source_files
            if _relative(path, root).startswith("app/ha_switchboard/")
            or _relative(path, root) == "app/run.sh"
        )
        for key in sorted(options):
            if not re.search(rf"\b{re.escape(key)}\b", runtime_text):
                findings.append(f"app/config.yaml: option {key!r} is not referenced by App runtime")
        docs = "\n".join(
            (root / name).read_text(encoding="utf-8")
            for name in ("README.md", "app/DOCS.md")
            if (root / name).exists()
        )
        for key in sorted(schema):
            if key not in docs:
                findings.append(f"app/config.yaml: option {key!r} is undocumented")
        required_docs = ("README.md", "app/DOCS.md", "docs/RELEASE.md")
        if (root / ".forgejo").exists():
            required_docs += ("docs/PUBLIC_REPOSITORY.md",)
        for name in required_docs:
            if not (root / name).exists():
                findings.append(f"documentation drift: missing {name}")
    for path in (root / "README.md", root / "app/DOCS.md"):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for target in _DOC_LINK.findall(text):
            if target.startswith(("http://", "https://", "#")):
                continue
            if not (path.parent / target).exists() and not (root / target).exists():
                findings.append(f"{_relative(path, root)}: broken documentation link {target!r}")
    return sorted(set(findings))


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
                findings.append(f"{path.relative_to(root)} imports operator-nixos")
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
    parser.add_argument("--quality", action="store_true", help="run the static quality audit")
    args = parser.parse_args()
    findings = quality_violations(args.root.resolve()) if args.quality else violations(args.root.resolve())
    if findings:
        print("quality audit: FAIL" if args.quality else "release boundary: FAIL")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1
    print("quality audit: PASS" if args.quality else "release boundary: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
