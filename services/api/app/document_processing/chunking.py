"""Paragraph-aligned chunking with stable source-location mapping."""

from __future__ import annotations

from app.document_processing.text import split_sentences
from app.document_processing.types import Block, ChapterSpec, ChunkSpec, ExtractedDocument

TARGET_WORDS = 220
MAX_WORDS = 360
PARA_SEP = "\n\n"


def chapter_text_units(doc: ExtractedDocument, spec: ChapterSpec) -> list[tuple[Block, str]]:
    """Paragraph units of a chapter (headings excluded from the canonical text but tracked as section titles)."""
    units: list[tuple[Block, str]] = []
    for b in doc.blocks[spec.start_block : spec.end_block]:
        if b.kind == "paragraph":
            words = b.text.split()
            if len(words) <= MAX_WORDS:
                units.append((b, b.text))
            else:  # split very long paragraphs on sentence boundaries
                buf: list[str] = []
                count = 0
                for sent in split_sentences(b.text):
                    n = len(sent.split())
                    if buf and count + n > TARGET_WORDS:
                        units.append((b, " ".join(buf)))
                        buf, count = [], 0
                    buf.append(sent)
                    count += n
                if buf:
                    units.append((b, " ".join(buf)))
    return units


def chunk_chapter(
    doc: ExtractedDocument, spec: ChapterSpec, chapter_index: int
) -> tuple[list[ChunkSpec], str]:
    """Return chunks plus the chapter's canonical text (chunk offsets index into it)."""
    chunks: list[ChunkSpec] = []
    canonical_parts: list[str] = []
    offset = 0
    section: str | None = None
    buf: list[tuple[Block, str]] = []
    buf_words = 0
    buf_section: str | None = None

    def flush() -> None:
        nonlocal buf, buf_words
        if not buf:
            return
        text = PARA_SEP.join(t for _, t in buf)
        start = offset - len(text)
        first, last = buf[0][0], buf[-1][0]
        chunks.append(
            ChunkSpec(
                chapter_index=chapter_index,
                text=text,
                section_title=buf_section,
                char_start=start,
                char_end=offset,
                start_location=first.location(),
                end_location=last.location(),
                page_start=first.page_index,
                page_end=last.page_index,
                page_label_start=first.page_label,
                page_label_end=last.page_label,
                confidence=min(b.confidence for b, _ in buf),
            )
        )
        buf, buf_words = [], 0

    blocks = doc.blocks[spec.start_block : spec.end_block]
    units_by_block: dict[int, list[str]] = {}
    for b, t in chapter_text_units(doc, spec):
        units_by_block.setdefault(id(b), []).append(t)

    for b in blocks:
        if b.kind == "heading":
            if buf and b.level <= 2:
                flush()
            section = b.text[:300]
            continue
        for t in units_by_block.get(id(b), []):
            n = len(t.split())
            if buf and buf_words + n > MAX_WORDS:
                flush()
            if not buf:
                buf_section = section
            if canonical_parts:
                # separator between units inside the chapter text
                canonical_parts.append(PARA_SEP)
                offset += len(PARA_SEP)
                if not buf:
                    pass
            canonical_parts.append(t)
            offset += len(t)
            buf.append((b, t))
            buf_words += n
            if buf_words >= TARGET_WORDS:
                flush()
    flush()
    return chunks, "".join(canonical_parts)
