"""Object storage abstraction. Keys are random and never exposed to clients."""

from __future__ import annotations

import secrets
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode


def new_storage_key(prefix: str, extension: str) -> str:
    ext = extension.lower().lstrip(".")
    if ext not in {"pdf", "epub"}:
        raise ValueError("unsupported extension")
    return f"{prefix}/{secrets.token_hex(16)}.{ext}"


class ObjectStorage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalStorage(ObjectStorage):
    """Filesystem storage for development and tests. Rejects any key that escapes the root."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise AppError(ErrorCode.STORAGE_FAILURE, "Invalid storage key.", status_code=500)
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise AppError(
                ErrorCode.STORAGE_FAILURE, "The stored file is no longer available.", status_code=410
            )
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage(ObjectStorage):
    """S3-compatible private storage (AWS S3, MinIO, R2...). Server-side encryption requested on every put."""

    def __init__(self) -> None:
        import boto3

        s = get_settings()
        self.bucket = s.storage_bucket
        self.client = boto3.client(
            "s3",
            region_name=s.storage_region,
            endpoint_url=s.storage_endpoint or None,
            aws_access_key_id=s.storage_access_key or None,
            aws_secret_access_key=s.storage_secret_key or None,
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                ErrorCode.STORAGE_FAILURE, "We could not store your file. Please retry.", status_code=503
            ) from exc

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                ErrorCode.STORAGE_FAILURE, "The stored file could not be read.", status_code=503
            ) from exc

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False


@lru_cache
def get_storage() -> ObjectStorage:
    s = get_settings()
    if s.storage_provider == "s3":
        return S3Storage()
    return LocalStorage(s.storage_local_path)
