"""PDF extraction with pypdf (BSD licensed).

Preserves physical page indices and printed page labels, removes running headers/footers and page numbers,
repairs hyphenation, rebuilds paragraphs and marks heading candidates. Scanned pages are detected and routed to
the configured OCR engine; if none is available the gap is disclosed as a warning.
"""

from __future__ import annotations

import io
import re
import time
from collections import Counter

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.document_processing.ocr import OCREngine, get_ocr_engine
from app.document_processing.text import collapse_whitespace, normalize_text
from app.document_processing.types import Block, ExtractedDocument, TocEntry

PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:page\s+)?(?:\d{1,4}|[ivxlcdm]{1,7})(?:\s+of\s+\d+)?\s*$", re.IGNORECASE
)
CHAPTER_LINE = re.compile(
    r"^(?:chapter|chap\.|part|book|section|prologue|epilogue|introduction|conclusion|preface|afterword|appendix"
    r"|अध्याय|भाग)\b",
    re.IGNORECASE,
)
JUNK_TITLES = re.compile(
    r"^(untitled|microsoft word|document\d*|\s*)$|\.(docx?|pdf|indd|tex)$", re.IGNORECASE
)
MIN_TEXT_CHARS = 25


def _clean_meta(value) -> str | None:
    if value is None:
        return None
    s = collapse_whitespace(str(value))
    if not s or JUNK_TITLES.search(s) or len(s) > 300:
        return None
    return s


def _flatten_outline(reader: PdfReader, items, level: int, out: list[TocEntry]) -> None:
    for item in items:
        if isinstance(item, list):
            _flatten_outline(reader, item, level + 1, out)
            continue
        try:
            page = reader.get_destination_page_number(item)
        except Exception:  # noqa: BLE001 - malformed outline entries are skipped
            continue
        title = collapse_whitespace(str(getattr(item, "title", "") or ""))
        if title and page is not None and page >= 0:
            out.append(TocEntry(title=title[:300], level=level, page_index=page))


def _signature(line: str) -> str:
    return re.sub(r"\d+", "#", collapse_whitespace(line).lower())


def _is_heading_candidate(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90 or len(s.split()) > 12:
        return False
    if CHAPTER_LINE.match(s):
        return True
    if s[-1] in ".,;:!?" and not s.endswith("?"):
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters if c.isascii()):
        return True
    return bool(re.match(r"^\d{1,2}(\.\d+)*\.?\s+[A-Z]", s))


def _page_lines(page) -> list[tuple[str, float]]:
    """Lines of text with their dominant (character-weighted) font size, via pypdf's text visitor."""
    frags: list[tuple[str, float]] = []

    def visitor(text, cm, tm, _font, font_size):
        if text:
            scale = abs(tm[0] or 1.0) * abs(cm[0] or 1.0)
            frags.append((text, round(float(font_size or 0) * scale, 1)))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:  # noqa: BLE001
        return []
    lines: list[tuple[str, float]] = []
    cur_text: list[str] = []
    cur_sizes: Counter[float] = Counter()
    for text, size in frags:
        parts = text.split("\n")
        for j, part in enumerate(parts):
            if part:
                cur_text.append(part)
                cur_sizes[size] += len(part.strip())
            if j < len(parts) - 1:
                line = normalize_text("".join(cur_text))
                lines.append((line, cur_sizes.most_common(1)[0][0] if cur_sizes else 0.0))
                cur_text, cur_sizes = [], Counter()
    if cur_text:
        lines.append(
            (normalize_text("".join(cur_text)), cur_sizes.most_common(1)[0][0] if cur_sizes else 0.0)
        )
    # Re-join hyphenated line breaks that normalize_text could not see across lines.
    joined: list[tuple[str, float]] = []
    for text, size in lines:
        if joined and joined[-1][0].endswith("-") and text[:1].islower():
            joined[-1] = (joined[-1][0][:-1] + text, joined[-1][1])
        else:
            joined.append((text, size))
    return joined


def _page_images(page) -> list[bytes]:
    try:
        return [img.data for img in page.images]
    except Exception:  # noqa: BLE001
        return []


def extract_pdf(data: bytes, ocr: OCREngine | None = None) -> ExtractedDocument:
    settings = get_settings()
    ocr = ocr or get_ocr_engine()
    started = time.monotonic()
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise FileNotDecryptedError("password required")
            except Exception as exc:  # noqa: BLE001
                raise AppError(
                    ErrorCode.PASSWORD_PROTECTED,
                    "This PDF is password-protected. Please upload an unlocked copy.",
                    status_code=422,
                ) from exc
        n_pages = len(reader.pages)
    except AppError:
        raise
    except (PdfReadError, Exception) as exc:  # noqa: BLE001
        raise AppError(
            ErrorCode.CORRUPTED_DOCUMENT,
            "This PDF appears to be damaged and could not be opened.",
            status_code=422,
        ) from exc

    if n_pages == 0:
        raise AppError(ErrorCode.CORRUPTED_DOCUMENT, "This PDF has no pages.", status_code=422)
    if n_pages > settings.max_document_pages:
        raise AppError(
            ErrorCode.DOCUMENT_TOO_LONG,
            f"This PDF has {n_pages} pages; the current limit is {settings.max_document_pages}.",
            status_code=422,
        )

    doc = ExtractedDocument(format="pdf", blocks=[], page_count=n_pages)
    try:
        meta = reader.metadata or {}
        doc.title = _clean_meta(meta.get("/Title"))
        doc.author = _clean_meta(meta.get("/Author"))
    except Exception:  # noqa: BLE001
        pass
    try:
        labels = list(reader.page_labels)
    except Exception:  # noqa: BLE001
        labels = []
    # Only keep labels if they differ from the trivial 1..n sequence (otherwise they add nothing).
    has_real_labels = bool(labels) and labels != [str(i + 1) for i in range(n_pages)]
    try:
        toc: list[TocEntry] = []
        _flatten_outline(reader, reader.outline, 1, toc)
        doc.toc = toc
    except Exception:  # noqa: BLE001
        doc.toc = []

    page_lines: list[list[tuple[str, float]]] = []
    page_conf: list[float] = []
    size_hist: Counter[float] = Counter()
    for idx, page in enumerate(reader.pages):
        if time.monotonic() - started > settings.max_processing_duration:
            raise AppError(ErrorCode.PROCESSING_TIMEOUT, "Text extraction took too long.", status_code=422)
        lines = _page_lines(page)
        conf = 1.0
        if sum(len(t) for t, _ in lines) < MIN_TEXT_CHARS:
            images = _page_images(page)
            if images and ocr.available:
                ocr_text = normalize_text("\n".join(ocr.image_to_text(img) for img in images))
                lines = [(ln, 0.0) for ln in ocr_text.split("\n")]
                conf = 0.7
                doc.ocr_pages += 1
            elif images:
                doc.unreadable_pages.append(idx)
        for t, size in lines:
            if size:
                size_hist[size] += len(t)
        page_lines.append(lines)
        page_conf.append(conf)
    body_size = size_hist.most_common(1)[0][0] if size_hist else 0.0

    # Running headers/footers: lines near the page edges that repeat on many pages.
    edge_counts: Counter[str] = Counter()
    for lines in page_lines:
        nonempty = [t for t, _ in lines if t.strip()]
        for ln in set(nonempty[:2] + nonempty[-2:]):
            edge_counts[_signature(ln)] += 1
    threshold = max(3, int(0.4 * n_pages))
    running = {sig for sig, c in edge_counts.items() if c >= threshold and len(sig) < 120}

    widths = [len(t) for lines in page_lines for t, _ in lines if t.strip()]
    typical = sorted(widths)[int(len(widths) * 0.8)] if widths else 80

    for idx, lines in enumerate(page_lines):
        label = labels[idx] if has_real_labels and idx < len(labels) else None
        nonempty_idx = [i for i, (t, _) in enumerate(lines) if t.strip()]
        edge = set(nonempty_idx[:2] + nonempty_idx[-2:])
        cleaned = [
            (t.strip(), size)
            for i, (t, size) in enumerate(lines)
            if not (i in edge and (_signature(t) in running or PAGE_NUMBER_LINE.match(t)))
        ]
        para: list[str] = []

        def flush() -> None:
            if para:
                txt = collapse_whitespace(" ".join(para))
                if txt:
                    doc.blocks.append(
                        Block(txt, "paragraph", page_index=idx, page_label=label, confidence=page_conf[idx])
                    )
                para.clear()

        def add_heading(text: str, level: int) -> None:
            last = doc.blocks[-1] if doc.blocks else None
            # A wrapped heading continues on the next line with the same size: merge it.
            if (
                last is not None
                and last.kind == "heading"
                and last.page_index == idx
                and last._size == size
                and not para
            ):
                last.text = collapse_whitespace(last.text + " " + text)
                return
            blk = Block(
                text, "heading", level=level, page_index=idx, page_label=label, confidence=page_conf[idx]
            )
            blk._size = size  # type: ignore[attr-defined]
            doc.blocks.append(blk)

        for i, (s_line, size) in enumerate(cleaned):
            if not s_line:
                flush()
                continue
            next_line = cleaned[i + 1][0] if i + 1 < len(cleaned) else ""
            by_font = bool(body_size and size >= body_size * 1.15 and len(s_line) <= 120)
            by_text = (
                not by_font
                and not para
                and _is_heading_candidate(s_line)
                and (not next_line or len(next_line) > len(s_line) or _is_heading_candidate(next_line))
                and (not body_size or size >= body_size)
            )
            if by_font or (CHAPTER_LINE.match(s_line) and len(s_line) <= 90 and not para) or by_text:
                flush()
                level = 1 if (CHAPTER_LINE.match(s_line) or (body_size and size >= body_size * 1.5)) else 2
                add_heading(s_line, level)
                continue
            para.append(s_line)
            ends_sentence = s_line[-1:] in '.!?:"”’)' or s_line.endswith("।")
            if ends_sentence and len(s_line) < 0.7 * typical:
                flush()
        flush()

    if doc.unreadable_pages:
        doc.warn(
            "ocr_unavailable" if not ocr.available else "extraction_gap",
            f"{len(doc.unreadable_pages)} page(s) appear to be scanned images and could not be read"
            + (" because OCR is not enabled." if not ocr.available else "."),
            pages=[p + 1 for p in doc.unreadable_pages[:50]],
        )
    if doc.ocr_pages:
        doc.warn(
            "ocr_used", f"{doc.ocr_pages} page(s) were read with OCR; minor recognition errors are possible."
        )
    doc.quality = _quality(doc, n_pages)
    return doc


def _quality(doc: ExtractedDocument, n_pages: int) -> float:
    text = " ".join(b.text for b in doc.blocks)
    if not text:
        return 0.0
    pages_with_text = len({b.page_index for b in doc.blocks})
    coverage = pages_with_text / max(1, n_pages)
    bad = sum(1 for c in text if c == "�" or (not c.isprintable() and c not in "\n\t"))
    garbage = bad / len(text)
    words = text.split()
    avg_len = sum(len(w) for w in words) / max(1, len(words))
    shape_penalty = 0.5 if avg_len > 15 or avg_len < 2 else 1.0
    return round(max(0.0, min(1.0, (0.4 + 0.6 * coverage) * (1 - 5 * garbage) * shape_penalty)), 3)
