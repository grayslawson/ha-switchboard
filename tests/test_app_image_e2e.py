from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "tools" / "app-image-e2e.sh"


def test_image_e2e_harness_is_bounded_and_fail_closed() -> None:
    text = HARNESS.read_text(encoding="utf-8")

    assert HARNESS.stat().st_mode & 0o111
    assert "for _ in {1..5}" in text
    assert "while true" not in text
    assert "cleanup_failed=1" in text
    assert '[[ -e "$DATA_DIR" ]]' in text
    assert 'case "$(basename -- "$ENGINE")"' in text
    assert 'env -i PATH=' in text
    assert "GATEWAY_TOKEN" in text


def test_image_e2e_harness_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(HARNESS)], check=True)
