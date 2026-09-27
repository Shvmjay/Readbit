"""Document ingestion job: validate → extract → structure → chunk → index → ready.

The handler is idempotent: it can be re-run for the same book at any time (retry, worker crash, redelivery) and
rebuilds derived rows from scratch inside the stage that owns them. Status is committed at every stage so the
client can show accurate progress; a book is only marked `ready` after every required stage succeeded.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.embeddings import get_embedder
from app.ai.router import ModelRouter
from app.core.db import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import sha256_hex
from app.document_processing.chunking import chunk_chapter
from app.document_processing.epub import extract_epub
from app.document_processing.pdf import extract_pdf
from app.document_processing.structure import apply_llm_boundaries, detect_chapters
from app.document_processing.text import detect_language, estimate_tokens, word_count
from app.document_processing.types import ExtractedDocument
from app.models.books import Book, Chapter, DocumentChunk, EvidenceReference, ProcessingJob
from app.models.content import Summary
from app.models.learning import Question, Topic
from app.services.analytics import track
from app.services.state_machine import PROGRESS, transition
from app.storage.base import get_storage

log = get_logger("readbit.ingest")
PROCESSING_VERSION = "ingest-2026.09.1"
MIN_WORDS = 60


class _Stage:
    def __init__(self, db: Session, job: ProcessingJob, book: Book) -> None:
        self.db, self.job, self.book = db, job, book

    def enter(self, status: str) -> float:
        transition(self.book, status)
        self.job.stage = status
        self.job.progress_percent = PROGRESS[status]
        self.db.commit()
        return time.monotonic()

    def done(self, status: str, started: float) -> None:
        timings = dict(self.job.stage_timings or {})
        timings[status] = int((time.monotonic() - started) * 1000)
        self.job.stage_timings = timings


def run_ingest_job(job_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.status in ("succeeded", "cancelled"):
            return
        book = db.get(Book, job.book_id)
        if book is None or book.deleted_at is not None:
            job.status = "cancelled"
            db.commit()
            return
        if book.processing_status == "ready":
            job.status, job.progress_percent = "succeeded", 100
            db.commit()
            return
        if book.processing_status == "failed":
            transition(book, "uploaded")
        elif book.processing_status != "uploaded":
            # A previous attempt died mid-pipeline: restart cleanly from the beginning.
            book.processing_status = "uploaded"
        job.status = "running"
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        job.error_code = job.safe_error_message = None
        db.commit()
        try:
            _pipeline(db, job, book)
        except AppError as exc:
            db.rollback()
            _fail(db, job.id, exc.code, exc.message)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("ingest crashed", extra={"job_id": str(job_id)})
            _fail(db, job.id, ErrorCode.INTERNAL, "Something went wrong while processing this book. You can retry.")


def _fail(db: Session, job_id: uuid.UUID, code: ErrorCode, message: str) -> None:
    job = db.get(ProcessingJob, job_id)
    if job is None:
        return
    book = db.get(Book, job.book_id)
    job.status, job.error_code, job.safe_error_message = "failed", str(code), message
    job.completed_at = datetime.now(UTC)
    if book is not None and book.processing_status != "ready":
        book.processing_status = "failed"
        track(db, "document_processing_failed", None, book.id, error_code=str(code), format=book.file_format)
    db.commit()


def _pipeline(db: Session, job: ProcessingJob, book: Book) -> None:
    st = _Stage(db, job, book)

    t = st.enter("validating")
    source = book.source_file
    if source is None or source.deleted_at is not None:
        raise AppError(ErrorCode.STORAGE_FAILURE, "The uploaded file is no longer available. Please upload it again.")
    data = get_storage().get(source.storage_key)
    if sha256_hex(data) != source.checksum:
        raise AppError(ErrorCode.CORRUPTED_DOCUMENT, "The stored file failed an integrity check. Please upload it again.")
    st.done("validating", t)

    t = st.enter("extracting")
    doc = extract_pdf(data) if book.file_format == "pdf" else extract_epub(data)
    total_words = sum(word_count(b.text) for b in doc.blocks)
    if total_words < MIN_WORDS:
        if doc.unreadable_pages:
            raise AppError(
                ErrorCode.OCR_UNAVAILABLE,
                "This looks like a scanned book without a text layer, and OCR is not enabled on this server. "
                "Try a version of the book with selectable text.",
            )
        raise AppError(ErrorCode.EXTRACTION_QUALITY_LOW, "We could not find enough readable text in this file.")
    if doc.quality < 0.5:
        doc.warn("extraction_quality_low", "Parts of this document may not have been extracted accurately.")
    st.done("extracting", t)

    t = st.enter("structuring")
    specs, confidence = detect_chapters(doc)
    if confidence < 0.5:
        specs, confidence = _try_model_structure(db, book, doc, specs, confidence)
    if confidence < 0.5:
        doc.warn(
            "chapter_detection_uncertain",
            "No reliable chapter structure was found. The book has been split into clearly labelled sections instead.",
        )
    sample = " ".join(b.text for b in doc.blocks[:200])
    detected = detect_language(sample)
    book.detected_language = detected
    book.original_language = doc.language or detected
    if doc.title and book.title_source == "filename":
        book.title = doc.title[:500]
        book.title_source = "metadata"
    if doc.author:
        book.author = doc.author[:500]
    book.page_count = doc.page_count
    book.word_count = total_words
    book.extraction_quality = doc.quality
    book.structure_confidence = confidence
    book.extraction_warnings = doc.warnings
    st.done("structuring", t)

    t = st.enter("chunking")
    # Idempotency: derived rows are rebuilt from scratch.
    for model in (Summary, Question, Topic, EvidenceReference, DocumentChunk, Chapter):
        db.execute(delete(model).where(model.book_id == book.id))
    ordinal = 0
    for idx, spec in enumerate(specs):
        chunks, chapter_text = chunk_chapter(doc, spec, idx)
        if not chunks:
            continue
        first, last = chunks[0], chunks[-1]
        chapter = Chapter(
            book_id=book.id,
            ordinal=idx + 1,
            title=spec.title[:500],
            start_location={**first.start_location, "char": 0},
            end_location={**last.end_location, "char": len(chapter_text)},
            detection_method=spec.method,
            detection_confidence=spec.confidence,
            content_hash=sha256_hex(chapter_text.encode()),
            word_count=word_count(chapter_text),
        )
        db.add(chapter)
        db.flush()
        for c in chunks:
            ordinal += 1
            db.add(
                DocumentChunk(
                    book_id=book.id,
                    chapter_id=chapter.id,
                    ordinal=ordinal,
                    text_content=c.text,
                    token_count=estimate_tokens(c.text),
                    source_start_location={**c.start_location, "char": c.char_start},
                    source_end_location={**c.end_location, "char": c.char_end},
                    page_start=c.page_start,
                    page_end=c.page_end,
                    page_label_start=c.page_label_start,
                    page_label_end=c.page_label_end,
                    section_title=c.section_title,
                    content_hash=sha256_hex(c.text.encode()),
                    extraction_confidence=c.confidence,
                )
            )
    # Re-number chapters densely (skipped empty specs would leave gaps).
    db.flush()
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)))
    for i, ch in enumerate(chapters, 1):
        ch.ordinal = -i
    db.flush()
    for ch in chapters:
        ch.ordinal = -ch.ordinal
    book.chapter_count = len(chapters)
    if not chapters:
        raise AppError(ErrorCode.EXTRACTION_QUALITY_LOW, "We could not find enough readable text in this file.")
    st.done("chunking", t)

    t = st.enter("indexing")
    embedder = get_embedder()
    rows = list(db.scalars(select(DocumentChunk).where(DocumentChunk.book_id == book.id).order_by(DocumentChunk.ordinal)))
    batch = 64
    for i in range(0, len(rows), batch):
        part = rows[i : i + batch]
        for row, vec in zip(part, embedder.embed([r.text_content for r in part]), strict=True):
            row.embedding = vec
    st.done("indexing", t)

    book.processing_version = PROCESSING_VERSION
    transition(book, "ready")
    job.stage, job.progress_percent, job.status = "ready", 100, "succeeded"
    job.completed_at = datetime.now(UTC)
    track(db, "document_processing_completed", None, book.id, format=book.file_format, count=book.chapter_count)
    db.commit()
    log.info("ingest complete", extra={"book_id": str(book.id), "chapters": book.chapter_count, "chunks": len(rows)})


def _try_model_structure(db: Session, book: Book, doc: ExtractedDocument, specs, confidence):
    """Conservative model-assisted chapter detection. Only selects from existing short standalone lines."""
    router = ModelRouter(db)
    if router.is_offline:
        return specs, confidence
    candidates = [
        (i, b.text) for i, b in enumerate(doc.blocks) if len(b.text) <= 100 and (b.kind == "heading" or len(b.text.split()) <= 10)
    ][:300]
    if len(candidates) < 2:
        return specs, confidence
    passages = [{"id": f"L{i}", "text": text} for i, text in candidates]
    rendered = "\n".join(f'<passage id="L{i}">{text}</passage>' for i, text in candidates)
    try:
        result = router.generate(
            "chapter_detector",
            variables={"passages": rendered},
            context={"passages": passages},
            book_id=book.id,
        )
    except AppError:
        return specs, confidence
    indices = [i for i in result.data.get("chapter_start_indices", []) if isinstance(i, int)]
    if len(indices) >= 2 and result.data.get("confidence") != "low":
        new_specs = apply_llm_boundaries(doc, indices)
        if len(new_specs) >= 2:
            return new_specs, 0.6
    return specs, confidence
