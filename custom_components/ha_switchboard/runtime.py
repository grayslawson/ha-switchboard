"""Runtime data attached to a Home Assistant config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SwitchboardRuntimeData:
    client: Any
    coordinator: Any
    executor: Any
