"""Chapter-aware hybrid retrieval (BM25 lexical + embedding similarity, fused with reciprocal rank fusion).

Every query is scoped to one book (and optionally one chapter). Callers must have verified ownership of the book
before retrieving; there is no cross-book search path.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings import cosine, get_embedder
from app.core.config import get_settings
from app.document_processing.text import content_words
from app.models.books import Chapter, DocumentChunk


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


@dataclass
class Retrieved:
    chunk: DocumentChunk
    score: float
    lexical: float
    semantic: float


def passage_id(chunk: DocumentChunk) -> str:
    return f"P{chunk.ordinal}"


def retrieve(
    db: Session, book_id: uuid.UUID, query: str, *, chapter_id: uuid.UUID | None = None, k: int = 6
) -> list[Retrieved]:
    stmt = select(DocumentChunk).where(DocumentChunk.book_id == book_id)
    if chapter_id is not None:
        stmt = stmt.where(DocumentChunk.chapter_id == chapter_id)
    chunks = list(db.scalars(stmt.order_by(DocumentChunk.ordinal)))
    if not chunks:
        return []

    # BM25
    q_terms = [_stem(t) for t in content_words(query)]
    docs = [[_stem(t) for t in content_words(c.text_content)] for c in chunks]
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / max(1, n)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    lexical: list[float] = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in set(q_terms):
            if tf[t]:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / max(1.0, avgdl)))
        lexical.append(s)

    # Embeddings (computed on PostgreSQL via pgvector ordering would also work; per-book sets are small enough
    # that scoring in-process keeps behaviour identical across databases).
    q_vec = get_embedder().embed([query])[0]
    semantic = [cosine(q_vec, c.embedding) for c in chunks]

    def ranks(values: list[float]) -> dict[int, int]:
        order = sorted(range(len(values)), key=lambda i: -values[i])
        return {i: r for r, i in enumerate(order)}

    lr, sr = ranks(lexical), ranks(semantic)
    fused = [
        (1 / (60 + lr[i]) + 1 / (60 + sr[i]), i) for i in range(n) if lexical[i] > 0 or semantic[i] > 0.05
    ]
    fused.sort(reverse=True)
    return [Retrieved(chunks[i], s, lexical[i], semantic[i]) for s, i in fused[:k]]


def render_passages(db: Session, chunks: list[DocumentChunk]) -> tuple[list[dict], str]:
    """Structured passages (for providers) and a delimited text rendering (for prompts)."""
    chapter_titles = {}
    ids = {c.chapter_id for c in chunks if c.chapter_id}
    if ids:
        chapter_titles = {ch.id: ch.title for ch in db.scalars(select(Chapter).where(Chapter.id.in_(ids)))}
    structured, lines = [], []
    for c in chunks:
        pid = passage_id(c)
        ch_title = chapter_titles.get(c.chapter_id, "")
        loc = []
        if ch_title:
            loc.append(ch_title)
        if c.section_title:
            loc.append(c.section_title)
        if c.page_label_start or c.page_start is not None:
            loc.append(f"page {c.page_label_start or (c.page_start or 0) + 1}")
        structured.append(
            {"id": pid, "text": c.text_content, "section": c.section_title, "chapter_title": ch_title}
        )
        body = c.text_content.replace("</passage", "&lt;/passage")
        lines.append(f'<passage id="{pid}" location="{" · ".join(loc)}">\n{body}\n</passage>')
    return structured, "\n".join(lines)


def token_budget_windows(
    chunks: list[DocumentChunk], max_tokens: int | None = None
) -> list[list[DocumentChunk]]:
    """Split chunks into windows that fit a prompt budget (used for hierarchical summarization)."""
    limit = max_tokens or max(3000, get_settings().max_generation_tokens)
    windows: list[list[DocumentChunk]] = [[]]
    used = 0
    for c in chunks:
        if windows[-1] and used + c.token_count > limit:
            windows.append([])
            used = 0
        windows[-1].append(c)
        used += c.token_count
    return [w for w in windows if w]
