from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.retrieval import retrieve
from app.api.deps import db_session, require_actor, upload_rate_limited
from app.api.serializers import serialize_book, serialize_chapter, serialize_job
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, not_found
from app.models.books import Chapter, DocumentChunk
from app.models.content import ReadingState
from app.schemas.api import ReadingStateBody
from app.services import annotation_service as ann
from app.services import book_service as bs
from app.services.actors import CurrentActor

router = APIRouter(prefix="/api/v1/books", tags=["books"])


@router.get("", summary="List my books (cursor pagination, newest first)")
def list_books(limit: int = Query(20, ge=1, le=100), cursor: str | None = None, db: Session = Depends(db_session),
               actor: CurrentActor = Depends(require_actor)) -> dict:
    books, next_cursor = bs.list_books(db, actor, limit=limit, cursor=cursor)
    return {"items": [serialize_book(b, bs.latest_job(db, b.id)) for b in books], "next_cursor": next_cursor}


@router.post("/upload", status_code=202, summary="Upload a PDF or EPUB and start processing")
async def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(db_session),
                 actor: CurrentActor = Depends(upload_rate_limited)):
    limit = get_settings().max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1024 * 1024:
        raise AppError(ErrorCode.FILE_TOO_LARGE, f"The file is larger than the {get_settings().max_upload_size_mb} MB limit.", status_code=413)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(ErrorCode.FILE_TOO_LARGE, f"The file is larger than the {get_settings().max_upload_size_mb} MB limit.", status_code=413)
    book, duplicate = bs.upload_book(db, actor, file.filename, file.content_type, data)
    body = {"book": serialize_book(book, bs.latest_job(db, book.id)), "duplicate": duplicate,
            "retention": {"guest": actor.is_guest, "expires_at": actor.guest.expires_at.isoformat() if actor.is_guest and actor.guest else None}}
    return JSONResponse(body, status_code=200 if duplicate else 202)


@router.get("/{book_id}", summary="Book details")
def get_book(book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    state = db.scalar(select(ReadingState).where(ReadingState.book_id == book.id, ReadingState.actor_key == actor.key))
    return {"book": serialize_book(book, bs.latest_job(db, book.id)), "reading_state": ann.serialize_reading_state(state)}


@router.delete("/{book_id}", summary="Delete a book, its file and everything derived from it")
def delete_book(book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    bs.delete_book(db, bs.get_owned_book(db, actor, book_id))
    return {"deleted": True}


@router.get("/{book_id}/processing-status", summary="Poll processing progress")
def processing_status(book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    return {"book_id": str(book.id), "processing_status": book.processing_status, "learning_status": book.learning_status,
            "job": serialize_job(bs.latest_job(db, book.id)), "warnings": book.extraction_warnings or []}


@router.post("/{book_id}/retry", status_code=202, summary="Retry failed processing")
def retry(book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    job = bs.retry_processing(db, bs.get_owned_book(db, actor, book_id))
    return {"job": serialize_job(job)}


@router.get("/{book_id}/chapters", summary="Table of contents")
def chapters(book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    return {"items": [serialize_chapter(c) for c in bs.chapters(db, book)], "structure_confidence": book.structure_confidence}


@router.get("/{book_id}/chapters/{chapter_id}/passages", summary="Extracted source passages of a chapter (private reader)")
def passages(book_id: uuid.UUID, chapter_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    chapter = db.get(Chapter, chapter_id)
    if chapter is None or chapter.book_id != book.id:
        raise not_found("Chapter")
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.chapter_id == chapter.id).order_by(DocumentChunk.ordinal))
    return {
        "chapter": serialize_chapter(chapter),
        "items": [{"id": str(c.id), "passage": f"P{c.ordinal}", "text": c.text_content, "section_title": c.section_title,
                   "page_number": (c.page_start + 1) if c.page_start is not None else None, "page_label": c.page_label_start,
                   "extraction_confidence": c.extraction_confidence} for c in chunks],
    }


@router.get("/{book_id}/search", summary="Search within the book")
def search(book_id: uuid.UUID, q: str = Query(..., min_length=2, max_length=200), db: Session = Depends(db_session),
           actor: CurrentActor = Depends(require_actor)) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    hits = retrieve(db, book.id, q, k=10)
    chapters = {c.id: c for c in bs.chapters(db, book)}
    items = []
    for h in hits:
        if h.lexical <= 0:
            continue
        ch = chapters.get(h.chunk.chapter_id)
        text = h.chunk.text_content
        idx = max(0, text.lower().find(q.lower().split()[0]))
        items.append({"chunk_id": str(h.chunk.id), "passage": f"P{h.chunk.ordinal}", "chapter_id": str(ch.id) if ch else None,
                      "chapter_title": ch.title if ch else None, "snippet": text[max(0, idx - 80): idx + 160],
                      "page_number": (h.chunk.page_start + 1) if h.chunk.page_start is not None else None, "score": round(h.score, 4)})
    return {"items": items}


@router.get("/{book_id}/reading-state", summary="Where I left off")
def get_reading_state(book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    state = db.scalar(select(ReadingState).where(ReadingState.book_id == book.id, ReadingState.actor_key == actor.key))
    return {"reading_state": ann.serialize_reading_state(state)}


@router.put("/{book_id}/reading-state", summary="Save reading position")
def put_reading_state(book_id: uuid.UUID, body: ReadingStateBody, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)) -> dict:
    from app.services.learning_service import evaluate_achievements

    book = bs.get_owned_book(db, actor, book_id)
    state = ann.upsert_reading_state(db, actor, book, body.model_dump(mode="json", exclude_none=True))
    earned = evaluate_achievements(db, actor, None) if body.view == "summary" else []
    db.commit()
    return {"reading_state": ann.serialize_reading_state(state), "achievements_earned": earned}


@router.get("/{book_id}/annotations/export", response_class=PlainTextResponse, summary="Export my notes and highlights (Markdown)")
def export_annotations(book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)):
    book = bs.get_owned_book(db, actor, book_id)
    return PlainTextResponse(ann.export_markdown(db, actor, book), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="readbit-notes.md"'})
