"""Library: uploads, ownership-checked access, processing status, retries and deletion."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, not_found
from app.core.logging import get_logger
from app.core.security import sha256_hex
from app.document_processing.validation import validate_upload
from app.models.books import Book, Chapter, ProcessingJob, SourceFile
from app.services.actors import CurrentActor
from app.services.analytics import track
from app.storage.base import get_storage, new_storage_key
from app.workers.dispatch import enqueue

log = get_logger("readbit.books")


def get_owned_book(db: Session, actor: CurrentActor, book_id: uuid.UUID) -> Book:
    """Ownership is enforced in SQL; a book owned by someone else is indistinguishable from a missing one."""
    book = db.scalar(select(Book).where(Book.id == book_id, actor.owns(Book), Book.deleted_at.is_(None)))
    if book is None:
        raise not_found("Book")
    return book


def list_books(
    db: Session, actor: CurrentActor, *, limit: int = 20, cursor: str | None = None
) -> tuple[list[Book], str | None]:
    stmt = select(Book).where(actor.owns(Book), Book.deleted_at.is_(None))
    if cursor:
        try:
            ts, bid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
            cur_ts, cur_id = datetime.fromisoformat(ts), uuid.UUID(bid)
        except (ValueError, UnicodeDecodeError) as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Invalid cursor.", status_code=422) from exc
        stmt = stmt.where((Book.created_at < cur_ts) | ((Book.created_at == cur_ts) & (Book.id < cur_id)))
    rows = list(db.scalars(stmt.order_by(Book.created_at.desc(), Book.id.desc()).limit(limit + 1)))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = base64.urlsafe_b64encode(f"{last.created_at.isoformat()}|{last.id}".encode()).decode()
    return rows, next_cursor


def upload_book(
    db: Session, actor: CurrentActor, filename: str | None, content_type: str | None, data: bytes
) -> tuple[Book, bool]:
    settings = get_settings()
    track(db, "book_upload_initiated", actor.key)
    validated = validate_upload(filename, content_type, data)
    checksum = sha256_hex(data)
    duplicate = db.scalar(
        select(Book).where(
            actor.owns(Book),
            Book.content_hash == checksum,
            Book.deleted_at.is_(None),
            Book.processing_status != "failed",
        )
    )
    if duplicate is not None:
        db.commit()
        return duplicate, True
    key = new_storage_key("books", validated.file_format)
    get_storage().put(key, data, validated.mime_type)
    retention = None
    if actor.is_guest and actor.guest is not None:
        retention = actor.guest.expires_at
    source = SourceFile(
        storage_key=key,
        original_filename=validated.safe_filename,
        mime_type=validated.mime_type,
        size_bytes=len(data),
        checksum=checksum,
        encryption_metadata={"server_side": "AES256" if settings.storage_provider == "s3" else "filesystem"},
        retention_expiry=retention,
    )
    db.add(source)
    db.flush()
    title = validated.safe_filename.rsplit(".", 1)[0].replace("_", " ").strip() or "Untitled upload"
    book = Book(
        title=title[:500],
        title_source="filename",
        file_format=validated.file_format,
        source_file_id=source.id,
        content_hash=checksum,
        processing_status="uploaded",
        **actor.owner_fields(),
    )
    db.add(book)
    db.flush()
    job = ProcessingJob(book_id=book.id, job_type="ingest", stage="uploaded", progress_percent=5)
    db.add(job)
    track(db, "book_upload_completed", actor.key, book.id, format=validated.file_format)
    db.commit()
    enqueue("ingest", job.id)
    db.refresh(book)
    return book, False


def latest_job(db: Session, book_id: uuid.UUID, job_type: str = "ingest") -> ProcessingJob | None:
    return db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.book_id == book_id, ProcessingJob.job_type == job_type)
        .order_by(ProcessingJob.created_at.desc())
    )


def retry_processing(db: Session, book: Book) -> ProcessingJob:
    if book.processing_status != "failed":
        raise AppError(
            ErrorCode.CONFLICT, "Only books whose processing failed can be retried.", status_code=409
        )
    job = ProcessingJob(book_id=book.id, job_type="ingest", stage="uploaded", progress_percent=5)
    db.add(job)
    db.commit()
    enqueue("ingest", job.id)
    return job


def delete_book(db: Session, book: Book) -> None:
    """Hard-deletes derived data and the stored file; keeps no copy of the user's book."""
    from app.services.retention import remove_book

    remove_book(db, book)
    db.commit()


def chapters(db: Session, book: Book) -> list[Chapter]:
    return list(db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)))


def guest_expiry_notice(actor: CurrentActor) -> datetime | None:
    if actor.is_guest and actor.guest is not None:
        return actor.guest.expires_at
    return None
