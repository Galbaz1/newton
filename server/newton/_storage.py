"""Internal private original storage: bounded bytes, generated keys, no public paths."""

import hashlib
import os
import re
import stat
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from .config import settings

MAX_BYTES = 64 * 1024 * 1024
_TYPES = {
    ".json": ("application/json", "annotation"),
    ".pdf": ("application/pdf", "document"),
    ".txt": ("text/plain", "document"),
    ".md": ("text/markdown", "document"),
    ".csv": ("text/csv", "timeseries"),
    ".png": ("image/png", "image"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".webp": ("image/webp", "image"),
}


def read_upload(file: UploadFile) -> tuple[bytes, str, str, str]:
    """Read at most 64 MiB plus one byte; reject empty/unsupported/spoofed uploads."""
    try:
        data = file.file.read(MAX_BYTES + 1)
    finally:
        file.file.close()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File exceeds the 64 MiB limit")
    if not data:
        raise HTTPException(422, "File is empty")
    raw_name = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(raw_name).suffix.lower()
    if suffix not in _TYPES:
        raise HTTPException(415, "Use PDF, TXT, MD, CSV, JSON, PNG, JPEG or WebP files")
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_name).stem).strip("._") or "upload"
    filename = stem[: 200 - len(suffix)] + suffix
    media_type, kind = _TYPES[suffix]
    supplied = (file.content_type or "application/octet-stream").split(";", 1)[0].lower()
    aliases = {media_type, "application/octet-stream"}
    if suffix in {".txt", ".md", ".csv"}:
        aliases.add("text/plain")
    if supplied not in aliases:
        raise HTTPException(415, "File content type does not match its extension")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(415, "File does not contain a PDF header")
    return data, filename, media_type, kind


def _directory() -> Path:
    root = settings.data_dir
    directory = root / "originals"
    if root.is_symlink() or directory.is_symlink():
        raise HTTPException(503, "Private storage is unavailable")
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=True)
        root.chmod(0o700)
        directory.chmod(0o700)
        return directory.resolve()
    except OSError:
        raise HTTPException(503, "Private storage is unavailable") from None


def _path(key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}\.bin", key):
        raise HTTPException(503, "Original file is unavailable")
    return _directory() / key


def save_original(data: bytes) -> str:
    """Write a new private read-only original under an unguessable exclusive key."""
    key = f"{uuid4().hex}.bin"
    path = _path(key)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o400)
    except OSError:
        path.unlink(missing_ok=True)
        raise HTTPException(503, "Original could not be stored") from None
    return key


def read_original(source) -> bytes:
    """Read a regular, bounded, non-symlink original and verify its stored SHA256."""
    path = _path(source.storage_path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise OSError("Invalid original")
            data = stream.read(MAX_BYTES + 1)
        if hashlib.sha256(data).hexdigest() != source.sha256:
            raise OSError("Original digest mismatch")
        return data
    except OSError:
        raise HTTPException(
            503, "Original file is unavailable or failed integrity checks"
        ) from None


def remove_original(key: str) -> None:
    """Remove a private original after its metadata has been deleted or rolled back."""
    try:
        _path(key).unlink(missing_ok=True)
    except OSError:
        raise HTTPException(503, "Private file cleanup failed") from None


def stage_removal(key: str) -> Path | None:
    """Hide an original until a deletion transaction commits; missing files are allowed."""
    path = _path(key)
    temporary = path.with_suffix(".deleting")
    try:
        path.rename(temporary)
    except FileNotFoundError:
        return None
    except OSError:
        raise HTTPException(503, "Private file cleanup failed") from None
    return temporary


def undo_removal(temporary: Path | None, key: str) -> None:
    """Restore a staged original if its database deletion rolls back."""
    if temporary is not None:
        temporary.rename(_path(key))
