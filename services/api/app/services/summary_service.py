"""Summarizer: hierarchical, coverage-aware, evidence-grounded chapter and whole-book summaries."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.retrieval import passage_id, render_passages, token_budget_windows
from app.ai.router import ModelRouter, RoutedResult
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.document_processing.text import word_count
from app.models.books import Book, Chapter, DocumentChunk, ProcessingJob
from app.models.content import Summary, SummaryEvidence
from app.services.analytics import track
from app.services.evidence import get_or_create_evidence
from app.workers.dispatch import enqueue

log = get_logger("readbit.summary")
DEPTHS = ("concise", "balanced", "comprehensive")
TARGET_WORDS = {"concise": 250, "balanced": 600, "comprehensive": 1400}
BOOK_TARGET_WORDS = {"concise": 400, "balanced": 900, "comprehensive": 2000}
CONTENT_VERSION = 1
WEAK_SUPPORT = 0.2
READING_WPM = 230
CLAIM_FIELDS = ("central_thesis", "conclusion")
CLAIM_LISTS = {"sections": "content", "definitions": "definition", "examples": "description", "caveats": "text",
               "connections": "text", "takeaways": "text"}


def book_output_language(book: Book) -> str:
    return book.detected_language or book.original_language or "en"


def request_summary(
    db: Session, book: Book, *, chapter_id: uuid.UUID | None, depth: str, language: str | None, actor_key: str
) -> Summary:
    if depth not in DEPTHS:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Depth must be concise, balanced or comprehensive.", status_code=422)
    if book.processing_status != "ready":
        raise AppError(ErrorCode.NOT_READY, "This book is still being processed.", status_code=409)
    chapter = None
    if chapter_id is not None:
        chapter = db.get(Chapter, chapter_id)
        if chapter is None or chapter.book_id != book.id:
            raise AppError(ErrorCode.NOT_FOUND, "Chapter not found.", status_code=404)
    lang = language or book_output_language(book)
    router = ModelRouter(db)
    if not router.supports_language("summary_generator", lang, book.detected_language):
        raise AppError(
            ErrorCode.LANGUAGE_UNSUPPORTED,
            "Summaries in this language need an AI provider that can translate. The offline engine summarizes in "
            "the book's own language.",
            status_code=422,
            details={"output_language": lang, "book_language": book.detected_language},
        )
    existing = db.scalar(
        select(Summary)
        .where(
            Summary.book_id == book.id,
            Summary.chapter_id.is_(None) if chapter is None else Summary.chapter_id == chapter.id,
            Summary.depth == depth,
            Summary.output_language == lang,
            Summary.content_version == CONTENT_VERSION,
        )
        .order_by(Summary.created_at.desc())
    )
    if existing is not None and existing.status in ("ready", "pending", "generating"):
        return existing
    summary = existing or Summary(
        book_id=book.id,
        chapter_id=chapter.id if chapter else None,
        scope="chapter" if chapter else "book",
        depth=depth,
        output_language=lang,
        content_version=CONTENT_VERSION,
    )
    summary.status, summary.error_code, summary.safe_error_message = "pending", None, None
    db.add(summary)
    db.flush()
    job = ProcessingJob(book_id=book.id, job_type="summary", target_id=summary.id, stage="queued")
    db.add(job)
    db.commit()
    enqueue("summary", job.id)
    db.refresh(summary)
    return summary


def run_summary_job(job_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.status in ("succeeded", "cancelled"):
            return
        summary = db.get(Summary, job.target_id)
        if summary is None or summary.status == "ready":
            job.status = "succeeded"
            db.commit()
            return
        book = db.get(Book, summary.book_id)
        assert book is not None
        job.status, job.attempts, job.started_at, job.stage = "running", job.attempts + 1, datetime.now(UTC), "generating"
        summary.status = "generating"
        db.commit()
        started = time.monotonic()
        try:
            if summary.scope == "chapter":
                chapter = db.get(Chapter, summary.chapter_id)
                assert chapter is not None
                content, usage = generate_chapter_summary(db, book, chapter, summary.depth, summary.output_language, summary.id)
            else:
                content, usage = generate_book_summary(db, book, summary.depth, summary.output_language, summary.id)
            summary.content_json = content
            summary.status = "ready"
            summary.model_provider = usage["provider"]
            summary.model_name = usage["model"]
            summary.prompt_version = usage["prompt_version"]
            summary.token_usage = {"input": usage["input_tokens"], "output": usage["output_tokens"], "calls": usage["calls"]}
            summary.estimated_cost = usage["cost"]
            summary.generation_duration_ms = int((time.monotonic() - started) * 1000)
            job.status, job.stage, job.progress_percent, job.completed_at = "succeeded", "ready", 100, datetime.now(UTC)
            track(db, "summary_generated", None, book.id, depth=summary.depth, language=summary.output_language)
            db.commit()
        except AppError as exc:
            db.rollback()
            _fail(db, job_id, exc.code, exc.message)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("summary crashed", extra={"job_id": str(job_id)})
            _fail(db, job_id, ErrorCode.INTERNAL, "The summary could not be generated. Please retry.")


def _fail(db: Session, job_id: uuid.UUID, code: ErrorCode, message: str) -> None:
    job = db.get(ProcessingJob, job_id)
    if job is None:
        return
    summary = db.get(Summary, job.target_id)
    job.status, job.error_code, job.safe_error_message, job.completed_at = "failed", str(code), message, datetime.now(UTC)
    if summary is not None:
        summary.status, summary.error_code, summary.safe_error_message = "failed", str(code), message
    db.commit()


class _Usage:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "calls": 0,
                                     "provider": None, "model": None, "prompt_version": None}

    def add(self, r: RoutedResult) -> None:
        d = self.data
        d["input_tokens"] += r.input_tokens
        d["output_tokens"] += r.output_tokens
        d["cost"] = round(d["cost"] + r.cost, 6)
        d["calls"] += 1
        d["provider"], d["model"], d["prompt_version"] = r.provider, r.model, r.prompt_version


def _chapter_chunks(db: Session, chapter: Chapter) -> list[DocumentChunk]:
    return list(db.scalars(select(DocumentChunk).where(DocumentChunk.chapter_id == chapter.id).order_by(DocumentChunk.ordinal)))


def generate_chapter_summary(
    db: Session, book: Book, chapter: Chapter, depth: str, language: str, summary_id: uuid.UUID | None
) -> tuple[dict, dict]:
    settings = get_settings()
    router = ModelRouter(db)
    usage = _Usage()
    chunks = _chapter_chunks(db, chapter)
    if not chunks:
        raise AppError(ErrorCode.EVIDENCE_INSUFFICIENT, "This chapter has no readable text to summarize.", status_code=422)
    windows = token_budget_windows(chunks, 9000)
    common = {"book_title": book.title, "chapter_title": chapter.title, "depth": depth,
              "target_words": TARGET_WORDS[depth]}
    if len(windows) == 1:
        passages, rendered = render_passages(db, chunks)
    else:
        # Hierarchical: passage-window notes first, then chapter synthesis over the notes (ids preserved).
        notes_by_pid: dict[str, list[str]] = {}
        for wi, window in enumerate(windows, 1):
            w_passages, w_rendered = render_passages(db, window)
            r = router.generate(
                "summary_passage_notes",
                variables={**common, "passages": w_rendered, "window_index": wi, "window_count": len(windows)},
                context={"passages": w_passages, "max_quote_ratio": settings.max_quote_ratio},
                output_language=language, source_language=book.detected_language, book_id=book.id,
            )
            usage.add(r)
            valid = {p["id"] for p in w_passages}
            for note in r.data["notes"]:
                ids = [e for e in note["evidence_ids"] if e in valid]
                if ids and note["text"].strip():
                    notes_by_pid.setdefault(ids[0], []).append(note["text"].strip())
        by_pid = {passage_id(c): c for c in chunks}
        passages = [{"id": pid, "text": " ".join(texts), "section": by_pid[pid].section_title, "chapter_title": chapter.title}
                    for pid, texts in sorted(notes_by_pid.items(), key=lambda kv: int(kv[0][1:]))]
        rendered = "\n".join(f'<passage id="{p["id"]}">\n{p["text"]}\n</passage>' for p in passages)
    r = router.generate(
        "summary_generator",
        variables={**common, "passages": rendered},
        context={"passages": passages, "depth": depth, "chapter_title": chapter.title,
                 "max_quote_ratio": settings.max_quote_ratio},
        output_language=language, source_language=book.detected_language, book_id=book.id,
    )
    usage.add(r)
    allowed = {passage_id(c): c for c in chunks}
    content = ground_summary(db, book, r.data, allowed, summary_id)
    content["scope"] = "chapter"
    content["chapter_id"] = str(chapter.id)
    content["depth"] = depth
    content["language"] = language
    content["engine"] = {"provider": r.provider, "model": r.model, "mode": "extractive" if router.is_offline else "generative"}
    content["coverage"].update({
        "source_passages_considered": len(chunks),
        "hierarchical_windows": len(windows),
        "chapter_detection_confidence": chapter.detection_confidence,
    })
    content["coverage"]["known_gaps"] = list(dict.fromkeys(r.data.get("known_gaps", []) + _chapter_gaps(book, chunks)))
    content["reading_minutes"] = _reading_minutes(content)
    content["source_reading_minutes"] = max(1, round(chapter.word_count / READING_WPM))
    return content, usage.data


def _chapter_gaps(book: Book, chunks: list[DocumentChunk]) -> list[str]:
    gaps = []
    pages = {p for c in chunks for p in (c.page_start, c.page_end) if p is not None}
    for w in book.extraction_warnings or []:
        wp = set(p - 1 for p in w.get("pages", []))
        if w.get("code") in ("ocr_unavailable", "extraction_gap") and (not pages or (wp and min(wp) <= max(pages) and max(wp) >= min(pages))):
            gaps.append(w["message"])
        if w.get("code") == "extraction_quality_low":
            gaps.append(w["message"])
    if any(c.extraction_confidence < 0.9 for c in chunks):
        gaps.append("Some passages in this chapter were read with OCR and may contain recognition errors.")
    return gaps


def generate_book_summary(db: Session, book: Book, depth: str, language: str, summary_id: uuid.UUID | None) -> tuple[dict, dict]:
    """Book-level synthesis over EVERY chapter summary (never over the first retrieved chunks only)."""
    router = ModelRouter(db)
    usage = _Usage()
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)))
    chapter_depth = "comprehensive" if depth == "comprehensive" else "balanced"
    inputs, failed = [], []
    for ch in chapters:
        existing = db.scalar(
            select(Summary).where(Summary.chapter_id == ch.id, Summary.depth == chapter_depth,
                                  Summary.output_language == language, Summary.status == "ready",
                                  Summary.content_version == CONTENT_VERSION)
        )
        content = existing.content_json if existing else None
        if content is None:
            try:
                content, u = generate_chapter_summary(db, book, ch, chapter_depth, language, None)
                for k in ("input_tokens", "output_tokens", "calls"):
                    usage.data[k] += u[k]
                usage.data["cost"] = round(usage.data["cost"] + u["cost"], 6)
                cached = Summary(book_id=book.id, chapter_id=ch.id, scope="chapter", depth=chapter_depth,
                                 output_language=language, status="ready", content_json=content,
                                 content_version=CONTENT_VERSION, model_provider=u["provider"], model_name=u["model"],
                                 prompt_version=u["prompt_version"], estimated_cost=u["cost"])
                db.add(cached)
                db.flush()
            except AppError as exc:
                failed.append(ch.title)
                log.warning("chapter summary failed during book summary", extra={"chapter": str(ch.id), "code": str(exc.code)})
                content = None
        inputs.append({"title": ch.title, "summary": content})
    if all(i["summary"] is None for i in inputs):
        raise AppError(ErrorCode.AI_OUTPUT_INVALID, "No chapter could be summarized, so no book summary was produced.", status_code=502)

    # Aggregator input: every chapter's grounded claims, each tagged with the original passage ids.
    passages, lines = [], []
    for i in inputs:
        s = i["summary"]
        if s is None:
            lines.append(f'<chapter title="{i["title"]}" status="unavailable"/>')
            continue
        lines.append(f'<chapter title="{i["title"]}">')
        for claim in _claims(s):
            for pid in claim["passage_ids"][:1]:
                passages.append({"id": pid, "text": claim["text"], "chapter_title": i["title"]})
                lines.append(f'<passage id="{pid}">{claim["text"]}</passage>')
        lines.append("</chapter>")
    r = router.generate(
        "book_summary_aggregator",
        variables={"book_title": book.title, "depth": depth, "target_words": BOOK_TARGET_WORDS[depth], "passages": "\n".join(lines)},
        context={"chapter_summaries": [{"title": i["title"], "summary": _as_model_output(i["summary"])} for i in inputs],
                 "depth": depth, "book_title": book.title},
        output_language=language, source_language=book.detected_language, book_id=book.id,
    )
    usage.add(r)
    all_chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.book_id == book.id)))
    allowed = {passage_id(c): c for c in all_chunks}
    content = ground_summary(db, book, r.data, allowed, summary_id)
    content["scope"] = "book"
    content["depth"] = depth
    content["language"] = language
    content["engine"] = {"provider": r.provider, "model": r.model, "mode": "extractive" if router.is_offline else "generative"}
    content["coverage"].update({
        "chapters_total": len(chapters),
        "chapters_covered": len(chapters) - len(failed),
        "chapters_failed": failed,
        "source_passages_considered": len(all_chunks),
    })
    gaps = list(r.data.get("known_gaps", [])) + [f"{t}: this chapter could not be summarized." for t in failed]
    if (book.structure_confidence or 0) < 0.5:
        gaps.append("No reliable chapter structure was detected, so the book was divided into labelled sections.")
    content["coverage"]["known_gaps"] = list(dict.fromkeys(gaps))
    content["reading_minutes"] = _reading_minutes(content)
    content["source_reading_minutes"] = max(1, round(book.word_count / READING_WPM))
    return content, usage.data


def _as_model_output(content: dict | None) -> dict | None:
    """Convert a stored (grounded) summary back to model-output shape with passage ids as evidence ids."""
    if content is None:
        return None
    out = {k: v for k, v in content.items() if k in ("title", "known_gaps", "language_ok")}

    def conv(item: dict) -> dict:
        clean = {k: v for k, v in item.items() if k not in ("passage_ids", "support")}
        return {**clean, "evidence_ids": list(item.get("passage_ids", []))}

    for f in CLAIM_FIELDS:
        out[f] = conv(content[f])
    for f in CLAIM_LISTS:
        out[f] = [conv(x) for x in content.get(f, [])]
    return out


def _claims(content: dict) -> list[dict]:
    claims = []
    for f in CLAIM_FIELDS:
        if content[f]["text"]:
            claims.append({"text": content[f]["text"], "passage_ids": content[f]["passage_ids"]})
    for f, text_key in CLAIM_LISTS.items():
        for item in content.get(f, []):
            if item.get(text_key):
                claims.append({"text": item[text_key], "passage_ids": item["passage_ids"]})
    return claims


def ground_summary(db: Session, book: Book, data: dict, allowed: dict[str, DocumentChunk], summary_id: uuid.UUID | None) -> dict:
    """Keep only claims with valid evidence, resolve each cited passage to a bounded excerpt, record coverage."""
    content = {k: v for k, v in data.items() if k not in ("language_ok", "known_gaps")}
    removed, weak, strong = 0, 0, 0
    cited: set[str] = set()
    links: list[tuple[str, uuid.UUID, float]] = []

    def ground(item: dict, text: str, key: str) -> dict | None:
        nonlocal removed, weak, strong
        pids = [p for p in dict.fromkeys(item.get("evidence_ids", [])) if p in allowed]
        if not text.strip():
            return {**item, "evidence_ids": [], "passage_ids": [], "support": "none"}
        if not pids:
            removed += 1
            return None
        ev_ids, scores = [], []
        for pid in pids[:4]:
            ev, score = get_or_create_evidence(db, book, allowed[pid], text)
            ev_ids.append(str(ev.id))
            scores.append(score)
            links.append((key, ev.id, score))
            cited.add(pid)
        support = "strong" if max(scores) >= WEAK_SUPPORT else "weak"
        if support == "strong":
            strong += 1
        else:
            weak += 1
        return {**item, "evidence_ids": ev_ids, "passage_ids": pids[:4], "support": support}

    for f in CLAIM_FIELDS:
        grounded = ground(content.get(f) or {"text": "", "evidence_ids": []}, (content.get(f) or {}).get("text", ""), f)
        content[f] = grounded or {"text": "", "evidence_ids": [], "passage_ids": [], "support": "removed"}
    for f, text_key in CLAIM_LISTS.items():
        kept = []
        for i, item in enumerate(content.get(f, [])):
            g = ground(item, item.get(text_key, ""), f"{f}.{i}")
            if g is not None:
                kept.append(g)
        content[f] = kept
    if summary_id is not None:
        for key, ev_id, score in links:
            db.add(SummaryEvidence(summary_id=summary_id, evidence_id=ev_id, section_key=key[:80], relevance_score=round(score, 3)))
    content["coverage"] = {
        "source_passages_cited": len(cited),
        "claims_with_strong_lexical_support": strong,
        "claims_with_weak_lexical_support": weak,
        "claims_removed_without_evidence": removed,
    }
    return content


def _reading_minutes(content: dict) -> int:
    words = sum(word_count(c["text"]) for c in _claims(content)) if content else 0
    return max(1, round(words / READING_WPM))


def serialize_summary(db: Session, summary: Summary) -> dict:
    from app.services.evidence import evidence_payload

    content = summary.content_json
    evidence = {}
    if content:
        ids: list[str] = []
        for f in CLAIM_FIELDS:
            ids += content[f].get("evidence_ids", [])
        for f in CLAIM_LISTS:
            for item in content.get(f, []):
                ids += item.get("evidence_ids", [])
        evidence = evidence_payload(db, ids)
    return {
        "id": str(summary.id),
        "book_id": str(summary.book_id),
        "chapter_id": str(summary.chapter_id) if summary.chapter_id else None,
        "scope": summary.scope,
        "depth": summary.depth,
        "output_language": summary.output_language,
        "status": summary.status,
        "content": content,
        "evidence": evidence,
        "error": {"code": summary.error_code, "message": summary.safe_error_message} if summary.status == "failed" else None,
        "model_provider": summary.model_provider,
        "model_name": summary.model_name,
        "prompt_version": summary.prompt_version,
        "generation_duration_ms": summary.generation_duration_ms,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
    }
