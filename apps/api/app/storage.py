"""Local filesystem storage adapter with traversal-safe object keys.

This is a development/worker adapter. Production object storage should implement
the same interface without exposing bucket credentials to the API process.
"""
from __future__ import annotations

import shutil
from pathlib import Path


class StorageError(RuntimeError):
    pass


class LocalObjectStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, object_key: str) -> Path:
        if not object_key or "\x00" in object_key:
            raise StorageError("Invalid object key")
        candidate = (self.root / object_key).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise StorageError("Object key escapes the configured storage root")
        return candidate

    def materialize(self, object_key: str, destination: str | Path) -> Path:
        source = self._resolve(object_key)
        target = Path(destination).resolve()
        if not source.is_file():
            raise StorageError(f"Stored asset does not exist: {object_key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target

    def put_file(self, source: str | Path, object_key: str) -> str:
        source_path = Path(source).resolve()
        if not source_path.is_file() or source_path.stat().st_size <= 0:
            raise StorageError("Cannot store a missing or empty render output")
        target = self._resolve(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        return object_key
