"""Small atomic JSON store for App `/data` state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .protocol import HomeProfile
from .redaction import SensitiveDataError, assert_no_secrets

MAX_STORED_BYTES = 2 * 1024 * 1024
STATE_SCHEMA_VERSION = 2
OPTIONS_SNAPSHOT_FILE_NAME = "options-state.json"
OPTIONS_BACKUP_FILE_NAME = "options-state.previous.json"
PERSISTED_STATE_FILE_NAMES = frozenset(
    {
        "profile.json",
        "status.json",
        OPTIONS_SNAPSHOT_FILE_NAME,
        OPTIONS_BACKUP_FILE_NAME,
    }
)


class ProfileStore:
    """Persist only sanitized profile/status data in the App data volume."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.data_dir = Path(data_dir)
        if self.data_dir.is_symlink():
            raise ValueError("state directory must be a real directory")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.data_dir.is_dir():
            raise ValueError("state directory must be a real directory")
        # The App owns this directory after its guarded root-to-non-root
        # transition. Keep persisted profile/diagnostic state private even if
        # a Supervisor-like mount arrived with permissive mode bits.
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            # A read-only or externally managed mount can still be used when
            # its existing permissions permit the App's normal writes.
            pass
        self.profile_path = self.data_dir / "profile.json"
        self.status_path = self.data_dir / "status.json"
        self.options_snapshot_path = self.data_dir / OPTIONS_SNAPSHOT_FILE_NAME
        self.options_backup_path = self.data_dir / OPTIONS_BACKUP_FILE_NAME

    def save_profile(self, profile: HomeProfile) -> None:
        payload = profile.to_dict()
        try:
            assert_no_secrets(payload)
        except SensitiveDataError as exc:
            raise ValueError("refusing to persist sensitive profile data") from exc
        self._atomic_write(self.profile_path, self._envelope("profile", payload))

    def load_profile(self) -> dict[str, Any] | None:
        value = self._load(self.profile_path)
        if value is None:
            return None
        if "profile" in value:
            if value.get("schema_version") != STATE_SCHEMA_VERSION or not isinstance(value["profile"], dict):
                raise ValueError("unsupported profile state schema")
            return value["profile"]
        # Version-one files were profile objects at the top level.
        try:
            self._atomic_write(self.profile_path, self._envelope("profile", value))
        except OSError:
            # A valid backup may be mounted read-only during recovery. Keep
            # serving the last profile rather than discarding it merely
            # because its envelope cannot be upgraded in place yet.
            pass
        return value

    def save_status(self, payload: dict[str, Any]) -> None:
        assert_no_secrets(payload)
        self._atomic_write(self.status_path, self._envelope("status", payload))

    def load_status(self) -> dict[str, Any] | None:
        value = self._load(self.status_path)
        if value is None:
            return None
        if "status" in value:
            if value.get("schema_version") != STATE_SCHEMA_VERSION or not isinstance(value["status"], dict):
                raise ValueError("unsupported status state schema")
            return value["status"]
        try:
            self._atomic_write(self.status_path, self._envelope("status", value))
        except OSError:
            pass
        return value

    def save_options_snapshot(self, payload: dict[str, Any]) -> None:
        """Persist only non-secret option state used for restart diagnostics.

        Supervisor remains the source of truth for credentials and live App
        options. This small snapshot is deliberately separate from
        ``options.json`` so an App restart cannot overwrite Supervisor state.
        """

        assert_no_secrets(payload)
        snapshot = self._envelope("options", dict(payload))
        # Keep one secret-free rollback point. This is diagnostic/configuration
        # history only; Supervisor's options remain authoritative and are
        # never replaced from this file.
        if self.options_snapshot_path.exists():
            current = self._load(self.options_snapshot_path)
            if current is not None:
                self._atomic_write(self.options_backup_path, current)
        self._atomic_write(self.options_snapshot_path, snapshot)

    def load_options_snapshot(self) -> dict[str, Any] | None:
        try:
            value = self._load(self.options_snapshot_path)
        except (OSError, TypeError, ValueError):
            # A failed update must not erase the last known safe, secret-free
            # snapshot. Do not promote it to live Supervisor options.
            value = self._load(self.options_backup_path)
        if value is None:
            value = self._load(self.options_backup_path)
        if value is None:
            return None
        if value.get("schema_version") != STATE_SCHEMA_VERSION or not isinstance(value.get("options"), dict):
            raise ValueError("unsupported options state schema")
        return value["options"]

    @staticmethod
    def _envelope(name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"schema_version": STATE_SCHEMA_VERSION, name: payload}

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
        if path.is_symlink():
            raise ValueError(f"refusing to replace symlink state {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                if len(encoded.encode("utf-8")) > MAX_STORED_BYTES:
                    raise ValueError("stored state exceeds size bound")
                handle.write(encoded)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            # Persist the directory entry before reporting success. This
            # keeps a committed profile/status across abrupt container exits.
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _load(path: Path) -> dict[str, Any] | None:
        try:
            if path.is_symlink():
                raise ValueError(f"refusing to load symlink state {path.name}")
            if path.stat().st_size > MAX_STORED_BYTES:
                raise ValueError(f"stored state {path.name} exceeds size bound")
            with path.open(encoding="utf-8") as handle:
                value = json.load(handle)
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"stored state {path.name} is not an object")
        assert_no_secrets(value)
        return value
