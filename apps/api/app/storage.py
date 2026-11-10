"""Object storage adapters for local development and S3-compatible deployments."""
from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Any


class StorageError(RuntimeError):
    pass


def _validate_object_key(object_key: str) -> str:
    if not object_key or "\x00" in object_key or "\\" in object_key or object_key.startswith("/"):
        raise StorageError("Invalid object key")
    parts = PurePosixPath(object_key).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise StorageError("Invalid object key")
    return object_key


class LocalObjectStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, object_key: str) -> Path:
        key = _validate_object_key(object_key)
        candidate = (self.root / key).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise StorageError("Object key escapes the configured storage root")
        return candidate

    def resolve_path(self, object_key: str) -> Path:
        """Return a validated local object path for read-only API streaming."""
        return self._resolve(object_key)

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


class S3ObjectStorage:
    """S3/S3-compatible adapter; credentials are supplied by the runtime, not stored here."""

    def __init__(
        self,
        bucket: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any | None = None,
    ):
        if not bucket or not bucket.strip():
            raise StorageError("S3 bucket is required")
        self.bucket = bucket
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise StorageError("boto3 is required for S3 storage; install API requirements") from exc
            client = boto3.client(
                "s3",
                region_name=region_name,
                endpoint_url=endpoint_url or None,
                aws_access_key_id=access_key_id or None,
                aws_secret_access_key=secret_access_key or None,
                config=Config(s3={"addressing_style": "path"}),
            )
        self.client = client

    def materialize(self, object_key: str, destination: str | Path) -> Path:
        key = _validate_object_key(object_key)
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, key, str(target))
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise StorageError(f"Could not download object: {key}") from exc
        if not target.is_file() or target.stat().st_size <= 0:
            raise StorageError(f"Downloaded object is missing or empty: {key}")
        return target

    def put_file(self, source: str | Path, object_key: str) -> str:
        key = _validate_object_key(object_key)
        source_path = Path(source).resolve()
        if not source_path.is_file() or source_path.stat().st_size <= 0:
            raise StorageError("Cannot store a missing or empty render output")
        try:
            self.client.upload_file(str(source_path), self.bucket, key)
        except Exception as exc:
            raise StorageError(f"Could not upload object: {key}") from exc
        return key

    def create_download_url(self, object_key: str, expires_seconds: int = 900) -> str:
        key = _validate_object_key(object_key)
        if expires_seconds < 1 or expires_seconds > 604800:
            raise ValueError("expires_seconds must be between 1 and 604800")
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_seconds,
            )
        except Exception as exc:
            raise StorageError(f"Could not create download URL: {key}") from exc


def create_object_storage(settings: Any) -> LocalObjectStorage | S3ObjectStorage:
    backend = str(settings.storage_backend).lower()
    if backend == "local":
        return LocalObjectStorage(settings.storage_root)
    if backend == "s3":
        if not settings.s3_bucket:
            raise StorageError("S3_BUCKET is required when EDITFLOW_STORAGE_BACKEND=s3")
        return S3ObjectStorage(
            bucket=settings.s3_bucket,
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
        )
    raise StorageError("EDITFLOW_STORAGE_BACKEND must be 'local' or 's3'")
