"""Format-independent intermediate representation of an extracted document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph"]


@dataclass
class Block:
    text: str
    kind: BlockKind = "paragraph"
    level: int = 0  # heading level (1 = top) when kind == "heading"
    page_index: int | None = None  # physical 0-based PDF page index
    page_label: str | None = None  # printed page label when extractable
    spine_index: int | None = None  # EPUB spine position
    href: str | None = None  # EPUB document href
    anchors: list[str] = field(default_factory=list)  # EPUB element ids that resolve to this block
    confidence: float = 1.0  # extraction confidence (lower for OCR text)
    _size: float = 0.0  # internal: font size used while building PDF headings

    def location(self) -> dict:
        loc: dict = {}
        if self.page_index is not None:
            loc["page_index"] = self.page_index
            if self.page_label is not None:
                loc["page_label"] = self.page_label
        if self.spine_index is not None:
            loc["spine_index"] = self.spine_index
            loc["href"] = self.href
        return loc


@dataclass
class TocEntry:
    title: str
    level: int
    page_index: int | None = None
    href: str | None = None
    fragment: str | None = None


@dataclass
class ExtractedDocument:
    format: Literal["pdf", "epub"]
    blocks: list[Block]
    title: str | None = None
    author: str | None = None
    language: str | None = None
    toc: list[TocEntry] = field(default_factory=list)
    page_count: int | None = None
    warnings: list[dict] = field(default_factory=list)
    quality: float = 1.0
    ocr_pages: int = 0
    unreadable_pages: list[int] = field(default_factory=list)

    def warn(self, code: str, message: str, **details) -> None:
        self.warnings.append({"code": code, "message": message, **details})


@dataclass
class ChapterSpec:
    title: str
    start_block: int
    end_block: int  # exclusive
    method: str
    confidence: float


@dataclass
class ChunkSpec:
    chapter_index: int
    text: str
    section_title: str | None
    char_start: int  # offsets into the chapter's canonical text
    char_end: int
    start_location: dict
    end_location: dict
    page_start: int | None
    page_end: int | None
    page_label_start: str | None
    page_label_end: str | None
    confidence: float
