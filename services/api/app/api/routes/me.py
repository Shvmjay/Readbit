from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.cookies import clear_auth_cookies
from app.api.deps import db_session, optional_actor, require_actor, require_user
from app.api.serializers import iso, serialize_book, serialize_user
from app.models.books import Book, Chapter
from app.models.content import Annotation, ReadingState
from app.models.learning import Achievement, QuizSession, Topic, TopicMastery, UserAchievement
from app.schemas.api import DeleteAccountBody, PreferencesBody
from app.services import learning_service as ls
from app.services.actors import CurrentActor
from app.services.annotation_service import serialize_annotation, serialize_reading_state
from app.services.book_service import latest_job
from app.services.quiz_service import serialize_session
from app.services.retention import delete_user_account

router = APIRouter(prefix="/api/v1", tags=["me"])


@router.get("/me", summary="Current identity (user, guest or anonymous)")
def me(actor: CurrentActor | None = Depends(optional_actor)) -> dict:
    if actor is None:
        return {"authenticated": False, "guest": False, "user": None}
    if actor.user:
        return {"authenticated": True, "guest": False, "user": serialize_user(actor.user)}
    assert actor.guest is not None
    return {
        "authenticated": True,
        "guest": True,
        "user": None,
        "guest_expires_at": iso(actor.guest.expires_at),
        "preferred_language": actor.guest.preferred_language,
    }


@router.patch("/me/preferences", summary="Update preferences")
def update_preferences(
    body: PreferencesBody, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
) -> dict:
    if actor.user is None:
        assert actor.guest is not None
        if body.preferred_language:
            actor.guest.preferred_language = body.preferred_language
            db.commit()
        return {"guest": True, "preferred_language": actor.guest.preferred_language}
    user = actor.user
    for field in ("preferred_language", "content_language", "theme_preference", "daily_goal_questions"):
        value = getattr(body, field)
        if value is not None:
            setattr(user, field, value)
    if body.display_name is not None:
        user.display_name = body.display_name.strip()[:120]
    db.commit()
    return {"user": serialize_user(user)}


@router.delete("/me", summary="Delete my account and all my data")
def delete_me(
    body: DeleteAccountBody,
    response: Response,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_user),
) -> dict:
    assert actor.user is not None
    delete_user_account(db, actor.user)
    clear_auth_cookies(response, guest=True)
    return {"deleted": True}


@router.get("/me/export", summary="Export my data (JSON): library metadata, notes, progress")
def export_me(db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    books = list(db.scalars(select(Book).where(actor.owns(Book), Book.deleted_at.is_(None))))
    return {
        "user": serialize_user(actor.user) if actor.user else None,
        "books": [serialize_book(b) for b in books],
        "annotations": [
            serialize_annotation(a) for a in db.scalars(select(Annotation).where(actor.owns(Annotation)))
        ],
        "quiz_sessions": [
            serialize_session(s) for s in db.scalars(select(QuizSession).where(actor.owns(QuizSession)))
        ],
        "note": "Uploaded files are not included; you already have the originals.",
    }


@router.get("/me/dashboard", summary="Dashboard: recent books, continue reading/learning, weak concepts")
def dashboard(db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    books = list(
        db.scalars(
            select(Book)
            .where(actor.owns(Book), Book.deleted_at.is_(None))
            .order_by(Book.updated_at.desc())
            .limit(12)
        )
    )
    by_id = {b.id: b for b in books}
    states = list(
        db.scalars(
            select(ReadingState)
            .where(ReadingState.actor_key == actor.key)
            .order_by(ReadingState.updated_at.desc())
            .limit(5)
        )
    )
    continue_reading = []
    for st in states:
        b = by_id.get(st.book_id) or db.get(Book, st.book_id)
        if b is None:
            continue
        ch = db.get(Chapter, st.last_chapter_id) if st.last_chapter_id else None
        continue_reading.append(
            {
                "book": {"id": str(b.id), "title": b.title},
                "chapter": {"id": str(ch.id), "title": ch.title} if ch else None,
                "state": serialize_reading_state(st),
                "chapters_total": b.chapter_count,
            }
        )
    sessions = list(
        db.scalars(
            select(QuizSession)
            .where(actor.owns(QuizSession))
            .order_by(QuizSession.started_at.desc())
            .limit(20)
        )
    )
    active = next((s for s in sessions if s.status in ("active", "preparing")), None)
    recent_completed = []
    for s in sessions:
        if s.status == "completed" and s.chapter_id and len(recent_completed) < 5:
            ch = db.get(Chapter, s.chapter_id)
            b = db.get(Book, s.book_id)
            if ch and b:
                recent_completed.append(
                    {
                        "book_id": str(b.id),
                        "book_title": b.title,
                        "chapter_title": ch.title,
                        "correct": s.correct_count,
                        "answered": s.answered_count,
                        "completed_at": iso(s.completed_at),
                    }
                )
    weak = []
    for m in db.scalars(
        select(TopicMastery).where(TopicMastery.actor_key == actor.key).order_by(TopicMastery.mastery_score)
    ):
        if ls.is_weak(m) and len(weak) < 6:
            t = db.get(Topic, m.topic_id)
            b = db.get(Book, m.book_id)
            if t and b:
                weak.append(
                    {
                        "topic": t.title,
                        "book_id": str(b.id),
                        "book_title": b.title,
                        "mastery_score": m.mastery_score,
                    }
                )
    total_answered = sum(s.answered_count for s in sessions)
    total_correct = sum(s.correct_count for s in sessions)
    goal = actor.user.daily_goal_questions if actor.user else 10
    return {
        "recent_books": [serialize_book(b, latest_job(db, b.id)) for b in books],
        "continue_reading": continue_reading,
        "continue_learning": {
            **serialize_session(active),
            "book_title": by_id[active.book_id].title if active.book_id in by_id else None,
        }
        if active
        else None,
        "recently_completed_lessons": recent_completed,
        "weak_concepts": weak,
        "totals": {
            "books": len(books),
            "questions_answered_recent": total_answered,
            "correct_recent": total_correct,
        },
        "streak_days": ls.streak_days(db, actor),
        "daily_goal": {"target": goal, "answered_today": ls.answered_today(db, actor)},
        "guest_expires_at": iso(actor.guest.expires_at) if actor.is_guest and actor.guest else None,
    }


@router.get("/users/me/achievements", summary="Achievements (earned and available)")
def achievements(db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    earned = {
        ua.achievement_id: ua
        for ua in db.scalars(select(UserAchievement).where(UserAchievement.actor_key == actor.key))
    }
    items = []
    for a in db.scalars(select(Achievement).order_by(Achievement.created_at)):
        ua = earned.get(a.id)
        items.append(
            {
                "code": a.code,
                "name": a.name,
                "description": a.description,
                "icon_key": a.icon_key,
                "earned": ua is not None,
                "earned_at": iso(ua.earned_at) if ua else None,
            }
        )
    return {"achievements": items}
