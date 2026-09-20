from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"
PRODUCT_ROOT = FIXTURES.parent.parent
sys.path.insert(0, str(PRODUCT_ROOT / "app"))
sys.path.insert(0, str(PRODUCT_ROOT))


@pytest.fixture
def discovery() -> dict:
    return json.loads((FIXTURES / "home-assistant-discovery.json").read_text(encoding="utf-8"))


@pytest.fixture
def sanitized_discovery(discovery: dict) -> dict:
    snapshot = copy.deepcopy(discovery)
    for entity in snapshot["entities"]:
        entity["adapter_ref"] = f"fixture-{entity.pop('entity_id').replace('.', '-') }"
    for routine in snapshot["routines"]:
        routine["adapter_ref"] = f"fixture-{routine.pop('entity_id').replace('.', '-') }"
    return snapshot
