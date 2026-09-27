"""Evidence references: resolve model-cited passage ids to verifiable, bounded excerpts of the source."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.document_processing.text import split_sentences, token_overlap
from app.models.books import Book, DocumentChunk, EvidenceReference


def best_support(claim: str, chunk_text: str) -> tuple[str, int, int, float]:
    """The sentence (or short window) of `chunk_text` that best supports `claim`, with offsets and overlap."""
    sentences = split_sentences(chunk_text)
    if not sentences:
        return chunk_text[:200], 0, min(200, len(chunk_text)), 0.0
    best, best_score = sentences[0], -1.0
    for i, s in enumerate(sentences):
        window = s if i + 1 >= len(sentences) else s + " " + sentences[i + 1]
        score = max(token_overlap(claim, s), token_overlap(claim, window) - 0.05)
        if score > best_score:
            best, best_score = s, score
    start = chunk_text.find(best[:40])
    if start < 0:
        start = 0
    return best, start, start + len(best), max(0.0, best_score)


def excerpt_limit(text: str) -> str:
    limit = get_settings().max_excerpt_chars
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def get_or_create_evidence(
    db: Session, book: Book, chunk: DocumentChunk, claim: str
) -> tuple[EvidenceReference, float]:
    sentence, start, end, score = best_support(claim, chunk.text_content)
    existing = db.scalar(
        select(EvidenceReference).where(
            EvidenceReference.book_id == book.id,
            EvidenceReference.chunk_id == chunk.id,
            EvidenceReference.character_start == start,
        )
    )
    if existing is not None:
        return existing, score
    loc = chunk.source_start_location or {}
    ev = EvidenceReference(
        id=uuid.uuid4(),
        book_id=book.id,
        chunk_id=chunk.id,
        chapter_id=chunk.chapter_id,
        source_type=book.file_format,
        page_label=chunk.page_label_start,
        page_index=chunk.page_start,
        epub_location=(f"{loc.get('href')}#{loc.get('spine_index')}" if loc.get("href") else None),
        character_start=start,
        character_end=end,
        excerpt=excerpt_limit(sentence),
        document_version=book.content_hash,
        extraction_confidence=chunk.extraction_confidence,
    )
    db.add(ev)
    db.flush()
    return ev, score


def evidence_payload(db: Session, evidence_ids: list[str | uuid.UUID]) -> dict[str, dict]:
    ids = []
    for e in evidence_ids:
        try:
            ids.append(uuid.UUID(str(e)))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = db.execute(
        select(EvidenceReference, DocumentChunk.ordinal, DocumentChunk.section_title)
        .join(DocumentChunk, DocumentChunk.id == EvidenceReference.chunk_id)
        .where(EvidenceReference.id.in_(ids))
    ).all()
    return {str(ev.id): serialize_evidence(ev, ordinal, section) for ev, ordinal, section in rows}


def serialize_evidence(ev: EvidenceReference, ordinal: int | None = None, section: str | None = None) -> dict:
    return {
        "id": str(ev.id),
        "chunk_id": str(ev.chunk_id),
        "chapter_id": str(ev.chapter_id) if ev.chapter_id else None,
        "passage": f"P{ordinal}" if ordinal is not None else None,
        "section_title": section,
        "source_type": ev.source_type,
        "page_label": ev.page_label,
        "page_number": (ev.page_index + 1) if ev.page_index is not None else None,
        "epub_location": ev.epub_location,
        "character_start": ev.character_start,
        "character_end": ev.character_end,
        "excerpt": ev.excerpt,
        "extraction_confidence": ev.extraction_confidence,
    }
