"""Books, source files, structure (chapters, chunks), evidence and processing jobs."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, JSONType, TimestampMixin, utcnow
from app.models.types import EmbeddingType

OWNER_CHECK = "(owner_user_id IS NOT NULL) <> (guest_session_id IS NOT NULL)"


class SourceFile(IdMixin, Base):
    __tablename__ = "source_files"

    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    encryption_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    retention_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Book(IdMixin, TimestampMixin, Base):
    __tablename__ = "books"
    __table_args__ = (
        CheckConstraint(OWNER_CHECK, name="book_single_owner"),
        Index("ix_books_owner_hash", "owner_user_id", "content_hash"),
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("guest_sessions.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    title_source: Mapped[str] = mapped_column(String(16), default="filename")  # filename | metadata | user
    # None means "not reliably extracted" – never fabricated.
    author: Mapped[str | None] = mapped_column(String(500))
    original_language: Mapped[str | None] = mapped_column(String(16))
    detected_language: Mapped[str | None] = mapped_column(String(16))
    file_format: Mapped[str] = mapped_column(String(10))
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"))
    content_hash: Mapped[str] = mapped_column(String(64))
    processing_status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    learning_status: Mapped[str] = mapped_column(String(32), default="not_started")
    extraction_quality: Mapped[float | None] = mapped_column(Float)
    extraction_warnings: Mapped[list] = mapped_column(JSONType, default=list)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    structure_confidence: Mapped[float | None] = mapped_column(Float)
    processing_version: Mapped[str] = mapped_column(String(32), default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_file: Mapped[SourceFile | None] = relationship()
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="book", order_by="Chapter.ordinal", cascade="all, delete-orphan", passive_deletes=True
    )


class Chapter(IdMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("book_id", "ordinal", name="uq_chapter_order"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    start_location: Mapped[dict] = mapped_column(JSONType, default=dict)
    end_location: Mapped[dict] = mapped_column(JSONType, default=dict)
    detection_method: Mapped[str] = mapped_column(String(32))
    detection_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    content_hash: Mapped[str] = mapped_column(String(64))
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    book: Mapped[Book] = relationship(back_populates="chapters")


class DocumentChunk(IdMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("book_id", "ordinal", name="uq_chunk_order"),
        Index("ix_chunks_book_chapter", "book_id", "chapter_id"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    text_content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    source_start_location: Mapped[dict] = mapped_column(JSONType, default=dict)
    source_end_location: Mapped[dict] = mapped_column(JSONType, default=dict)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    page_label_start: Mapped[str | None] = mapped_column(String(32))
    page_label_end: Mapped[str | None] = mapped_column(String(32))
    section_title: Mapped[str | None] = mapped_column(String(500))
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType())
    content_hash: Mapped[str] = mapped_column(String(64))
    extraction_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceReference(IdMixin, Base):
    __tablename__ = "evidence_references"
    __table_args__ = (Index("ix_evidence_book_chunk", "book_id", "chunk_id"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(10))  # pdf | epub
    page_label: Mapped[str | None] = mapped_column(String(32))
    page_index: Mapped[int | None] = mapped_column(Integer)
    epub_location: Mapped[str | None] = mapped_column(String(500))
    character_start: Mapped[int | None] = mapped_column(Integer)
    character_end: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str] = mapped_column(Text)
    document_version: Mapped[str] = mapped_column(String(64), default="")
    extraction_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingJob(IdMixin, Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_jobs_book_type", "book_id", "job_type"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(40))  # ingest | summary | question_bank
    target_id: Mapped[uuid.UUID | None] = mapped_column()  # e.g. summary id or chapter id
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|succeeded|failed|cancelled
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)
    stage_timings: Mapped[dict] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
