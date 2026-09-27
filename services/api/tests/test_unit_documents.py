"""Unit tests: validation, PDF/EPUB extraction, chapter detection, chunking and source mapping."""

import io
import zipfile

import pytest

from app.core.errors import AppError, ErrorCode
from app.document_processing.chunking import chunk_chapter
from app.document_processing.epub import extract_epub
from app.document_processing.pdf import extract_pdf
from app.document_processing.structure import detect_chapters
from app.document_processing.text import detect_language, fuzzy_contains, normalize_text, split_sentences
from app.document_processing.validation import sanitize_filename, validate_upload
from tests.conftest import fixture_bytes


# ------------------------------------------------------------------ text
def test_normalize_repairs_hyphenation_and_ligatures():
    assert normalize_text("infor-\nmation ﬁne") == "information fine"


def test_sentence_split_handles_abbreviations_and_devanagari():
    assert split_sentences("Dr. Smith left. He slept.") == ["Dr. Smith left.", "He slept."]
    assert len(split_sentences("यह एक वाक्य है। दूसरा वाक्य।")) == 2


def test_language_detection():
    assert (
        detect_language("The reader and the book are in the room with all of the notes for a while.") == "en"
    )
    assert (
        detect_language("लेखिका के अनुसार रोज़ थोड़ी देर पढ़ना कभी-कभी लंबे समय तक पढ़ने से अधिक उपयोगी है।" * 3) == "hi"
    )
    assert detect_language("12345") is None


def test_fuzzy_contains():
    assert fuzzy_contains("The switching tax is small for a single interruption.", "switching tax is small")
    assert not fuzzy_contains("The switching tax is small.", "the ledger records pages")


# ------------------------------------------------------------------ validation
def test_filename_sanitized_against_traversal():
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert "/" not in sanitize_filename("a/b\\c.pdf")


@pytest.mark.parametrize(
    "name,mime,data,code",
    [
        ("notes.txt", "text/plain", b"hello", ErrorCode.UNSUPPORTED_FILE),
        ("fake.pdf", "application/pdf", b"not a pdf at all", ErrorCode.UNSUPPORTED_FILE),
        ("book.pdf", "image/png", b"%PDF-1.7 ...", ErrorCode.UNSUPPORTED_FILE),
        ("empty.pdf", "application/pdf", b"", ErrorCode.CORRUPTED_DOCUMENT),
        ("fake.epub", "application/epub+zip", b"PK\x03\x04garbage", ErrorCode.CORRUPTED_DOCUMENT),
    ],
)
def test_upload_validation_rejects(name, mime, data, code):
    with pytest.raises(AppError) as exc:
        validate_upload(name, mime, data)
    assert exc.value.code == code


def test_upload_size_limit(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    get_settings.cache_clear()
    with pytest.raises(AppError) as exc:
        validate_upload("big.pdf", "application/pdf", b"%PDF-" + b"0" * (1024 * 1024 + 10))
    assert exc.value.code == ErrorCode.FILE_TOO_LARGE
    get_settings.cache_clear()


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_epub_zip_bomb_and_traversal_rejected():
    bomb = _zip(
        {"mimetype": b"application/epub+zip", "META-INF/container.xml": b"<x/>", "big.txt": b"0" * 20_000_000}
    )
    with pytest.raises(AppError):
        validate_upload("bomb.epub", "application/epub+zip", bomb)
    evil = _zip(
        {"mimetype": b"application/epub+zip", "../evil.xhtml": b"x", "META-INF/container.xml": b"<x/>"}
    )
    with pytest.raises(AppError):
        validate_upload("evil.epub", "application/epub+zip", evil)


def test_epub_xml_entity_attack_rejected():
    xxe = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><container>&x;</container>'
    data = _zip({"mimetype": b"application/epub+zip", "META-INF/container.xml": xxe})
    with pytest.raises(AppError) as exc:
        extract_epub(data)
    assert exc.value.code == ErrorCode.CORRUPTED_DOCUMENT


# ------------------------------------------------------------------ PDF
def test_pdf_extraction_metadata_outline_and_pages():
    doc = extract_pdf(fixture_bytes("attentive_mind.pdf"))
    assert doc.title == "The Attentive Mind" and doc.author == "Mira Solen"
    assert len(doc.toc) == 4
    headings = [b.text for b in doc.blocks if b.kind == "heading"]
    assert "Chapter 3: Memory and the Testing Effect" in headings  # wrapped heading merged
    body = " ".join(b.text for b in doc.blocks)
    assert "The Attentive Mind The Attentive Mind" not in body  # running header removed
    assert all(b.page_index is not None for b in doc.blocks)


def test_pdf_encrypted_and_malformed():
    with pytest.raises(AppError) as exc:
        extract_pdf(fixture_bytes("encrypted.pdf"))
    assert exc.value.code == ErrorCode.PASSWORD_PROTECTED
    with pytest.raises(AppError) as exc:
        extract_pdf(fixture_bytes("malformed.pdf"))
    assert exc.value.code == ErrorCode.CORRUPTED_DOCUMENT


def test_scanned_pdf_reports_ocr_gap():
    doc = extract_pdf(fixture_bytes("scanned.pdf"))
    assert doc.blocks == []
    assert doc.unreadable_pages == [0, 1]
    assert doc.warnings[0]["code"] == "ocr_unavailable"


def test_scanned_pdf_uses_ocr_when_available():
    from app.document_processing.ocr import OCREngine

    class FakeOCR(OCREngine):
        name = "fake"

        @property
        def available(self):
            return True

        def image_to_text(self, image_bytes, language="eng"):
            return "Recognised text from a scanned page about lighthouses and their keepers. " * 3

    doc = extract_pdf(fixture_bytes("scanned.pdf"), ocr=FakeOCR())
    assert doc.ocr_pages == 2
    assert all(b.confidence < 1 for b in doc.blocks)


# ------------------------------------------------------------------ EPUB
def test_epub_extraction_strips_scripts_and_reads_nav():
    doc = extract_epub(fixture_bytes("backyard_compost.epub"))
    assert doc.title.startswith("Backyard Compost")
    assert doc.language == "en"
    assert len(doc.toc) == 3
    assert not any("alert(" in b.text for b in doc.blocks)
    assert all(b.spine_index is not None for b in doc.blocks)


def test_epub2_ncx_toc():
    doc = extract_epub(fixture_bytes("hindi_reading.epub"))
    assert [t.title for t in doc.toc] == ["अध्याय 1: रोज़ पढ़ना", "अध्याय 2: याद रखना"]


# ------------------------------------------------------------------ structure + chunking
@pytest.mark.parametrize(
    "name,method,count",
    [
        ("attentive_mind.pdf", "pdf_outline", 4),
        ("attentive_mind_no_outline.pdf", "heading_pattern", 4),
        ("attentive_mind.epub", "epub_navigation", 4),
        ("backyard_compost.epub", "epub_navigation", 3),
        ("no_structure.pdf", "fallback_segments", 1),
    ],
)
def test_chapter_detection(name, method, count):
    data = fixture_bytes(name)
    doc = extract_pdf(data) if name.endswith(".pdf") else extract_epub(data)
    specs, confidence = detect_chapters(doc)
    assert len(specs) == count
    assert specs[0].method == method
    if method == "fallback_segments":
        assert confidence < 0.5
        assert "no chapter headings detected" in specs[0].title  # disclosed, not invented


def test_chunks_have_stable_offsets_and_locations():
    doc = extract_epub(fixture_bytes("backyard_compost.epub"))
    specs, _ = detect_chapters(doc)
    for i, spec in enumerate(specs):
        chunks, text = chunk_chapter(doc, spec, i)
        assert chunks
        for c in chunks:
            assert text[c.char_start : c.char_end] == c.text
            assert "spine_index" in c.start_location
    chunks, _ = chunk_chapter(doc, specs[0], 0)
    assert {c.section_title for c in chunks} == {"The four ingredients", "Moisture and air"}
