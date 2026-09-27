"""Response serializers. Never expose storage keys, token hashes or answer keys before submission."""

from __future__ import annotations

from app.models.books import Book, Chapter, ProcessingJob
from app.models.users import User


def iso(dt):
    return dt.isoformat() if dt else None


def serialize_job(job: ProcessingJob | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": str(job.id), "job_type": job.job_type, "status": job.status, "stage": job.stage,
        "progress_percent": job.progress_percent, "attempts": job.attempts,
        "error": {"code": job.error_code, "message": job.safe_error_message} if job.status == "failed" else None,
        "started_at": iso(job.started_at), "completed_at": iso(job.completed_at), "updated_at": iso(job.updated_at),
    }


def serialize_book(book: Book, job: ProcessingJob | None = None) -> dict:
    sf = book.source_file
    return {
        "id": str(book.id),
        "title": book.title,
        "title_source": book.title_source,
        "author": book.author,  # null = not reliably extracted
        "file_format": book.file_format,
        "original_filename": sf.original_filename if sf else None,
        "size_bytes": sf.size_bytes if sf else None,
        "detected_language": book.detected_language,
        "processing_status": book.processing_status,
        "learning_status": book.learning_status,
        "extraction_quality": book.extraction_quality,
        "structure_confidence": book.structure_confidence,
        "warnings": book.extraction_warnings or [],
        "chapter_count": book.chapter_count,
        "page_count": book.page_count,
        "word_count": book.word_count,
        "estimated_reading_minutes": round(book.word_count / 230) if book.word_count else None,
        "owner": "guest" if book.guest_session_id else "user",
        "created_at": iso(book.created_at),
        "updated_at": iso(book.updated_at),
        "processing_job": serialize_job(job),
    }


def serialize_chapter(ch: Chapter) -> dict:
    return {
        "id": str(ch.id), "ordinal": ch.ordinal, "title": ch.title, "detection_method": ch.detection_method,
        "detection_confidence": ch.detection_confidence, "word_count": ch.word_count,
        "estimated_reading_minutes": max(1, round(ch.word_count / 230)) if ch.word_count else None,
        "start_location": ch.start_location, "end_location": ch.end_location,
    }


def serialize_user(user: User) -> dict:
    return {
        "id": str(user.id), "email": user.email, "display_name": user.display_name,
        "preferred_language": user.preferred_language, "content_language": user.content_language,
        "theme_preference": user.theme_preference, "daily_goal_questions": user.daily_goal_questions,
        "created_at": iso(user.created_at),
    }
