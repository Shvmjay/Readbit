"""Privacy-conscious product analytics. Only allowlisted event names and non-content properties are stored."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import pseudonymous_id
from app.models.ops import AnalyticsEvent

EVENTS = {
    "landing_viewed", "onboarding_completed", "guest_session_started", "account_created", "book_upload_initiated",
    "book_upload_completed", "document_processing_completed", "document_processing_failed", "summary_generated",
    "chapter_summary_opened", "summary_depth_changed", "book_question_asked", "bookmark_created", "note_created",
    "highlight_created", "quiz_started", "question_answered", "answer_correct", "answer_incorrect",
    "explanation_opened", "lesson_completed", "chapter_completed", "revision_session_started", "achievement_earned",
    "user_returned", "source_citation_opened",
}
CLIENT_EVENTS = {"landing_viewed", "onboarding_completed", "explanation_opened", "user_returned", "source_citation_opened",
                 "chapter_summary_opened", "summary_depth_changed"}
ALLOWED_PROPS = {"format", "depth", "language", "question_type", "difficulty", "session_type", "achievement",
                 "answerable", "status", "stage", "error_code", "chapter_ordinal", "count", "view", "source"}


def track(db: Session, name: str, actor_key: str | None, book_id: uuid.UUID | None = None, **props: Any) -> None:
    if not get_settings().metrics_enabled or name not in EVENTS:
        return
    clean = {k: v for k, v in props.items() if k in ALLOWED_PROPS and isinstance(v, str | int | float | bool)}
    db.add(
        AnalyticsEvent(
            name=name,
            actor_pseudo_id=pseudonymous_id(actor_key) if actor_key else None,
            book_id=book_id,
            properties=clean,
        )
    )
