"""Install the native fixture package only into the named local HA devcontainer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


CONTAINER = "busy_cohen"
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


def main() -> None:
    details = json.loads(run("docker", "inspect", CONTAINER))[0]
    if details["Name"] != f"/{CONTAINER}" or not details["State"]["Running"]:
        raise SystemExit("The named local devcontainer is not running")
    ports = details["NetworkSettings"]["Ports"]
    if not any(entry.get("HostPort") == "7123" for entry in ports.get("80/tcp") or []):
        raise SystemExit("Refusing to install outside the localhost:7123 devcontainer")

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
