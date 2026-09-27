"""Quizzer: topics, questions, sessions, attempts, mastery and achievements."""

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
from app.models.types import EmbeddingType


class Topic(IdMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (Index("ix_topics_book_chapter", "book_id", "chapter_id"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    parent_topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    source_evidence_ids: Mapped[list] = mapped_column(JSONType, default=list)
    difficulty_estimate: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Question(IdMixin, TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("question_type IN ('recall','comprehension','application','inference')", name="qtype"),
        CheckConstraint("difficulty BETWEEN 1 AND 3", name="qdifficulty"),
        CheckConstraint("correct_option_key IN ('A','B','C','D')", name="qcorrect_key"),
        Index("ix_questions_bank", "book_id", "chapter_id", "validation_status", "language"),
        Index("ix_questions_fingerprint", "book_id", "semantic_fingerprint"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    question_text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(16))
    difficulty: Mapped[int] = mapped_column(Integer)  # 1 easy, 2 medium, 3 hard
    options_json: Mapped[list] = mapped_column(JSONType)  # [{"key":"A","text":"..."}, ...] exactly four
    correct_option_key: Mapped[str] = mapped_column(String(1))
    explanation: Mapped[str] = mapped_column(Text)
    misconception: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSONType, default=list)
    language: Mapped[str] = mapped_column(String(8), default="en")
    generation_method: Mapped[str] = mapped_column(String(16))  # bank | dynamic
    validation_status: Mapped[str] = mapped_column(String(16), default="pending")  # approved|rejected|pending
    validation_report: Mapped[dict] = mapped_column(JSONType, default=dict)
    semantic_fingerprint: Mapped[str] = mapped_column(String(64))
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType())
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    model_provider: Mapped[str | None] = mapped_column(String(40))
    model_name: Mapped[str | None] = mapped_column(String(80))


class QuizSession(IdMixin, Base):
    __tablename__ = "quiz_sessions"
    __table_args__ = (
        CheckConstraint(OWNER_CHECK, name="quiz_single_owner"),
        CheckConstraint("session_type IN ('lesson','revision')", name="session_type"),
        Index("ix_quiz_sessions_book", "book_id"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guest_sessions.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    session_type: Mapped[str] = mapped_column(String(16), default="lesson")
    status: Mapped[str] = mapped_column(String(16), default="preparing")  # preparing|active|completed|unavailable
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str] = mapped_column(String(8), default="en")
    question_count: Mapped[int] = mapped_column(Integer, default=5)
    answered_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    status_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionQuestion(IdMixin, Base):
    """Order in which questions were served in a session."""

    __tablename__ = "session_questions"
    __table_args__ = (
        UniqueConstraint("quiz_session_id", "position", name="uq_session_position"),
        UniqueConstraint("quiz_session_id", "question_id", name="uq_session_question"),
    )

    quiz_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quiz_sessions.id", ondelete="CASCADE"))
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    served_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuestionAttempt(IdMixin, Base):
    __tablename__ = "question_attempts"
    __table_args__ = (
        # One graded attempt per question per session: resubmissions are idempotent.
        UniqueConstraint("quiz_session_id", "question_id", "attempt_number", name="uq_attempt"),
        Index("ix_attempts_question", "question_id"),
    )

    quiz_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quiz_sessions.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    selected_option_key: Mapped[str] = mapped_column(String(1))
    is_correct: Mapped[bool] = mapped_column()
    response_duration_ms: Mapped[int | None] = mapped_column(Integer)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TopicMastery(IdMixin, Base):
    __tablename__ = "topic_mastery"
    __table_args__ = (
        CheckConstraint(OWNER_CHECK, name="mastery_single_owner"),
        UniqueConstraint("topic_id", "actor_key", name="uq_mastery_actor_topic"),
        Index("ix_mastery_book", "book_id"),
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guest_sessions.id", ondelete="CASCADE"))
    actor_key: Mapped[str] = mapped_column(String(40))
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[float] = mapped_column(Float, default=0.0)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    review_interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Achievement(IdMixin, Base):
    __tablename__ = "achievements"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    criteria_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    icon_key: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserAchievement(IdMixin, Base):
    __tablename__ = "user_achievements"
    __table_args__ = (
        CheckConstraint(OWNER_CHECK, name="user_achievement_single_owner"),
        UniqueConstraint("achievement_id", "actor_key", "scope_key", name="uq_user_achievement"),
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guest_sessions.id", ondelete="CASCADE"))
    actor_key: Mapped[str] = mapped_column(String(40))
    scope_key: Mapped[str] = mapped_column(String(40), default="global")  # book id or "global"
    achievement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("achievements.id", ondelete="CASCADE"))
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


