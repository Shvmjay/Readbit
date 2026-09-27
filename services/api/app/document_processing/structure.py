"""Chapter detection. Structure first (TOC/outline, EPUB navigation, headings), conservative fallbacks after.

Never invents chapter names: fallback segments are labelled as such and flagged with low confidence.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.document_processing.text import collapse_whitespace, normalize_for_match
from app.document_processing.types import Block, ChapterSpec, ExtractedDocument, TocEntry

CHAPTER_HEADING = re.compile(
    r"^(?:(?:chapter|chap\.|part|book|अध्याय|भाग)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b"
    r"|prologue\b|epilogue\b|introduction\b|conclusion\b|preface\b|afterword\b|foreword\b|appendix\b)",
    re.IGNORECASE,
)
NUMBERED_HEADING = re.compile(r"^\d{1,2}\.?\s+\S")
NON_CONTENT_TITLES = re.compile(
    r"^(contents|table of contents|copyright|dedication|index|also by|cover|title page|acknowledg(e)?ments?)$",
    re.IGNORECASE,
)
MIN_CHAPTER_WORDS = 40
FALLBACK_SEGMENT_WORDS = 3000


def _words(blocks: list[Block]) -> int:
    return sum(len(b.text.split()) for b in blocks)


def _toc_level_entries(toc: list[TocEntry]) -> list[TocEntry]:
    if not toc:
        return []
    top = min(e.level for e in toc)
    entries = [e for e in toc if e.level == top]
    # A single wrapping entry (e.g. the book title) → use its children instead.
    if len(entries) == 1:
        children = [e for e in toc if e.level == top + 1]
        if len(children) >= 2:
            entries = children
    return [e for e in entries if not NON_CONTENT_TITLES.match(e.title.strip())]


def _map_toc_entry(doc: ExtractedDocument, entry: TocEntry) -> int | None:
    blocks = doc.blocks
    if doc.format == "pdf" and entry.page_index is not None:
        on_page = [i for i, b in enumerate(blocks) if b.page_index == entry.page_index]
        if not on_page:
            later = [i for i, b in enumerate(blocks) if (b.page_index or 0) > entry.page_index]
            return later[0] if later else None
        target = normalize_for_match(entry.title)
        best, best_score = on_page[0], 0.0
        for i in on_page:
            if blocks[i].kind != "heading" and len(blocks[i].text) > 120:
                continue
            score = SequenceMatcher(None, normalize_for_match(blocks[i].text), target).ratio()
            if score > best_score:
                best, best_score = i, score
        return best if best_score >= 0.6 else on_page[0]
    if doc.format == "epub" and entry.href:
        for i, b in enumerate(blocks):
            if b.href == entry.href and (entry.fragment is None or entry.fragment in b.anchors or "" in b.anchors and entry.fragment is None):
                if entry.fragment is None or entry.fragment in b.anchors:
                    return i
        # Fragment not found → first block of that document.
        for i, b in enumerate(blocks):
            if b.href == entry.href:
                return i
    return None


def _from_starts(doc: ExtractedDocument, starts: list[tuple[int, str]], method: str, conf: float) -> list[ChapterSpec]:
    starts = sorted({s: t for s, t in starts}.items())
    specs: list[ChapterSpec] = []
    n = len(doc.blocks)
    if starts and starts[0][0] > 0 and _words(doc.blocks[: starts[0][0]]) >= 150:
        specs.append(ChapterSpec("Front matter (before the first detected chapter)", 0, starts[0][0], "front_matter", conf))
    # Shorter front matter (title page, copyright lines) is excluded from chapter text.
    for k, (start, title) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else n
        if end > start:
            specs.append(ChapterSpec(title, start, end, method, conf))
    # Merge chapters that are too small to be meaningful into their neighbour (keeps the first title).
    merged: list[ChapterSpec] = []
    for spec in specs:
        if merged and _words(doc.blocks[spec.start_block : spec.end_block]) < MIN_CHAPTER_WORDS and spec.method != "front_matter":
            # A heading-only "part" divider: attach its blocks to the next chapter by extending the previous one.
            merged[-1].end_block = spec.end_block
            continue
        merged.append(spec)
    return merged


def detect_chapters(doc: ExtractedDocument) -> tuple[list[ChapterSpec], float]:
    """Return chapter specs and overall structure confidence (0–1)."""
    n = len(doc.blocks)
    if n == 0:
        return [], 0.0

    # 1–3. Embedded table of contents / PDF bookmarks / EPUB navigation.
    entries = _toc_level_entries(doc.toc)
    if len(entries) >= 2:
        starts = []
        for e in entries:
            idx = _map_toc_entry(doc, e)
            if idx is not None:
                starts.append((idx, e.title))
        if len({s for s, _ in starts}) >= 2:
            method = "pdf_outline" if doc.format == "pdf" else "epub_navigation"
            return _from_starts(doc, starts, method, 0.95), 0.95

    # 4–5. Heading hierarchy and numbered chapter patterns.
    heading_starts: list[tuple[int, str]] = []
    i = 0
    while i < n:
        b = doc.blocks[i]
        text = b.text.strip()
        is_chapter = CHAPTER_HEADING.match(text) or (b.kind == "heading" and b.level == 1 and doc.format == "epub")
        if b.kind == "heading" and is_chapter and len(text) <= 120:
            title = text
            # "Chapter 3" followed by a short heading line → "Chapter 3: The Title"
            if i + 1 < n and doc.blocks[i + 1].kind == "heading" and len(text.split()) <= 3:
                title = f"{text}: {doc.blocks[i + 1].text.strip()}"
            heading_starts.append((i, collapse_whitespace(title)[:300]))
        i += 1
    if len(heading_starts) >= 2:
        return _from_starts(doc, heading_starts, "heading_pattern", 0.8), 0.8

    if doc.format == "epub":
        # One chapter per spine document that starts with a heading.
        spine_starts: list[tuple[int, str]] = []
        seen: set[int | None] = set()
        for idx, b in enumerate(doc.blocks):
            if b.spine_index not in seen:
                seen.add(b.spine_index)
                if b.kind == "heading":
                    spine_starts.append((idx, b.text[:300]))
        if len(spine_starts) >= 2:
            return _from_starts(doc, spine_starts, "epub_spine", 0.7), 0.7

    numbered = [(i, b.text) for i, b in enumerate(doc.blocks) if b.kind == "heading" and NUMBERED_HEADING.match(b.text)]
    if len(numbered) >= 2:
        return _from_starts(doc, numbered, "numbered_heading", 0.65), 0.65

    return fallback_segments(doc), 0.3


def fallback_segments(doc: ExtractedDocument) -> list[ChapterSpec]:
    """Disclosed, paragraph-aligned segmentation used when no reliable structure exists."""
    specs: list[ChapterSpec] = []
    start, words = 0, 0
    for i, b in enumerate(doc.blocks):
        words += len(b.text.split())
        if words >= FALLBACK_SEGMENT_WORDS and i + 1 < len(doc.blocks):
            specs.append(ChapterSpec("", start, i + 1, "fallback_segments", 0.3))
            start, words = i + 1, 0
    if start < len(doc.blocks):
        specs.append(ChapterSpec("", start, len(doc.blocks), "fallback_segments", 0.3))
    for k, spec in enumerate(specs, 1):
        blocks = doc.blocks[spec.start_block : spec.end_block]
        pages = [b.page_index for b in blocks if b.page_index is not None]
        if pages:
            spec.title = f"Section {k} (pages {min(pages) + 1}–{max(pages) + 1}, no chapter headings detected)"
        else:
            spec.title = f"Section {k} (no chapter headings detected)"
        if len(specs) == 1:
            spec.title = "Full text (no chapter headings detected)"
    return specs


def apply_llm_boundaries(doc: ExtractedDocument, indices: list[int]) -> list[ChapterSpec]:
    """Build chapters from model-proposed heading block indices (validated: must be existing heading-like blocks)."""
    valid = sorted({i for i in indices if 0 <= i < len(doc.blocks) and len(doc.blocks[i].text) <= 120})
    starts = [(i, doc.blocks[i].text.strip()) for i in valid]
    return _from_starts(doc, starts, "model_assisted", 0.6)
