from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.router import ModelRouter
from app.api.deps import ai_rate_limited, db_session, require_actor
from app.core.errors import not_found
from app.models.books import DocumentChunk, EvidenceReference
from app.models.content import Summary
from app.schemas.api import QuestionBody, SummaryRequest, TranslateBody
from app.services import book_service as bs
from app.services import qa_service
from app.services import summary_service as ss
from app.services.actors import CurrentActor
from app.services.evidence import serialize_evidence

router = APIRouter(prefix="/api/v1", tags=["summarizer"])


@router.post("/books/{book_id}/summaries", summary="Request a chapter or whole-book summary (async; cached)")
def create_summary(
    book_id: uuid.UUID,
    body: SummaryRequest,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(ai_rate_limited),
):
    book = bs.get_owned_book(db, actor, book_id)
    summary = ss.request_summary(
        db,
        book,
        chapter_id=body.chapter_id,
        depth=body.depth,
        language=body.output_language,
        actor_key=actor.key,
    )
    return JSONResponse(
        {"summary": ss.serialize_summary(db, summary)}, status_code=200 if summary.status == "ready" else 202
    )


@router.get("/books/{book_id}/summaries", summary="List generated summaries for a book")
def list_summaries(
    book_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    rows = db.scalars(select(Summary).where(Summary.book_id == book.id).order_by(Summary.created_at.desc()))
    return {
        "items": [
            {
                "id": str(s.id),
                "chapter_id": str(s.chapter_id) if s.chapter_id else None,
                "scope": s.scope,
                "depth": s.depth,
                "output_language": s.output_language,
                "status": s.status,
            }
            for s in rows
        ]
    }


def _owned_summary(db: Session, actor: CurrentActor, book_id: uuid.UUID, summary_id: uuid.UUID) -> Summary:
    book = bs.get_owned_book(db, actor, book_id)
    summary = db.get(Summary, summary_id)
    if summary is None or summary.book_id != book.id:
        raise not_found("Summary")
    return summary


@router.get("/books/{book_id}/summaries/{summary_id}", summary="Get a summary (poll until status=ready)")
def get_summary(
    book_id: uuid.UUID,
    summary_id: uuid.UUID,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_actor),
) -> dict:
    return {"summary": ss.serialize_summary(db, _owned_summary(db, actor, book_id, summary_id))}


@router.get(
    "/books/{book_id}/summaries/{summary_id}/export",
    response_class=PlainTextResponse,
    summary="Export a summary as Markdown",
)
def export_summary(
    book_id: uuid.UUID,
    summary_id: uuid.UUID,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_actor),
):
    summary = _owned_summary(db, actor, book_id, summary_id)
    data = ss.serialize_summary(db, summary)
    c = data["content"] or {}
    ev = data["evidence"]

    def cite(ids):
        refs = []
        for i in ids or []:
            e = ev.get(i)
            if e:
                refs.append(
                    f"p. {e['page_label'] or e['page_number']}"
                    if e.get("page_number")
                    else e.get("passage") or ""
                )
        return f" [{', '.join(r for r in refs if r)}]" if refs else ""

    lines = [
        f"# {c.get('title', '')}",
        "",
        f"_Readbit {summary.depth} summary. Generated from your uploaded book; citations point to the source._",
        "",
    ]
    if c.get("central_thesis", {}).get("text"):
        lines += [
            "## Central thesis",
            c["central_thesis"]["text"] + cite(c["central_thesis"].get("evidence_ids")),
            "",
        ]
    for s in c.get("sections", []):
        lines += [f"## {s['heading']}", s["content"] + cite(s.get("evidence_ids")), ""]
    for title, key, field in (
        ("Definitions", "definitions", "definition"),
        ("Examples", "examples", "description"),
        ("Caveats", "caveats", "text"),
        ("Key takeaways", "takeaways", "text"),
    ):
        if c.get(key):
            lines.append(f"## {title}")
            for item in c[key]:
                prefix = f"**{item['term']}**: " if key == "definitions" else ""
                lines.append(f"- {prefix}{item[field]}{cite(item.get('evidence_ids'))}")
            lines.append("")
    gaps = (c.get("coverage") or {}).get("known_gaps") or []
    if gaps:
        lines += ["## Known gaps"] + [f"- {g}" for g in gaps]
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="readbit-summary.md"'},
    )


@router.post("/books/{book_id}/questions", summary="Ask a question answered only from this book")
def ask(
    book_id: uuid.UUID,
    body: QuestionBody,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(ai_rate_limited),
) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    return qa_service.ask(
        db, actor, book, body.question, chapter_id=body.chapter_id, language=body.output_language
    )


def _owned_evidence(db: Session, actor: CurrentActor, book_id: uuid.UUID, evidence_id: uuid.UUID):
    book = bs.get_owned_book(db, actor, book_id)
    ev = db.get(EvidenceReference, evidence_id)
    if ev is None or ev.book_id != book.id:
        raise not_found("Evidence")
    chunk = db.get(DocumentChunk, ev.chunk_id)
    return book, ev, chunk


@router.get(
    "/books/{book_id}/evidence/{evidence_id}", summary="Resolve a citation to its source location and passage"
)
def get_evidence(
    book_id: uuid.UUID,
    evidence_id: uuid.UUID,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_actor),
) -> dict:
    _, ev, chunk = _owned_evidence(db, actor, book_id, evidence_id)
    data = serialize_evidence(ev, chunk.ordinal if chunk else None, chunk.section_title if chunk else None)
    data["passage_text"] = chunk.text_content if chunk else None
    return {"evidence": data}


@router.post(
    "/books/{book_id}/evidence/{evidence_id}/translate",
    summary="Machine-translate a cited excerpt (shown alongside the original)",
)
def translate_evidence(
    book_id: uuid.UUID,
    evidence_id: uuid.UUID,
    body: TranslateBody,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(ai_rate_limited),
) -> dict:
    book, ev, _ = _owned_evidence(db, actor, book_id, evidence_id)
    result = ModelRouter(db).generate(
        "translation",
        variables={"passages": f'<passage id="E1">{ev.excerpt}</passage>'},
        context={"passages": [{"id": "E1", "text": ev.excerpt}]},
        output_language=body.target_language,
        source_language=book.detected_language,
        book_id=book.id,
        actor=actor.ai_actor(),
    )
    db.commit()
    return {
        "original": ev.excerpt,
        "translation": result.data["translation"],
        "target_language": body.target_language,
        "label": "Machine translation — the original passage is authoritative.",
    }
