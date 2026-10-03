"""Notes, highlights, bookmarks and reading position. User-authored content is kept separate from source text."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode, not_found
from app.models.books import Book, Chapter, DocumentChunk
from app.models.content import Annotation, ReadingState, Summary
from app.services.actors import CurrentActor
from app.services.analytics import track

TYPES = ("highlight", "bookmark", "note")
COLORS = ("yellow", "green", "blue", "pink", "purple")
MAX_SELECTED = 2000
MAX_NOTE = 10000


def _validate_location(db: Session, book: Book, loc: dict[str, Any]) -> dict[str, Any]:
    kind = loc.get("kind")
    clean: dict[str, Any] = {"kind": kind}
    if kind == "passage":
        try:
            chunk = db.get(DocumentChunk, uuid.UUID(str(loc.get("chunk_id"))))
        except ValueError:
            chunk = None
        if chunk is None or chunk.book_id != book.id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The annotated passage does not belong to this book.",
                status_code=422,
            )
        clean.update(chunk_id=str(chunk.id), chapter_id=str(chunk.chapter_id), passage=f"P{chunk.ordinal}")
        for k in ("start", "end"):
            if isinstance(loc.get(k), int) and 0 <= loc[k] <= len(chunk.text_content):
                clean[k] = loc[k]
    elif kind == "summary":
        try:
            summary = db.get(Summary, uuid.UUID(str(loc.get("summary_id"))))
        except ValueError:
            summary = None
        if summary is None or summary.book_id != book.id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The annotated summary does not belong to this book.",
                status_code=422,
            )
        clean.update(
            summary_id=str(summary.id),
            chapter_id=str(summary.chapter_id) if summary.chapter_id else None,
            section_key=str(loc.get("section_key", ""))[:80],
            depth=summary.depth,
        )
    elif kind == "chapter":
        try:
            chapter = db.get(Chapter, uuid.UUID(str(loc.get("chapter_id"))))
        except ValueError:
            chapter = None
        if chapter is None or chapter.book_id != book.id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "The chapter does not belong to this book.", status_code=422
            )
        clean.update(chapter_id=str(chapter.id))
    else:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown annotation location.", status_code=422)
    return clean


def create_annotation(db: Session, actor: CurrentActor, book: Book, payload: dict[str, Any]) -> Annotation:
    atype = payload.get("annotation_type")
    if atype not in TYPES:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Annotation type must be highlight, bookmark or note.",
            status_code=422,
        )
    selected = (payload.get("selected_text") or "")[:MAX_SELECTED] or None
    note = (payload.get("note_text") or "").strip() or None
    if note and len(note) > MAX_NOTE:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Notes are limited to 10,000 characters.", status_code=422)
    if atype == "note" and not note:
        raise AppError(ErrorCode.VALIDATION_ERROR, "A note needs some text.", status_code=422)
    color = payload.get("color")
    if color is not None and color not in COLORS:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unsupported highlight colour.", status_code=422)
    ann = Annotation(
        book_id=book.id,
        annotation_type=atype,
        source_location=_validate_location(db, book, payload.get("source_location") or {}),
        selected_text=selected,
        note_text=note,
        color=color if atype == "highlight" else None,
        **actor.owner_fields(),
    )
    db.add(ann)
    track(
        db,
        {"bookmark": "bookmark_created", "note": "note_created", "highlight": "highlight_created"}[atype],
        actor.key,
        book.id,
    )
    db.commit()
    return ann


def get_owned_annotation(db: Session, actor: CurrentActor, annotation_id: uuid.UUID) -> Annotation:
    ann = db.scalar(select(Annotation).where(Annotation.id == annotation_id, actor.owns(Annotation)))
    if ann is None:
        raise not_found("Annotation")
    return ann


def update_annotation(db: Session, ann: Annotation, payload: dict[str, Any]) -> Annotation:
    if "note_text" in payload:
        note = (payload.get("note_text") or "").strip() or None
        if note and len(note) > MAX_NOTE:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "Notes are limited to 10,000 characters.", status_code=422
            )
        if ann.annotation_type == "note" and not note:
            raise AppError(ErrorCode.VALIDATION_ERROR, "A note needs some text.", status_code=422)
        ann.note_text = note
    if "color" in payload and ann.annotation_type == "highlight":
        if payload["color"] not in COLORS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Unsupported highlight colour.", status_code=422)
        ann.color = payload["color"]
    db.commit()
    return ann


def list_annotations(
    db: Session, actor: CurrentActor, book: Book, atype: str | None = None
) -> list[Annotation]:
    stmt = select(Annotation).where(Annotation.book_id == book.id, actor.owns(Annotation))
    if atype:
        stmt = stmt.where(Annotation.annotation_type == atype)
    return list(db.scalars(stmt.order_by(Annotation.created_at.desc())))


def serialize_annotation(a: Annotation) -> dict:
    return {
        "id": str(a.id),
        "book_id": str(a.book_id),
        "annotation_type": a.annotation_type,
        "source_location": a.source_location,
        "selected_text": a.selected_text,
        "note_text": a.note_text,
        "color": a.color,
        "author": "you",
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


def export_markdown(db: Session, actor: CurrentActor, book: Book) -> str:
    chapters = {str(c.id): c for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id))}
    lines = [
        f"# {book.title} — my notes",
        "",
        "_Exported from Readbit. Quoted text is from the book; notes are yours._",
        "",
    ]
    anns = sorted(
        list_annotations(db, actor, book),
        key=lambda a: (
            chapters.get(a.source_location.get("chapter_id") or "", None).ordinal
            if chapters.get(a.source_location.get("chapter_id") or "")
            else 0,
            a.created_at,
        ),
    )
    current = None
    for a in anns:
        ch = chapters.get(a.source_location.get("chapter_id") or "")
        title = ch.title if ch else "General"
        if title != current:
            lines += [f"## {title}", ""]
            current = title
        label = {"highlight": "Highlight", "bookmark": "Bookmark", "note": "Note"}[a.annotation_type]
        if a.selected_text:
            lines.append(f"> {a.selected_text}")
        lines.append(f"- **{label}**" + (f": {a.note_text}" if a.note_text else ""))
        lines.append("")
    return "\n".join(lines)


def upsert_reading_state(
    db: Session, actor: CurrentActor, book: Book, payload: dict[str, Any]
) -> ReadingState:
    state = db.scalar(
        select(ReadingState).where(ReadingState.book_id == book.id, ReadingState.actor_key == actor.key)
    )
    if state is None:
        state = ReadingState(book_id=book.id, actor_key=actor.key, **actor.owner_fields())
        db.add(state)
    view = payload.get("view")
    if view in ("summary", "source", "overview"):
        state.last_view = view
    chapter_id = payload.get("chapter_id")
    if chapter_id:
        try:
            ch = db.get(Chapter, uuid.UUID(str(chapter_id)))
        except ValueError:
            ch = None
        if ch is None or ch.book_id != book.id:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Chapter not found in this book.", status_code=422)
        state.last_chapter_id = ch.id
        if view == "summary" and str(ch.id) not in (state.chapters_read or []):
            state.chapters_read = list(state.chapters_read or []) + [str(ch.id)]
    if payload.get("depth") in ("concise", "balanced", "comprehensive"):
        state.last_depth = payload["depth"]
    pos = payload.get("position")
    if isinstance(pos, dict):
        state.last_position = {
            k: v
            for k, v in pos.items()
            if k in ("section_key", "chunk_id", "scroll") and isinstance(v, str | int | float)
        }
    db.commit()
    return state


def serialize_reading_state(s: ReadingState | None) -> dict | None:
    if s is None:
        return None
    return {
        "last_view": s.last_view,
        "last_chapter_id": str(s.last_chapter_id) if s.last_chapter_id else None,
        "last_depth": s.last_depth,
        "last_position": s.last_position,
        "chapters_read": s.chapters_read or [],
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
