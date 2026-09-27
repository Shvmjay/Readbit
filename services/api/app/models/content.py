"""Generated summaries, their evidence links, annotations and reading state."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TimestampMixin, utcnow
from app.models.books import OWNER_CHECK


class Summary(IdMixin, TimestampMixin, Base):
    __tablename__ = "summaries"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'book' AND chapter_id IS NULL) OR (scope = 'chapter' AND chapter_id IS NOT NULL)",
            name="summary_scope",
        ),
        Index("ix_summaries_lookup", "book_id", "chapter_id", "depth", "output_language"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(10))  # book | chapter
    depth: Mapped[str] = mapped_column(String(16))  # concise | balanced | comprehensive
    output_language: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|generating|ready|failed
    content_json: Mapped[dict | None] = mapped_column(JSONType)
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    model_provider: Mapped[str | None] = mapped_column(String(40))
    model_name: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    token_usage: Mapped[dict] = mapped_column(JSONType, default=dict)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    generation_duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)


class SummaryEvidence(IdMixin, Base):
    __tablename__ = "summary_evidence"

    summary_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("summaries.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_references.id", ondelete="CASCADE"))
    section_key: Mapped[str] = mapped_column(String(80))
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Annotation(IdMixin, TimestampMixin, Base):
    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint(OWNER_CHECK, name="annotation_single_owner"),
        CheckConstraint("annotation_type IN ('highlight','bookmark','note')", name="annotation_type"),
        Index("ix_annotations_book", "book_id"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guest_sessions.id", ondelete="CASCADE"))
    annotation_type: Mapped[str] = mapped_column(String(16))
    # {"kind": "passage"|"summary", "chunk_id"?, "chapter_id"?, "summary_id"?, "section_key"?, "start"?, "end"?}
    source_location: Mapped[dict] = mapped_column(JSONType, default=dict)
    selected_text: Mapped[str | None] = mapped_column(Text)
    note_text: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(16))


class ReadingState(IdMixin, Base):
    """Where an actor left off in a book and which chapters they have read."""

    __tablename__ = "reading_states"
    __table_args__ = (
        CheckConstraint(OWNER_CHECK, name="reading_single_owner"),
        UniqueConstraint("book_id", "actor_key", name="uq_reading_state_actor"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guest_sessions.id", ondelete="CASCADE"))
    actor_key: Mapped[str] = mapped_column(String(40))  # "u:<uuid>" or "g:<uuid>"; NULL-safe uniqueness
    last_view: Mapped[str] = mapped_column(String(16), default="summary")  # summary | source
    last_chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    last_depth: Mapped[str] = mapped_column(String(16), default="balanced")
    last_position: Mapped[dict] = mapped_column(JSONType, default=dict)
    chapters_read: Mapped[list] = mapped_column(JSONType, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
