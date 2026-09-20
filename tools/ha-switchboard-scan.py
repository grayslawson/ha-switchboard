#!/usr/bin/env python3
"""Read-only Home Assistant scanner for producing a sanitized profile.

The scanner is adapter-side: it may hold a user-supplied HA token briefly in
memory, compiles the response locally, and emits only the resulting opaque
profile. It has no write method and rejects non-GET requests by construction.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from ha_switchboard.profile import ProfileCompiler  # noqa: E402


class ReadOnlyHomeAssistantClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def get(self, path: str) -> Any:
        if not path.startswith("/") or any(method in path.lower() for method in ("post", "put", "delete", "patch")):
            raise RuntimeError("scanner only supports read-only GET paths")
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read(1_000_000))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("Home Assistant read failed") from exc

    def snapshot(self) -> dict[str, Any]:
        config = self.get("/api/config")
        states = self.get("/api/states")
        services = self.get("/api/services")
        if not isinstance(states, list) or not isinstance(services, list):
            raise RuntimeError("Home Assistant returned an unexpected read response")
        entities = []
        for state in states:
            if not isinstance(state, dict) or not isinstance(state.get("entity_id"), str):
                continue
            entity_id = state["entity_id"]
            domain = entity_id.split(".", 1)[0]
            if domain not in {"light", "switch", "fan", "media_player", "climate"}:
                continue
            entities.append(
                {
                    "entity_id": entity_id,
                    "name": state.get("attributes", {}).get("friendly_name", entity_id),
                    "domain": domain,
                    "available": state.get("state") not in {"unavailable", "unknown"},
                    "exposed": True,
                    "operations": _operations(domain),
                }
            )
        return {
            "installation_key": str(config.get("location_name", "home-assistant")),
            "entities": entities,
            "services": [{"domain": item.get("domain"), "services": sorted(item.get("services", {}))} for item in services if isinstance(item, dict)],
            "assist_surfaces": [],
            "compatibility": [],
            "routines": [],
        }


def _operations(domain: str) -> list[str]:
    return {
        "light": ["turn_on", "turn_off", "toggle", "set_brightness"],
        "switch": ["turn_on", "turn_off", "toggle"],
        "fan": ["turn_on", "turn_off", "toggle"],
        "media_player": ["turn_on", "turn_off", "play", "pause", "stop", "set_volume"],
        "climate": ["set_temperature", "set_hvac_mode"],
    }.get(domain, [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file")
    parser.add_argument("--output", required=True)
    parser.add_argument("--read-only", action="store_true", required=True)
    args = parser.parse_args()
    token = Path(args.token_file).read_text(encoding="utf-8").strip() if args.token_file else os.environ.get("HA_TOKEN", "")
    if not token:
        raise SystemExit("a runtime token file or HA_TOKEN is required")
    profile = ProfileCompiler().compile(ReadOnlyHomeAssistantClient(args.url, token).snapshot())
    Path(args.output).write_text(json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
