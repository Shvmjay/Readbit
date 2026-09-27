"""Upload validation: extension, declared MIME, magic bytes, size, archive safety, encryption, page limits."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
EPUB_MIME = "application/epub+zip"
ALLOWED_DECLARED_MIME = {
    "pdf": {"application/pdf", "application/x-pdf", "application/octet-stream", ""},
    "epub": {EPUB_MIME, "application/zip", "application/octet-stream", ""},
}
MAX_EPUB_ENTRIES = 5000
MAX_EPUB_UNCOMPRESSED = 400 * 1024 * 1024
MAX_COMPRESSION_RATIO = 120


@dataclass
class ValidatedUpload:
    file_format: str
    mime_type: str
    safe_filename: str


def sanitize_filename(name: str | None) -> str:
    name = (name or "upload").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\- ()ऀ-ॿ]", "_", name).strip(" .") or "upload"
    return name[:200]


def _unsupported(msg: str = "Readbit supports PDF and EPUB files only.") -> AppError:
    return AppError(ErrorCode.UNSUPPORTED_FILE, msg, status_code=415)


def validate_upload(filename: str | None, declared_mime: str | None, data: bytes) -> ValidatedUpload:
    settings = get_settings()
    safe = sanitize_filename(filename)
    ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
    if ext not in ("pdf", "epub"):
        raise _unsupported()
    if len(data) == 0:
        raise AppError(ErrorCode.CORRUPTED_DOCUMENT, "The file is empty.", status_code=422)
    if len(data) > settings.max_upload_bytes:
        raise AppError(
            ErrorCode.FILE_TOO_LARGE,
            f"The file is larger than the {settings.max_upload_size_mb} MB limit.",
            status_code=413,
        )
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared not in ALLOWED_DECLARED_MIME[ext]:
        raise _unsupported("The file type does not match its extension.")

    if ext == "pdf":
        if not data[:1024].lstrip().startswith(PDF_MAGIC) and PDF_MAGIC not in data[:1024]:
            raise _unsupported("This file does not look like a valid PDF.")
        return ValidatedUpload("pdf", "application/pdf", safe)

    if not data.startswith(ZIP_MAGIC):
        raise _unsupported("This file does not look like a valid EPUB.")
    check_epub_archive(data)
    return ValidatedUpload("epub", EPUB_MIME, safe)


def check_epub_archive(data: bytes) -> None:
    """Defend against zip bombs and path tricks before any parsing happens."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AppError(ErrorCode.CORRUPTED_DOCUMENT, "The EPUB archive is damaged.", status_code=422) from exc
    infos = zf.infolist()
    if len(infos) > MAX_EPUB_ENTRIES:
        raise AppError(ErrorCode.UNSUPPORTED_FILE, "The EPUB contains too many files.", status_code=422)
    total = 0
    for info in infos:
        if info.filename.startswith("/") or ".." in info.filename.split("/"):
            raise AppError(ErrorCode.UNSUPPORTED_FILE, "The EPUB contains unsafe paths.", status_code=422)
        if info.flag_bits & 0x1:
            raise AppError(ErrorCode.PASSWORD_PROTECTED, "This EPUB is encrypted.", status_code=422)
        total += info.file_size
        if info.compress_size and info.file_size > 1_000_000 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise AppError(ErrorCode.UNSUPPORTED_FILE, "The EPUB has a suspicious compression ratio.", status_code=422)
    if total > MAX_EPUB_UNCOMPRESSED:
        raise AppError(ErrorCode.FILE_TOO_LARGE, "The EPUB expands beyond the processing limit.", status_code=413)
    names = set(zf.namelist())
    if "mimetype" in names:
        mt = zf.read("mimetype")[:64].decode("ascii", "ignore").strip()
        if mt != EPUB_MIME:
            raise _unsupported("This archive is not an EPUB.")
    if "META-INF/container.xml" not in names:
        raise AppError(ErrorCode.CORRUPTED_DOCUMENT, "The EPUB is missing its container manifest.", status_code=422)
    if "META-INF/encryption.xml" in names:
        # Font obfuscation is common and harmless; DRM encryption of content documents is not supported.
        enc = zf.read("META-INF/encryption.xml").decode("utf-8", "ignore")
        if "http://www.idpf.org/2008/embedding" not in enc and "http://ns.adobe.com/pdf/enc#RC" not in enc:
            raise AppError(
                ErrorCode.PASSWORD_PROTECTED,
                "This EPUB is DRM-protected. Readbit can only process DRM-free books.",
                status_code=422,
            )
