"""Book Q&A: retrieval-grounded answers that abstain when the book does not support an answer."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.ai.retrieval import passage_id, render_passages, retrieve
from app.ai.router import ModelRouter
from app.core.errors import AppError, ErrorCode
from app.models.books import Book, Chapter
from app.services.actors import CurrentActor
from app.services.analytics import track
from app.services.evidence import get_or_create_evidence, serialize_evidence
from app.services.summary_service import book_output_language

MAX_QUESTION_CHARS = 1000


def ask(db: Session, actor: CurrentActor, book: Book, question: str, *, chapter_id: uuid.UUID | None, language: str | None) -> dict:
    question = question.strip()
    if not question:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Please enter a question.", status_code=422)
    if len(question) > MAX_QUESTION_CHARS:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Questions are limited to 1,000 characters.", status_code=422)
    if book.processing_status != "ready":
        raise AppError(ErrorCode.NOT_READY, "This book is still being processed.", status_code=409)
    scope_line = "Scope: the whole book."
    if chapter_id is not None:
        chapter = db.get(Chapter, chapter_id)
        if chapter is None or chapter.book_id != book.id:
            raise AppError(ErrorCode.NOT_FOUND, "Chapter not found.", status_code=404)
        scope_line = f"Scope: the chapter “{chapter.title}”."
    lang = language or book_output_language(book)
    router = ModelRouter(db)
    hits = retrieve(db, book.id, question, chapter_id=chapter_id, k=6)
    engine = {"provider": router.provider_name, "mode": "extractive" if router.is_offline else "generative"}
    if not hits:
        track(db, "book_question_asked", actor.key, book.id, answerable=False)
        return _abstain("The book does not appear to contain anything related to this question.", engine)
    chunks = [h.chunk for h in hits]
    passages, rendered = render_passages(db, chunks)
    result = router.generate(
        "book_qa",
        variables={"book_title": book.title, "question": question, "passages": rendered, "scope_line": scope_line},
        context={"question": question, "passages": passages},
        output_language=lang,
        source_language=book.detected_language,
        book_id=book.id,
        actor=actor.ai_actor(),
    )
    data = result.data
    engine["model"] = result.model
    allowed = {passage_id(c): c for c in chunks}
    pids = [p for p in dict.fromkeys(data.get("evidence_ids", [])) if p in allowed]
    if not data.get("answerable") or not data.get("answer", "").strip() or not pids:
        track(db, "book_question_asked", actor.key, book.id, answerable=False)
        reason = data.get("unanswerable_reason") or "The book does not provide enough information to answer this."
        if data.get("answerable") and not pids:
            reason = "An answer was drafted but could not be tied to passages in your book, so it was withheld."
        db.commit()
        return _abstain(reason, engine)
    citations, scores = [], []
    for pid in pids[:4]:
        ev, score = get_or_create_evidence(db, book, allowed[pid], data["answer"])
        citations.append(serialize_evidence(ev, allowed[pid].ordinal, allowed[pid].section_title))
        scores.append(score)
    confidence = data.get("confidence", "medium")
    if max(scores) < 0.08:
        confidence = "low"
    track(db, "book_question_asked", actor.key, book.id, answerable=True)
    db.commit()
    return {
        "answerable": True,
        "answer": data["answer"],
        "confidence": confidence,
        "citations": citations,
        "unanswerable_reason": None,
        "engine": engine,
        "language": lang,
    }


def _abstain(reason: str, engine: dict) -> dict:
    return {"answerable": False, "answer": None, "confidence": "low", "citations": [], "unanswerable_reason": reason, "engine": engine}
