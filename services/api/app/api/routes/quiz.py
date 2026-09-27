from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ai_rate_limited, db_session, require_actor
from app.core.errors import not_found
from app.models.books import ProcessingJob
from app.models.content import ReadingState
from app.models.learning import QuizSession, SessionQuestion, Topic, TopicMastery
from app.schemas.api import AnswerBody, QuizSessionCreate
from app.services import book_service as bs
from app.services import learning_service as ls
from app.services import quiz_service as qs
from app.services.actors import CurrentActor

router = APIRouter(prefix="/api/v1", tags=["quizzer"])


@router.get("/books/{book_id}/lessons", summary="Chapter lessons with question-bank and progress status")
def lessons(
    book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    stats = ls.chapter_stats(db, actor, book)
    items = []
    for ch in bs.chapters(db, book):
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.job_type == "question_bank", ProcessingJob.target_id == ch.id)
            .order_by(ProcessingJob.created_at.desc())
        )
        st = stats[ch.id]
        bank = "ready" if st["approved_questions"] else "none"
        if job is not None and job.status in ("queued", "running"):
            bank = "generating"
        elif job is not None and job.status == "failed" and not st["approved_questions"]:
            bank = "failed"
        items.append(
            {
                "chapter_id": str(ch.id),
                "ordinal": ch.ordinal,
                "title": ch.title,
                "bank_status": bank,
                "approved_questions": st["approved_questions"],
                "questions_answered": st["answered"],
                "correct": st["correct"],
                "accuracy": round(st["correct"] / st["answered"], 3) if st["answered"] else None,
                "lessons_completed": st["lessons_completed"],
                "completed": st["completed"],
            }
        )
    return {"items": items, "learning_status": book.learning_status}


def _owned_session(db: Session, actor: CurrentActor, session_id: uuid.UUID) -> QuizSession:
    s = db.scalar(select(QuizSession).where(QuizSession.id == session_id, actor.owns(QuizSession)))
    if s is None:
        raise not_found("Quiz session")
    return s


def _session_view(db: Session, actor: CurrentActor, s: QuizSession) -> dict:
    s = qs.refresh_session(db, actor, s)
    q = qs.current_question(db, actor, s)
    position = None
    if q is not None:
        sq = db.scalar(
            select(SessionQuestion).where(
                SessionQuestion.quiz_session_id == s.id, SessionQuestion.question_id == q.id
            )
        )
        position = sq.position if sq else None
    return {
        "session": qs.serialize_session(s),
        "question": qs.serialize_question(q, position=position) if q else None,
    }


@router.post(
    "/books/{book_id}/quiz-sessions",
    summary="Start a chapter lesson (continues where you left off if no chapter given)",
)
def start_session(
    book_id: uuid.UUID,
    body: QuizSessionCreate,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(ai_rate_limited),
):
    book = bs.get_owned_book(db, actor, book_id)
    s = qs.start_lesson(db, actor, book, body.chapter_id)
    return JSONResponse(_session_view(db, actor, s), status_code=201)


@router.post(
    "/books/{book_id}/revision-sessions", summary="Start a revision session on weak concepts (reuse allowed)"
)
def start_revision(
    book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
):
    book = bs.get_owned_book(db, actor, book_id)
    s = qs.start_revision(db, actor, book)
    return JSONResponse(_session_view(db, actor, s), status_code=201)


@router.get(
    "/quiz-sessions/{session_id}",
    summary="Session state and the current question (answer key never included)",
)
def get_session(
    session_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
) -> dict:
    return _session_view(db, actor, _owned_session(db, actor, session_id))


@router.post(
    "/quiz-sessions/{session_id}/answers", summary="Submit an answer (idempotent; first submission is final)"
)
def answer(
    session_id: uuid.UUID,
    body: AnswerBody,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_actor),
) -> dict:
    s = _owned_session(db, actor, session_id)
    return qs.submit_answer(
        db, actor, s, body.question_id, body.selected_option_key, body.response_duration_ms
    )


@router.get("/books/{book_id}/progress", summary="Reading and learning progress for a book")
def progress(
    book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    stats = ls.chapter_stats(db, actor, book)
    state = db.scalar(
        select(ReadingState).where(ReadingState.book_id == book.id, ReadingState.actor_key == actor.key)
    )
    answered = sum(s["answered"] for s in stats.values())
    correct = sum(s["correct"] for s in stats.values())
    return {
        "reading": {
            "chapters_total": book.chapter_count,
            "chapters_read": len(state.chapters_read or []) if state else 0,
        },
        "learning": {
            "chapters_total": book.chapter_count,
            "chapters_completed": sum(1 for s in stats.values() if s["completed"]),
            "lessons_completed": sum(s["lessons_completed"] for s in stats.values()),
            "questions_answered": answered,
            "correct": correct,
            "question_accuracy": round(correct / answered, 3) if answered else None,
            "note": "Question accuracy measures answers in Readbit lessons; it is not a measure of long-term retention.",
        },
        "chapters": {str(k): v for k, v in stats.items()},
    }


@router.get("/books/{book_id}/mastery", summary="Topic-level mastery estimates and review schedule")
def mastery(
    book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    rows = db.execute(
        select(TopicMastery, Topic)
        .join(Topic, Topic.id == TopicMastery.topic_id)
        .where(TopicMastery.actor_key == actor.key, TopicMastery.book_id == book.id)
    ).all()
    items = [
        {
            "topic_id": str(t.id),
            "topic": t.title,
            "chapter_id": str(t.chapter_id) if t.chapter_id else None,
            "mastery_score": m.mastery_score,
            "confidence": m.confidence_level,
            "attempts": m.attempts_count,
            "correct": m.correct_count,
            "weak": ls.is_weak(m),
            "next_review_at": m.next_review_at.isoformat() if m.next_review_at else None,
        }
        for m, t in rows
    ]
    items.sort(key=lambda i: i["mastery_score"])
    return {
        "items": items,
        "method": "Exponentially weighted accuracy per topic (α=0.35), weighted by difficulty. "
        "An estimate from quiz answers, not a validated measure of knowledge.",
    }
