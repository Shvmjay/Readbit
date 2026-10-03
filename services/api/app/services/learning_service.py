"""Learning state: topic mastery, adaptive difficulty, spaced review, progress and achievements.

All rules are transparent and rule-based (no trained personalization model). See docs/AI_GROUNDING.md §Adaptive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.books import Book, Chapter
from app.models.content import ReadingState
from app.models.learning import (
    Achievement,
    Question,
    QuestionAttempt,
    QuizSession,
    Topic,
    TopicMastery,
    UserAchievement,
)
from app.services.actors import CurrentActor
from app.services.analytics import track

# --- Tunable, documented parameters
MASTERY_ALPHA = 0.35  # EWMA learning rate
DIFFICULTY_CREDIT = {1: 0.85, 2: 0.95, 3: 1.0}  # a correct hard answer counts more than an easy one
WEAK_THRESHOLD = 0.6
CHAPTER_COMPLETE_ACCURACY = 0.6
REVIEW_GROWTH = 2.2
RETRY_DELAY = timedelta(minutes=10)
SLOW_RESPONSE_MS = 45_000

ACHIEVEMENTS = [
    (
        "first_book",
        "First book on the shelf",
        "Your first book finished processing.",
        "book",
        {"books_ready": 1},
    ),
    ("first_summary", "Summary reader", "You opened your first summary.", "scroll", {"summaries_opened": 1}),
    ("first_lesson", "First lesson", "You completed your first lesson.", "sparkle", {"lessons_completed": 1}),
    (
        "perfect_lesson",
        "Flawless",
        "You answered every question in a lesson correctly (3+ questions).",
        "star",
        {"lesson_accuracy": 1.0, "min_questions": 3},
    ),
    (
        "chapter_complete",
        "Chapter complete",
        "You completed a chapter's lessons with at least 60% accuracy.",
        "flag",
        {"chapter_accuracy": 0.6},
    ),
    (
        "ten_correct",
        "Ten right answers",
        "You answered ten questions correctly.",
        "target",
        {"correct_answers": 10},
    ),
    ("revision_done", "Comeback", "You completed a revision session.", "refresh", {"revision_sessions": 1}),
    (
        "three_day_streak",
        "Three-day streak",
        "You practised on three consecutive days.",
        "flame",
        {"streak_days": 3},
    ),
    (
        "book_mastered",
        "Book complete",
        "You completed the lessons for every chapter of a book.",
        "trophy",
        {"all_chapters": True},
    ),
]


def seed_achievements(db: Session) -> None:
    existing = {a.code: a for a in db.scalars(select(Achievement))}
    for code, name, desc, icon, criteria in ACHIEVEMENTS:
        if code in existing:
            a = existing[code]
            a.name, a.description, a.icon_key, a.criteria_json = name, desc, icon, criteria
        else:
            db.add(Achievement(code=code, name=name, description=desc, icon_key=icon, criteria_json=criteria))
    db.commit()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def get_mastery(db: Session, actor: CurrentActor, topic_id: uuid.UUID) -> TopicMastery | None:
    return db.scalar(
        select(TopicMastery).where(TopicMastery.topic_id == topic_id, TopicMastery.actor_key == actor.key)
    )


def update_mastery(
    db: Session, actor: CurrentActor, question: Question, correct: bool
) -> TopicMastery | None:
    if question.topic_id is None:
        return None
    m = get_mastery(db, actor, question.topic_id)
    if m is None:
        m = TopicMastery(
            actor_key=actor.key, book_id=question.book_id, topic_id=question.topic_id, **actor.owner_fields()
        )
        db.add(m)
    outcome = DIFFICULTY_CREDIT.get(question.difficulty, 1.0) if correct else 0.0
    prev = m.mastery_score or 0.0
    m.mastery_score = round(prev + MASTERY_ALPHA * (outcome - prev), 4)
    m.attempts_count = (m.attempts_count or 0) + 1
    m.correct_count = (m.correct_count or 0) + (1 if correct else 0)
    m.confidence_level = round(1 - 0.7**m.attempts_count, 4)
    now = _now()
    m.last_practiced_at = now
    if correct:
        m.review_interval_days = (
            1.0 if not m.review_interval_days else round(m.review_interval_days * REVIEW_GROWTH, 2)
        )
        m.next_review_at = now + timedelta(days=m.review_interval_days)
    else:
        m.review_interval_days = 0.0
        m.next_review_at = now + RETRY_DELAY
    db.flush()
    return m


def next_difficulty(current: int, recent: list[bool], durations: list[int | None]) -> int:
    """Rule-based adaptation over the most recent answers in the session (newest last)."""
    if len(recent) < 2:
        return current
    window = recent[-4:]
    acc = sum(window) / len(window)
    last_two = recent[-2:]
    slow = durations and durations[-1] is not None and durations[-1] > SLOW_RESPONSE_MS
    if all(last_two) and acc >= 0.75 and not slow:
        return min(3, current + 1)
    if not any(last_two) or acc <= 0.4:
        return max(1, current - 1)
    return current


def initial_difficulty(
    db: Session, actor: CurrentActor, book_id: uuid.UUID, chapter_id: uuid.UUID | None
) -> int:
    stmt = select(func.avg(TopicMastery.mastery_score)).where(
        TopicMastery.actor_key == actor.key, TopicMastery.book_id == book_id
    )
    if chapter_id is not None:
        stmt = stmt.join(Topic, Topic.id == TopicMastery.topic_id).where(Topic.chapter_id == chapter_id)
    avg = db.scalar(stmt)
    if avg is None:
        return 1
    return 1 if avg < 0.4 else 2 if avg < 0.75 else 3


def is_weak(m: TopicMastery, now: datetime | None = None) -> bool:
    now = now or _now()
    due = _aware(m.next_review_at)
    return m.attempts_count > 0 and (
        m.mastery_score < WEAK_THRESHOLD or (due is not None and due <= now and m.mastery_score < 0.85)
    )


def actor_sessions(db: Session, actor: CurrentActor, book_id: uuid.UUID | None = None):
    stmt = select(QuizSession).where(actor.owns(QuizSession))
    if book_id is not None:
        stmt = stmt.where(QuizSession.book_id == book_id)
    return stmt


def chapter_stats(db: Session, actor: CurrentActor, book: Book) -> dict[uuid.UUID, dict]:
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)))
    stats = {
        ch.id: {"answered": 0, "correct": 0, "lessons_completed": 0, "completed": False, "best_accuracy": 0.0}
        for ch in chapters
    }
    sessions = list(db.scalars(actor_sessions(db, actor, book.id)))
    for s in sessions:
        if s.chapter_id in stats and s.session_type == "lesson":
            st = stats[s.chapter_id]
            st["answered"] += s.answered_count
            st["correct"] += s.correct_count
            if s.status == "completed" and s.answered_count:
                st["lessons_completed"] += 1
                acc = s.correct_count / s.answered_count
                st["best_accuracy"] = max(st["best_accuracy"], acc)
                if acc >= CHAPTER_COMPLETE_ACCURACY:
                    st["completed"] = True
    counts = dict(
        db.execute(
            select(Question.chapter_id, func.count())
            .where(Question.book_id == book.id, Question.validation_status == "approved")
            .group_by(Question.chapter_id)
        ).all()
    )
    for cid, st in stats.items():
        st["approved_questions"] = int(counts.get(cid, 0))
    return stats


def streak_days(db: Session, actor: CurrentActor) -> int:
    rows = db.scalars(
        select(QuestionAttempt.answered_at)
        .join(QuizSession, QuizSession.id == QuestionAttempt.quiz_session_id)
        .where(actor.owns(QuizSession))
    ).all()
    days = {(_aware(r) or _now()).date() for r in rows}
    if not days:
        return 0
    today = _now().date()
    cur = today if today in days else today - timedelta(days=1)
    n = 0
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def answered_today(db: Session, actor: CurrentActor) -> int:
    start = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
    return int(
        db.scalar(
            select(func.count())
            .select_from(QuestionAttempt)
            .join(QuizSession, QuizSession.id == QuestionAttempt.quiz_session_id)
            .where(actor.owns(QuizSession), QuestionAttempt.answered_at >= start)
        )
        or 0
    )


def _award(db: Session, actor: CurrentActor, code: str, book_id: uuid.UUID | None = None) -> dict | None:
    ach = db.scalar(select(Achievement).where(Achievement.code == code))
    if ach is None:
        return None
    scope = str(book_id) if book_id and code in ("chapter_complete", "book_mastered") else "global"
    exists = db.scalar(
        select(UserAchievement).where(
            UserAchievement.achievement_id == ach.id,
            UserAchievement.actor_key == actor.key,
            UserAchievement.scope_key == scope,
        )
    )
    if exists:
        return None
    db.add(
        UserAchievement(
            achievement_id=ach.id,
            actor_key=actor.key,
            scope_key=scope,
            book_id=book_id if scope != "global" else None,
            **actor.owner_fields(),
        )
    )
    db.flush()
    track(db, "achievement_earned", actor.key, book_id, achievement=code)
    return {"code": ach.code, "name": ach.name, "description": ach.description, "icon_key": ach.icon_key}


def evaluate_achievements(
    db: Session, actor: CurrentActor, book: Book | None = None, session: QuizSession | None = None
) -> list[dict]:
    earned: list[dict] = []

    def add(code: str, book_id=None):
        r = _award(db, actor, code, book_id)
        if r:
            earned.append(r)

    if db.scalar(
        select(func.count())
        .select_from(Book)
        .where(actor.owns(Book), Book.processing_status == "ready", Book.deleted_at.is_(None))
    ):
        add("first_book")
    if db.scalar(
        select(func.count())
        .select_from(ReadingState)
        .where(ReadingState.actor_key == actor.key, ReadingState.last_view == "summary")
    ):
        add("first_summary")
    sessions = list(db.scalars(actor_sessions(db, actor)))
    completed = [s for s in sessions if s.status == "completed"]
    if any(s.session_type == "lesson" for s in completed):
        add("first_lesson")
    if (
        session is not None
        and session.status == "completed"
        and session.answered_count >= 3
        and session.correct_count == session.answered_count
        and session.session_type == "lesson"
    ):
        add("perfect_lesson")
    if any(s.session_type == "revision" for s in completed):
        add("revision_done")
    if sum(s.correct_count for s in sessions) >= 10:
        add("ten_correct")
    if streak_days(db, actor) >= 3:
        add("three_day_streak")
    if book is not None:
        stats = chapter_stats(db, actor, book)
        if any(st["completed"] for st in stats.values()):
            add("chapter_complete", book.id)
        if stats and all(st["completed"] for st in stats.values()):
            add("book_mastered", book.id)
    return earned
