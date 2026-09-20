from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "tools" / "app-image-e2e.sh"
WORKFLOW = ROOT / ".forgejo" / "workflows" / "build-app.yml"


def test_local_e2e_harness_is_source_build_and_secret_free() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert HARNESS.stat().st_mode & 0o111
    assert '"$ROOT_DIR/app"' in text
    assert "localhost/ha-switchboard-local" in text
    assert "ghcr.io/grayslawson/ha-switchboard" not in text
    assert '--build-arg "BUILD_ARCH=${HA_ARCH}"' in text
    assert "HA_SWITCHBOARD_E2E_DISCOVERY_HOOK=1" in text
    assert "env -i" in text
    assert "/healthz" in text and "/readyz" in text
    assert "172.30.32.2" in text
    assert '172.30.32.3:8099 "$path"' in text
    assert 'if [[ "$ENGINE" == podman ]]; then' in text
    assert "65532:65532" in text
    assert "apparmor" in text


def test_release_workflow_maps_docker_arm64_to_home_assistant_aarch64() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "for arch in amd64 arm64; do" in text
    assert "hass_arch=aarch64" in text
    assert '--build-arg "BUILD_ARCH=${hass_arch}"' in text
