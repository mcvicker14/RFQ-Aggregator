"""File storage abstraction. `LocalDiskStorage` is the working default. A future
S3/Azure Blob backend implements the same `StorageBackend` interface and is selected
via settings.STORAGE_BACKEND — no route or service code changes when that happens.
See docs/ARCHITECTURE.md §Deployment shape and docs/SECURITY.md §File uploads.
"""
import mimetypes
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings

settings = get_settings()

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".png", ".jpg", ".jpeg", ".gif", ".csv", ".txt", ".zip",
}


class StorageBackend(ABC):
    @abstractmethod
    def save(self, file: UploadFile, subdir: str) -> tuple[str, int]:
        """Persist the file, return (opaque_storage_path, size_bytes)."""

    @abstractmethod
    def read_path(self, storage_path: str) -> Path:
        """Return a local filesystem path to the stored file (for download/analysis)."""


class LocalDiskStorage(StorageBackend):
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, file: UploadFile, subdir: str) -> tuple[str, int]:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"File type '{ext}' is not permitted for upload.")

        target_dir = self.base_dir / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        generated_name = f"{uuid.uuid4().hex}{ext}"
        target_path = target_dir / generated_name

        size = 0
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        with open(target_path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    os.remove(target_path)
                    raise ValueError(f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB upload limit.")
                out.write(chunk)

        storage_path = f"{subdir}/{generated_name}"
        return storage_path, size

    def read_path(self, storage_path: str) -> Path:
        return self.base_dir / storage_path


def get_storage_backend() -> StorageBackend:
    if settings.STORAGE_BACKEND == "local":
        return LocalDiskStorage(settings.UPLOAD_DIR)
    raise NotImplementedError(
        f"Storage backend '{settings.STORAGE_BACKEND}' is not implemented yet. "
        "See docs/ARCHITECTURE.md §Deployment shape — this is a Phase 2 integration "
        "point (S3/Azure Blob), not something silently faked."
    )


def guess_content_type(filename: str) -> str | None:
    return mimetypes.guess_type(filename)[0]
