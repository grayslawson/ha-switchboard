"""Install the native fixture package only into the named local HA devcontainer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


CONTAINER = "busy_cohen"
LOCAL_PORT = "7123"
DESTINATION = "/mnt/supervisor/homeassistant/switchboard_fixture.yaml"
MARKER = "# HA Switchboard local fixture package"
INCLUDE = (
    f"\n{MARKER}\n"
    "homeassistant:\n"
    "  packages:\n"
    "    switchboard_fixture: !include switchboard_fixture.yaml\n"
)


def run(*arguments: str) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"Local fixture command failed ({arguments[0]}, exit {result.returncode})")
    return result.stdout


def validate_local_container(details: dict) -> None:
    """Fail closed unless Docker describes the disposable local Core fixture."""
    if details.get("Name") != f"/{CONTAINER}" or not details.get("State", {}).get("Running"):
        raise SystemExit("Refusing fixture install: busy_cohen is not the running local container")
    ports = details.get("NetworkSettings", {}).get("Ports", {})
    published = {
        entry.get("HostPort")
        for entry in ports.get("80/tcp") or []
        if isinstance(entry, dict)
    }
    if LOCAL_PORT not in published:
        raise SystemExit("Refusing fixture install outside localhost:7123")


def main() -> None:
    details = json.loads(run("docker", "inspect", CONTAINER))[0]
    validate_local_container(details)

    fixture = Path(__file__).with_name("switchboard.yaml")
    run("docker", "cp", str(fixture), f"{CONTAINER}:{DESTINATION}")
    edit = f"""
from pathlib import Path
path = Path('/config/configuration.yaml')
original = path.read_text()
marker = {MARKER!r}
include = {INCLUDE!r}
if marker not in original:
    if '\\nhomeassistant:' in '\\n' + original:
        raise SystemExit('Existing homeassistant section needs manual merge')
    path.write_text(original.rstrip() + '\\n' + include)
elif include not in original:
    raise SystemExit('Fixture marker differs; refusing to overwrite local configuration')
"""
    run("docker", "exec", CONTAINER, "docker", "exec", "homeassistant", "python3", "-c", edit)
    check = json.loads(run("docker", "exec", CONTAINER, "ha", "core", "check", "--raw-json"))
    if check.get("result") != "ok":
        raise SystemExit("Local Core rejected fixture configuration")
    print("Local fixture package installed and Core configuration validated.")
    print("Restart local Core with: docker exec busy_cohen ha core restart")


if __name__ == "__main__":
    main()
