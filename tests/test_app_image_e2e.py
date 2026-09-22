from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "tools" / "app-image-e2e.sh"
MIRROR_WORKFLOW = ROOT / ".forgejo" / "workflows" / "mirror-public.yml"


def test_image_e2e_harness_is_bounded_and_fail_closed() -> None:
    text = HARNESS.read_text(encoding="utf-8")

    assert HARNESS.stat().st_mode & 0o111
    assert "for _ in {1..5}" in text
    assert "timeout=3" in text
    assert "sleep 0.5" in text
    assert "while true" not in text
    assert "cleanup_failed=1" in text
    assert '[[ -e "$DATA_DIR" ]]' in text
    assert 'ENGINE_NAME="$(basename -- "$ENGINE")"' in text
    assert 'env -i PATH=' in text
    assert "GATEWAY_TOKEN" in text
    assert 'command -v timeout' in text
    assert '--kill-after=5s' in text
    assert 'CONTAINER_ATTEMPTED=true' in text
    assert 'NETWORK_ATTEMPTED=true' in text
    assert 'image rm --force "$IMAGE"' in text
    assert 'HOOK_TIMEOUT_SECONDS=60' in text
    assert 'run_bounded "${HOOK_TIMEOUT_SECONDS}s"' in text


def test_apparmor_option_is_fail_closed_and_does_not_claim_unverified_enforcement() -> None:
    text = HARNESS.read_text(encoding="utf-8")

    assert '"$APPARMOR_PROFILE"' in text
    assert "/sys/module/apparmor/parameters/enabled" in text
    assert "/sys/kernel/security/apparmor/profiles" in text
    assert "profile is not loaded" in text
    assert "profile loaded and attached" in text
    assert "AppArmor enforcement: not requested (host support detected)" in text
    assert "AppArmor enforcement: unavailable (not requested)" in text
    assert "AppArmor enforcement: ${APPARMOR_PROFILE}" not in text


def test_mirror_release_probe_is_bounded_without_changing_outer_e2e_timeout() -> None:
    text = MIRROR_WORKFLOW.read_text(encoding="utf-8")
    probe_start = text.index("Gate release on matching multi-architecture App image")
    e2e_start = text.index("Run bounded App image E2E gate before tag publication")
    probe = text[probe_start:e2e_start]

    assert "for attempt in {1..12}; do" in probe
    assert "for attempt in {1..18}; do" not in probe
    assert 'if [ "$attempt" -eq 12 ]; then' in probe
    assert "matching App image was not published within 120 seconds" in probe
    assert "sleep 10" in probe
    assert "timeout --kill-after=10s 300s bash tools/app-image-e2e.sh" in text


def test_image_e2e_harness_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(HARNESS)], check=True)
