"""Small atomic JSON store for App `/data` state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .protocol import HomeProfile
from .redaction import SensitiveDataError, assert_no_secrets


class ProfileStore:
    """Persist only sanitized profile/status data in the App data volume."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.data_dir / "profile.json"
        self.status_path = self.data_dir / "status.json"

    def save_profile(self, profile: HomeProfile) -> None:
        payload = profile.to_dict()
        try:
            assert_no_secrets(payload)
        except SensitiveDataError as exc:
            raise ValueError("refusing to persist sensitive profile data") from exc
        self._atomic_write(self.profile_path, payload)

    def load_profile(self) -> dict[str, Any] | None:
        return self._load(self.profile_path)

    def save_status(self, payload: dict[str, Any]) -> None:
        assert_no_secrets(payload)
        self._atomic_write(self.status_path, payload)

    def load_status(self) -> dict[str, Any] | None:
        return self._load(self.status_path)

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _load(path: Path) -> dict[str, Any] | None:
        try:
            with path.open(encoding="utf-8") as handle:
                value = json.load(handle)
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"stored state {path.name} is not an object")
        return value
