"""Operational records: AI executions (cost/latency) and privacy-conscious analytics events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, utcnow


class AIExecution(IdMixin, Base):
    """One model call. Never stores prompts or document text."""

    __tablename__ = "ai_executions"
    __table_args__ = (Index("ix_ai_exec_created", "created_at"), Index("ix_ai_exec_book", "book_id"))

    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guest_sessions.id", ondelete="SET NULL"))
    task_type: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    input_token_count: Mapped[int] = mapped_column(Integer, default=0)
    output_token_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(default=True)
    failure_category: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalyticsEvent(IdMixin, Base):
    """Product analytics with pseudonymous actor ids. Properties must never include book text, notes or questions."""

    __tablename__ = "analytics_events"
    __table_args__ = (Index("ix_analytics_name_time", "name", "created_at"),)

    name: Mapped[str] = mapped_column(String(64))
    actor_pseudo_id: Mapped[str | None] = mapped_column(String(32), index=True)
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"))
    properties: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
