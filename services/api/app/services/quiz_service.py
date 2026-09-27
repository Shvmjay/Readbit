"""Quizzer: hybrid question bank (validated bank + controlled dynamic generation), sessions and grading.

Pipeline for every candidate question:
  generate → structural checks → blind semantic validation → (explanation repair) → deduplication → persist.
Only approved questions are ever served. The stored answer key is authoritative at grading time; no model is
consulted to decide correctness.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embeddings import cosine, get_embedder
from app.ai.providers.extractive import _key_terms
from app.ai.retrieval import passage_id, render_passages
from app.ai.router import ModelRouter
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.document_processing.text import content_words, normalize_for_match
from app.models.books import Book, Chapter, DocumentChunk, ProcessingJob
from app.models.learning import Question, QuestionAttempt, QuizSession, SessionQuestion, Topic, TopicMastery
from app.services import learning_service as ls
from app.services.actors import CurrentActor
from app.services.analytics import track
from app.services.evidence import evidence_payload, get_or_create_evidence
from app.services.state_machine import learning_transition
from app.services.summary_service import book_output_language
from app.workers.dispatch import enqueue

log = get_logger("readbit.quiz")
BANK_TARGET_PER_CHAPTER = 12
MAX_ROUNDS = 3
KEYS = ("A", "B", "C", "D")
OFFLINE_TYPES = ["recall", "comprehension"]
ALL_TYPES = ["recall", "comprehension", "application", "inference"]


# ---------------------------------------------------------------- validation helpers
def structural_problems(cand: dict, valid_pids: set[str]) -> list[str]:
    problems = []
    q = (cand.get("question") or "").strip()
    opts = cand.get("options") or []
    if not q:
        problems.append("empty_question")
    if len(opts) != 4:
        problems.append("not_four_options")
    keys = [o.get("key") for o in opts]
    if sorted(keys) != list(KEYS):
        problems.append("option_keys_invalid")
    texts = [normalize_for_match(o.get("text", "")) for o in opts]
    if any(not t for t in texts):
        problems.append("empty_option")
    if len(set(texts)) != len(texts):
        problems.append("duplicate_options")
    if cand.get("correct_key") not in keys:
        problems.append("correct_key_invalid")
    if cand.get("question_type") not in ALL_TYPES:
        problems.append("invalid_type")
    if cand.get("difficulty") not in (1, 2, 3):
        problems.append("invalid_difficulty")
    if not [p for p in cand.get("evidence_ids", []) if p in valid_pids]:
        problems.append("no_valid_evidence")
    if not (cand.get("explanation") or "").strip():
        problems.append("missing_explanation")
    if any(t in normalize_for_match(q.split("“")[0]) for t in texts if len(t) > 12):
        problems.append("answer_in_stem")
    if opts and cand.get("correct_key") in keys:
        correct = next(o["text"] for o in opts if o["key"] == cand["correct_key"])
        others = [len(o["text"]) for o in opts if o["key"] != cand["correct_key"]]
        if others and len(correct) > 1.8 * (sum(others) / len(others)) and len(correct) > 40:
            problems.append("length_reveals_answer")
    return problems


def fingerprint(question_text: str, correct_text: str) -> str:
    words = sorted(set(content_words(question_text + " " + correct_text)))
    return hashlib.sha256(" ".join(words).encode()).hexdigest()


# ---------------------------------------------------------------- generation
def _chapter_passages(db: Session, chapter: Chapter, round_index: int) -> list[DocumentChunk]:
    chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.chapter_id == chapter.id).order_by(DocumentChunk.ordinal)))
    budget, window, used = 7000, [], 0
    if sum(c.token_count for c in chunks) <= budget:
        return chunks
    # Long chapters: rotate through windows so successive rounds cover different parts of the chapter.
    start = (round_index * max(1, len(chunks) // MAX_ROUNDS)) % len(chunks)
    for c in chunks[start:] + chunks[:start]:
        if used + c.token_count > budget:
            break
        window.append(c)
        used += c.token_count
    return sorted(window, key=lambda c: c.ordinal)


def _topic_for(db: Session, book: Book, chapter: Chapter, label: str, evidence_ids: list[str]) -> Topic:
    title = (label or "General").strip()[:300]
    norm = normalize_for_match(title)
    for t in db.scalars(select(Topic).where(Topic.book_id == book.id, Topic.chapter_id == chapter.id)):
        if normalize_for_match(t.title) == norm:
            t.source_evidence_ids = list(dict.fromkeys((t.source_evidence_ids or []) + evidence_ids))
            return t
    topic = Topic(book_id=book.id, chapter_id=chapter.id, title=title, source_evidence_ids=evidence_ids)
    db.add(topic)
    db.flush()
    return topic


def generate_questions(
    db: Session,
    book: Book,
    chapter: Chapter,
    *,
    count: int,
    method: str,
    seed: int = 0,
    round_index: int = 0,
) -> dict[str, int]:
    """Generate, validate, deduplicate and persist up to `count` new approved questions for a chapter."""
    settings = get_settings()
    router = ModelRouter(db)
    lang = book_output_language(book)
    chunks = _chapter_passages(db, chapter, round_index)
    if not chunks:
        return {"approved": 0, "rejected": 0}
    passages, rendered = render_passages(db, chunks)
    allowed = {passage_id(c): c for c in chunks}
    existing = list(db.scalars(select(Question).where(Question.book_id == book.id, Question.validation_status == "approved")))
    chapter_existing = [q for q in existing if q.chapter_id == chapter.id]
    avoid = [q.question_text for q in chapter_existing][-40:]
    other_text = [c.text_content for c in db.scalars(
        select(DocumentChunk).where(DocumentChunk.book_id == book.id, DocumentChunk.chapter_id != chapter.id).limit(60))]
    book_terms = _key_terms(other_text, 12) if other_text else []
    types = OFFLINE_TYPES if router.is_offline else ALL_TYPES
    result = router.generate(
        "quiz_question_generator",
        variables={
            "book_title": book.title, "chapter_title": chapter.title, "passages": rendered, "count": count + 2,
            "types": ", ".join(types), "difficulties": "a mix of 1, 2 and 3",
            "avoid": "\n".join(f"- {t}" for t in avoid) or "(none)",
        },
        context={"passages": passages, "count": count + 2, "chapter_title": _short_title(chapter), "avoid": avoid,
                 "book_terms": book_terms, "seed": seed, "source_language": book.detected_language},
        output_language=lang, source_language=book.detected_language, book_id=book.id,
    )
    embedder = get_embedder()
    existing_vecs = [(q.embedding, q) for q in chapter_existing if q.embedding]
    existing_norm = {q.normalized_text for q in existing}
    existing_fp = {q.semantic_fingerprint for q in existing}
    approved = rejected = 0
    for cand in result.data.get("questions", []):
        if approved >= count:
            break
        report: dict[str, Any] = {"structural": [], "semantic": {}, "dedup": None}
        problems = structural_problems(cand, set(allowed))
        report["structural"] = problems
        status = "approved"
        if problems:
            status = "rejected"
        else:
            blind = {"question": cand["question"], "options": cand["options"], "explanation": cand["explanation"]}
            v = router.generate(
                "quiz_question_validator",
                variables={"passages": rendered, "question": _render_question(blind)},
                context={"question": blind, "passages": passages},
                output_language=lang, source_language=book.detected_language, book_id=book.id,
            ).data
            report["semantic"] = {"validator_key": v["answer_key"], "checks": v["checks"], "reason": v["reason"]}
            checks = dict(v["checks"])
            if v["answer_key"] != cand["correct_key"]:
                status = "rejected"
                report["semantic"]["decision"] = "validator_disagrees_with_key"
            elif not all(val for k, val in checks.items() if k != "explanation_supports_answer"):
                status = "rejected"
                report["semantic"]["decision"] = "failed_checks"
            elif not checks.get("explanation_supports_answer", True):
                fixed = router.generate(
                    "answer_explainer",
                    variables={"passages": rendered, "question": _render_question(cand, include_key=True)},
                    context={"question": cand, "passages": passages},
                    output_language=lang, source_language=book.detected_language, book_id=book.id,
                ).data
                if fixed["explanation"].strip():
                    cand["explanation"] = fixed["explanation"]
                    cand["misconception"] = fixed["misconception"] or cand.get("misconception", "")
                    report["semantic"]["explanation_repaired"] = True
                else:
                    status = "rejected"
                    report["semantic"]["decision"] = "explanation_unsupported"
        correct_text = next((o["text"] for o in cand.get("options", []) if o.get("key") == cand.get("correct_key")), "")
        norm = normalize_for_match(cand.get("question", "") + " || " + correct_text)
        fp = fingerprint(cand.get("question", ""), correct_text)
        vec = embedder.embed([cand.get("question", "") + " " + correct_text])[0]
        if status == "approved":
            dup_reason = None
            if norm in existing_norm:
                dup_reason = "exact_text"
            elif fp in existing_fp:
                dup_reason = "fingerprint"
            else:
                for other_vec, other in existing_vecs:
                    sim = cosine(vec, other_vec)
                    other_correct = next((o["text"] for o in other.options_json if o["key"] == other.correct_option_key), "")
                    same_answer = normalize_for_match(other_correct) == normalize_for_match(correct_text)
                    same_evidence = bool(set(cand["evidence_ids"][:1]) & set(other.validation_report.get("passage_ids", [])[:1]))
                    if sim >= settings.dedup_similarity_threshold:
                        dup_reason = f"semantic_similarity:{sim:.2f}"
                        break
                    if same_answer and same_evidence:
                        dup_reason = "same_answer_and_evidence"
                        break
            if dup_reason:
                status = "rejected"
                report["dedup"] = dup_reason
        pids = [p for p in cand.get("evidence_ids", []) if p in allowed][:3]
        report["passage_ids"] = pids
        ev_ids = []
        if status == "approved":
            for pid in pids:
                ev, _ = get_or_create_evidence(db, book, allowed[pid], cand["question"] + " " + correct_text)
                ev_ids.append(str(ev.id))
        topic = _topic_for(db, book, chapter, cand.get("topic", ""), ev_ids) if status == "approved" else None
        if cand.get("correct_key") not in KEYS or len(cand.get("options", [])) != 4:
            rejected += 1
            log.info("question rejected before persistence", extra={"problems": problems})
            continue
        q = Question(
            book_id=book.id, chapter_id=chapter.id, topic_id=topic.id if topic else None,
            question_text=cand["question"].strip(),
            question_type=cand.get("question_type") if cand.get("question_type") in ALL_TYPES else "recall",
            difficulty=int(cand.get("difficulty", 2)) if cand.get("difficulty") in (1, 2, 3) else 2,
            options_json=[{"key": o["key"], "text": o["text"].strip()} for o in sorted(cand["options"], key=lambda o: o["key"])],
            correct_option_key=cand["correct_key"], explanation=cand.get("explanation", "").strip(),
            misconception=(cand.get("misconception") or "").strip() or None, evidence_ids=ev_ids, language=lang,
            generation_method=method, validation_status=status, validation_report=report,
            semantic_fingerprint=fp, normalized_text=norm, embedding=vec, prompt_version=result.prompt_version,
            model_provider=result.provider, model_name=result.model,
        )
        db.add(q)
        db.flush()
        if status == "approved":
            approved += 1
            existing_norm.add(norm)
            existing_fp.add(fp)
            existing_vecs.append((vec, q))
        else:
            rejected += 1
    db.flush()
    return {"approved": approved, "rejected": rejected}


def _short_title(chapter: Chapter) -> str:
    title = chapter.title
    if ":" in title and len(title.split(":")[0]) <= 20:
        return title.split(":")[0].strip()
    return f"“{title}”" if len(title) <= 60 else "this chapter"


def _render_question(q: dict, include_key: bool = False) -> str:
    lines = [q["question"]] + [f"{o['key']}. {o['text']}" for o in q["options"]]
    if include_key:
        lines.append(f"Correct answer: {q['correct_key']}")
    if q.get("explanation"):
        lines.append(f"Explanation: {q['explanation']}")
    return "\n".join(lines)


def request_question_bank(db: Session, book: Book, chapter: Chapter, *, needed: int, method: str) -> ProcessingJob:
    running = db.scalar(select(ProcessingJob).where(
        ProcessingJob.book_id == book.id, ProcessingJob.job_type == "question_bank", ProcessingJob.target_id == chapter.id,
        ProcessingJob.status.in_(("queued", "running"))))
    if running is not None:
        return running
    job = ProcessingJob(book_id=book.id, job_type="question_bank", target_id=chapter.id, params={"needed": needed, "method": method})
    db.add(job)
    if book.learning_status in ("not_started", "learning_ready", "learning_failed"):
        learning_transition(book, "generating_questions")
    db.commit()
    enqueue("question_bank", job.id)
    return job


def run_question_bank_job(job_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.status in ("succeeded", "cancelled"):
            return
        book = db.get(Book, job.book_id)
        chapter = db.get(Chapter, job.target_id)
        if book is None or chapter is None:
            job.status = "cancelled"
            db.commit()
            return
        job.status, job.attempts, job.started_at, job.stage = "running", job.attempts + 1, datetime.now(UTC), "generating_questions"
        db.commit()
        needed = int((job.params or {}).get("needed", BANK_TARGET_PER_CHAPTER))
        method = (job.params or {}).get("method", "bank")
        totals = {"approved": 0, "rejected": 0}
        try:
            for rnd in range(MAX_ROUNDS):
                if totals["approved"] >= needed:
                    break
                r = generate_questions(db, book, chapter, count=needed - totals["approved"], method=method,
                                       seed=job.attempts * 101 + rnd, round_index=rnd)
                totals["approved"] += r["approved"]
                totals["rejected"] += r["rejected"]
                job.stage = "validating_questions"
                if book.learning_status == "generating_questions":
                    learning_transition(book, "validating_questions")
                db.commit()
                if r["approved"] == 0 and r["rejected"] == 0:
                    break
            job.params = {**(job.params or {}), **totals}
            job.status, job.progress_percent, job.completed_at = "succeeded", 100, datetime.now(UTC)
            if book.learning_status in ("generating_questions", "validating_questions"):
                book.learning_status = "learning_ready"
            db.commit()
        except AppError as exc:
            db.rollback()
            job = db.get(ProcessingJob, job_id)
            book = db.get(Book, job.book_id)
            job.status, job.error_code, job.safe_error_message = "failed", str(exc.code), exc.message
            job.completed_at = datetime.now(UTC)
            if book and book.learning_status in ("generating_questions", "validating_questions"):
                book.learning_status = "learning_failed"
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("question bank crashed", extra={"job_id": str(job_id)})
            job = db.get(ProcessingJob, job_id)
            job.status, job.error_code = "failed", str(ErrorCode.INTERNAL)
            job.safe_error_message = "Questions could not be generated. Please retry."
            db.commit()


# ---------------------------------------------------------------- sessions
def _answered_question_ids(db: Session, actor: CurrentActor, book_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.scalars(
        select(QuestionAttempt.question_id).join(QuizSession, QuizSession.id == QuestionAttempt.quiz_session_id)
        .where(actor.owns(QuizSession), QuizSession.book_id == book_id)
    ))


def _unused_count(db: Session, actor: CurrentActor, book: Book, chapter: Chapter) -> int:
    answered = _answered_question_ids(db, actor, book.id)
    ids = set(db.scalars(select(Question.id).where(Question.chapter_id == chapter.id, Question.validation_status == "approved",
                                                   Question.language == book_output_language(book))))
    return len(ids - answered)


def start_lesson(db: Session, actor: CurrentActor, book: Book, chapter_id: uuid.UUID | None) -> QuizSession:
    if book.processing_status != "ready":
        raise AppError(ErrorCode.NOT_READY, "This book is still being processed.", status_code=409)
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)))
    if chapter_id is None:
        stats = ls.chapter_stats(db, actor, book)
        chapter = next((c for c in chapters if not stats[c.id]["completed"]), chapters[0] if chapters else None)
    else:
        chapter = next((c for c in chapters if c.id == chapter_id), None)
    if chapter is None:
        raise AppError(ErrorCode.NOT_FOUND, "Chapter not found.", status_code=404)
    size = get_settings().lesson_size
    session = QuizSession(
        book_id=book.id, chapter_id=chapter.id, session_type="lesson", status="preparing",
        difficulty=ls.initial_difficulty(db, actor, book.id, chapter.id), language=book_output_language(book),
        question_count=size, **actor.owner_fields(),
    )
    db.add(session)
    db.flush()
    unused = _unused_count(db, actor, book, chapter)
    if unused >= size:
        session.status = "active"
    else:
        has_bank = db.scalar(select(func.count()).select_from(Question).where(Question.chapter_id == chapter.id, Question.validation_status == "approved"))
        method = "dynamic" if has_bank else "bank"
        needed = BANK_TARGET_PER_CHAPTER if method == "bank" else max(size, size - unused + 2)
        request_question_bank(db, book, chapter, needed=needed, method=method)
    track(db, "quiz_started", actor.key, book.id, session_type="lesson", chapter_ordinal=chapter.ordinal)
    db.commit()
    return refresh_session(db, actor, session)


def start_revision(db: Session, actor: CurrentActor, book: Book) -> QuizSession:
    candidates = _revision_candidates(db, actor, book, exclude=set())
    if not candidates:
        raise AppError(ErrorCode.CONFLICT, "Nothing to revise yet: answer some questions first, and weak concepts will appear here.", status_code=409)
    size = get_settings().lesson_size
    session = QuizSession(
        book_id=book.id, chapter_id=None, session_type="revision", status="active",
        difficulty=ls.initial_difficulty(db, actor, book.id, None), language=book_output_language(book),
        question_count=min(size, len(candidates)), **actor.owner_fields(),
    )
    db.add(session)
    track(db, "revision_session_started", actor.key, book.id, session_type="revision")
    db.commit()
    return session


def _revision_candidates(db: Session, actor: CurrentActor, book: Book, exclude: set[uuid.UUID]) -> list[Question]:
    now = datetime.now(UTC)
    weak_topics = [m.topic_id for m in db.scalars(select(TopicMastery).where(TopicMastery.actor_key == actor.key, TopicMastery.book_id == book.id))
                   if ls.is_weak(m, now)]
    if not weak_topics:
        return []
    answered = _answered_question_ids(db, actor, book.id)
    qs = list(db.scalars(select(Question).where(Question.topic_id.in_(weak_topics), Question.validation_status == "approved")))
    # Revision explicitly allows reuse; prefer questions the reader got wrong, then any from weak topics.
    wrong = set(db.scalars(
        select(QuestionAttempt.question_id).join(QuizSession, QuizSession.id == QuestionAttempt.quiz_session_id)
        .where(actor.owns(QuizSession), QuizSession.book_id == book.id, QuestionAttempt.is_correct.is_(False))
    ))
    qs.sort(key=lambda q: (q.id not in wrong, q.id not in answered, hashlib.md5(str(q.id).encode()).hexdigest()))  # noqa: S324
    return [q for q in qs if q.id not in exclude]


def refresh_session(db: Session, actor: CurrentActor, session: QuizSession) -> QuizSession:
    """Advance a preparing lesson once its question bank job has finished."""
    if session.status != "preparing":
        return session
    book = db.get(Book, session.book_id)
    chapter = db.get(Chapter, session.chapter_id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.job_type == "question_bank", ProcessingJob.target_id == session.chapter_id)
                    .order_by(ProcessingJob.created_at.desc()))
    unused = _unused_count(db, actor, book, chapter)
    size = get_settings().lesson_size
    if unused >= size or (job is not None and job.status in ("succeeded", "failed", "cancelled")):
        if unused >= 1:
            session.status = "active"
            session.question_count = min(size, unused)
        else:
            session.status = "unavailable"
            session.status_message = (
                (job.safe_error_message if job and job.status == "failed" else None)
                or "No new validated questions could be created for this chapter. Invalid questions are never shown; "
                "try a revision session or another chapter."
            )
        db.commit()
    return session


def _served(db: Session, session: QuizSession) -> list[SessionQuestion]:
    return list(db.scalars(select(SessionQuestion).where(SessionQuestion.quiz_session_id == session.id).order_by(SessionQuestion.position)))


def _attempts(db: Session, session: QuizSession) -> list[QuestionAttempt]:
    return list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.quiz_session_id == session.id).order_by(QuestionAttempt.answered_at)))


def current_question(db: Session, actor: CurrentActor, session: QuizSession) -> Question | None:
    if session.status != "active":
        return None
    served = _served(db, session)
    answered = {a.question_id for a in _attempts(db, session)}
    pending = [s for s in served if s.question_id not in answered]
    if pending:
        return db.get(Question, pending[0].question_id)
    if session.answered_count >= session.question_count:
        return None
    served_ids = {s.question_id for s in served}
    book = db.get(Book, session.book_id)
    if session.session_type == "revision":
        pool = _revision_candidates(db, actor, book, exclude=served_ids)
    else:
        seen = _answered_question_ids(db, actor, session.book_id) | served_ids
        pool = [q for q in db.scalars(select(Question).where(Question.chapter_id == session.chapter_id, Question.validation_status == "approved",
                                                             Question.language == session.language)) if q.id not in seen]
    if not pool:
        session.question_count = session.answered_count
        _complete(db, actor, session)
        db.commit()
        return None
    mastery = {m.topic_id: m.mastery_score for m in db.scalars(select(TopicMastery).where(TopicMastery.actor_key == actor.key, TopicMastery.book_id == session.book_id))}
    last_type = db.get(Question, served[-1].question_id).question_type if served else None
    last_topic = db.get(Question, served[-1].question_id).topic_id if served else None

    def rank(q: Question):
        return (
            abs(q.difficulty - session.difficulty),
            q.topic_id == last_topic,
            mastery.get(q.topic_id, 0.0) if session.session_type == "lesson" else 0,
            q.question_type == last_type,
            hashlib.sha256(f"{session.id}{q.id}".encode()).hexdigest(),
        )

    q = min(pool, key=rank)
    db.add(SessionQuestion(quiz_session_id=session.id, question_id=q.id, position=len(served) + 1))
    db.commit()
    return q


def _complete(db: Session, actor: CurrentActor, session: QuizSession) -> list[dict]:
    if session.status == "completed":
        return []
    session.status = "completed"
    session.completed_at = datetime.now(UTC)
    book = db.get(Book, session.book_id)
    track(db, "lesson_completed", actor.key, session.book_id, session_type=session.session_type, count=session.answered_count)
    earned = ls.evaluate_achievements(db, actor, book, session)
    if session.session_type == "lesson" and session.chapter_id:
        stats = ls.chapter_stats(db, actor, book)
        if stats.get(session.chapter_id, {}).get("completed"):
            track(db, "chapter_completed", actor.key, session.book_id)
    return earned


def submit_answer(
    db: Session, actor: CurrentActor, session: QuizSession, question_id: uuid.UUID, selected: str, duration_ms: int | None
) -> dict:
    if selected not in KEYS:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Choose one of the four options.", status_code=422)
    served = db.scalar(select(SessionQuestion).where(SessionQuestion.quiz_session_id == session.id, SessionQuestion.question_id == question_id))
    if served is None:
        raise AppError(ErrorCode.NOT_FOUND, "This question is not part of the session.", status_code=404)
    question = db.get(Question, question_id)
    assert question is not None
    existing = db.scalar(select(QuestionAttempt).where(QuestionAttempt.quiz_session_id == session.id, QuestionAttempt.question_id == question_id))
    if existing is not None:
        # Idempotent: the first submission is final; replays return the original result.
        return _feedback(db, actor, session, question, existing, mastery=None, earned=[], already_answered=True)
    if session.status != "active":
        raise AppError(ErrorCode.CONFLICT, "This session is no longer active.", status_code=409)
    is_correct = selected == question.correct_option_key
    attempt = QuestionAttempt(quiz_session_id=session.id, question_id=question.id, selected_option_key=selected,
                              is_correct=is_correct, response_duration_ms=duration_ms if duration_ms and 0 < duration_ms < 3_600_000 else None)
    db.add(attempt)
    session.answered_count += 1
    session.correct_count += 1 if is_correct else 0
    mastery = ls.update_mastery(db, actor, question, is_correct)
    attempts = _attempts(db, session)
    session.difficulty = ls.next_difficulty(session.difficulty, [a.is_correct for a in attempts], [a.response_duration_ms for a in attempts])
    track(db, "question_answered", actor.key, session.book_id, question_type=question.question_type, difficulty=question.difficulty)
    track(db, "answer_correct" if is_correct else "answer_incorrect", actor.key, session.book_id)
    earned: list[dict] = []
    if session.answered_count >= session.question_count:
        earned = _complete(db, actor, session)
    else:
        earned = ls.evaluate_achievements(db, actor, None, session)
    db.commit()
    return _feedback(db, actor, session, question, attempt, mastery=mastery, earned=earned, already_answered=False)


def _feedback(db, actor, session, question: Question, attempt: QuestionAttempt, *, mastery, earned, already_answered) -> dict:
    correct_text = next(o["text"] for o in question.options_json if o["key"] == question.correct_option_key)
    topic = db.get(Topic, question.topic_id) if question.topic_id else None
    return {
        "question_id": str(question.id),
        "selected_option_key": attempt.selected_option_key,
        "is_correct": attempt.is_correct,
        "correct_option_key": question.correct_option_key,
        "correct_option_text": correct_text,
        "explanation": question.explanation,
        "misconception": question.misconception,
        "evidence": list(evidence_payload(db, question.evidence_ids).values()),
        "already_answered": already_answered,
        "topic": {"id": str(topic.id), "title": topic.title} if topic else None,
        "mastery": {"score": mastery.mastery_score, "confidence": mastery.confidence_level} if mastery else None,
        "session": serialize_session(session),
        "achievements_earned": earned,
    }


def serialize_question(q: Question, *, position: int | None = None) -> dict:
    """Pre-submission view: never includes the answer key, explanation or evidence."""
    return {
        "id": str(q.id),
        "question_text": q.question_text,
        "question_type": q.question_type,
        "difficulty": q.difficulty,
        "options": [{"key": o["key"], "text": o["text"]} for o in q.options_json],
        "language": q.language,
        "position": position,
    }


def serialize_session(s: QuizSession) -> dict:
    return {
        "id": str(s.id),
        "book_id": str(s.book_id),
        "chapter_id": str(s.chapter_id) if s.chapter_id else None,
        "session_type": s.session_type,
        "status": s.status,
        "status_message": s.status_message,
        "difficulty": s.difficulty,
        "question_count": s.question_count,
        "answered_count": s.answered_count,
        "correct_count": s.correct_count,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
    }
