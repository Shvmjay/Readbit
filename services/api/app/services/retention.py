"""Retention and deletion: guest-session expiry, orphaned files, account deletion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.books import Book, SourceFile
from app.models.users import AuthSession, GuestSession, PasswordResetToken, User
from app.storage.base import get_storage

log = get_logger("readbit.retention")


def _now() -> datetime:
    return datetime.now(UTC)


def remove_book(db: Session, book: Book) -> None:
    """Delete a book, its derived data (FK cascades) and its stored file. If the file cannot be deleted right now,
    the file record is kept with an immediate retention expiry so the cleanup job retries."""
    source = book.source_file
    db.delete(book)
    db.flush()
    if source is not None:
        try:
            get_storage().delete(source.storage_key)
            db.delete(source)
        except Exception:  # noqa: BLE001
            log.warning("storage delete failed; cleanup will retry", extra={"source_id": str(source.id)})
            source.retention_expiry = _now()
            source.deleted_at = _now()


def delete_user_account(db: Session, user: User) -> None:
    """Deletes the account and everything it owns (books, files, notes, learning history)."""
    for book in list(db.scalars(select(Book).where(Book.owner_user_id == user.id))):
        remove_book(db, book)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    db.delete(user)
    db.commit()
    log.info("account deleted")


def run_retention_cleanup(db: Session) -> dict:
    now = _now()
    storage = get_storage()
    expired_guests = list(db.scalars(select(GuestSession).where(GuestSession.expires_at <= now)))
    books_removed = 0
    for guest in expired_guests:
        for book in list(db.scalars(select(Book).where(Book.guest_session_id == guest.id))):
            remove_book(db, book)
            books_removed += 1
        db.delete(guest)
    files_removed = 0
    for sf in db.scalars(select(SourceFile).where(SourceFile.retention_expiry <= now)):
        referenced = db.scalar(select(Book.id).where(Book.source_file_id == sf.id))
        if referenced is None:
            try:
                storage.delete(sf.storage_key)
            except Exception:  # noqa: BLE001
                continue
            db.delete(sf)
            files_removed += 1
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now - timedelta(days=7)))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at <= now - timedelta(days=1)))
    db.commit()
    result = {"guests_expired": len(expired_guests), "books_removed": books_removed, "files_removed": files_removed}
    log.info("retention cleanup", extra=result)
    return result
