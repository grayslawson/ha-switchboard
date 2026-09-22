from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
SMOKE = ROOT / "tools" / "standalone-smoke.sh"


def test_standalone_smoke_is_executable_and_bounded() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    assert SMOKE.stat().st_mode & stat.S_IXUSR
    assert "set -Eeuo pipefail" in text
    assert "env -i" in text
    assert "--kill-after=2s" in text
    assert "config --format json" in text
    assert "docker compose" in text
    assert "podman compose" in text
    assert "docker compose up" not in text
    assert "docker compose pull" not in text


def test_standalone_smoke_validates_rendered_model_without_credentials(tmp_path: Path) -> None:
    fake_compose = tmp_path / "compose"
    observed = tmp_path / "observed.json"
    model = {
        "services": {
            "ha-switchboard": {
                "ports": [{"host_ip": "127.0.0.1", "published": 18099, "target": 8099}],
                "read_only": True,
                "tmpfs": ["/tmp:rw,noexec,nosuid,nodev"],
                "volumes": [{"type": "bind", "source": str(tmp_path / "data"), "target": "/data"}],
                "healthcheck": {
                    "test": ["CMD", "python3", "healthz"],
                    "interval": "30s",
                    "timeout": "5s",
                    "retries": 3,
                },
                "environment": {
                    "HA_SWITCHBOARD_INGRESS_ONLY": "false",
                    "JEV_API_KEY": "",
                    "FALLBACK_API_KEY": "",
                    "GATEWAY_TOKEN": "",
                    "JEV_ENDPOINT": "",
                    "JEV_BASE_URL": "",
                    "FALLBACK_BASE_URL": "",
                    "FALLBACK_ENDPOINT": "",
                },
            }
        }
    }
    fake_compose.write_text(
        "#!/bin/sh\n"
        f"env | sort > {observed}\n"
        "printf '%s' '" + json.dumps(model).replace("'", "'\\''") + "'\n",
        encoding="utf-8",
    )
    fake_compose.chmod(0o755)

    result = subprocess.run(
        [str(SMOKE)],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], "COMPOSE_BIN": str(fake_compose)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "secret-free wiring OK" in result.stdout
    observed_text = observed.read_text(encoding="utf-8")
    assert "GATEWAY_TOKEN=" in observed_text
    assert "JEV_API_KEY=" in observed_text
    assert "FALLBACK_API_KEY=" in observed_text
    assert "DOCKER_AUTH_CONFIG" not in observed_text
