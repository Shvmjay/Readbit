#!/usr/bin/env python3
"""Generate deterministic PDF/EPUB fixtures from the synthetic corpus in evals/datasets/books.

All text is original and CC0. Outputs go to evals/fixtures/. Run from the repository root:

    python scripts/generate_fixtures.py
"""

from __future__ import annotations

import io
import json
import zipfile
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOKS = ROOT / "evals" / "datasets" / "books"
OUT = ROOT / "evals" / "fixtures"


def load(book_id: str) -> dict:
    return json.loads((BOOKS / f"{book_id}.json").read_text(encoding="utf-8"))


def chapter_sections(ch: dict) -> list[tuple[str | None, list[str]]]:
    if "sections" in ch:
        return [(s["heading"], s["paragraphs"]) for s in ch["sections"]]
    return [(None, ch["paragraphs"])]


# ---------------------------------------------------------------- PDF
def make_pdf(book: dict, *, outline: bool = True, headings: bool = True, running_header: bool = True) -> bytes:
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    title = book["title"]

    class Doc(SimpleDocTemplate):
        def afterFlowable(self, flowable):  # noqa: N802 - reportlab API
            if outline and isinstance(flowable, Paragraph) and getattr(flowable, "_bookmark", None):
                key = flowable._bookmark
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(flowable.getPlainText(), key, level=0)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        if running_header:
            canvas.drawString(40, A5[1] - 30, title)
        canvas.drawCentredString(A5[0] / 2, 25, str(doc.page))
        canvas.restoreState()

    doc = Doc(buf, pagesize=A5, title=title, author=book.get("author") or "", leftMargin=40, rightMargin=40,
              topMargin=50, bottomMargin=45)
    story = [Paragraph(escape(title), styles["Title"])]
    if book.get("author"):
        story.append(Paragraph(escape(book["author"]), styles["Normal"]))
    story.append(PageBreak())
    for i, ch in enumerate(book["chapters"]):
        if headings:
            h = Paragraph(escape(ch["title"]), styles["Heading1"])
            h._bookmark = f"ch{i}"
            story.append(h)
        for heading, paras in chapter_sections(ch):
            if heading and headings:
                story.append(Paragraph(escape(heading), styles["Heading2"]))
            for p in paras:
                story.append(Paragraph(escape(p), styles["BodyText"]))
                story.append(Spacer(1, 6))
        story.append(PageBreak())
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def make_scanned_pdf() -> bytes:
    """A PDF whose only page is an image (no text layer)."""
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    png = _tiny_png()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    for _ in range(2):
        c.drawImage(ImageReader(io.BytesIO(png)), 40, 40, width=300, height=500)
        c.showPage()
    c.save()
    return buf.getvalue()


def _tiny_png() -> bytes:
    import struct
    import zlib

    width, height = 8, 8
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_encrypted_pdf(src: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(src))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password="secret-pass", owner_password="owner-pass")  # noqa: S106 - test fixture
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ---------------------------------------------------------------- EPUB
def make_epub(book: dict, *, version: int = 3) -> bytes:
    lang = book.get("language", "en")
    files: list[tuple[str, str]] = []
    nav_items = []
    ncx_points = []
    for i, ch in enumerate(book["chapters"], 1):
        body = [f'<h1 id="c{i}">{escape(ch["title"])}</h1>']
        for s, (heading, paras) in enumerate(chapter_sections(ch)):
            if heading:
                body.append(f'<h2 id="c{i}s{s}">{escape(heading)}</h2>')
            body.extend(f"<p>{escape(p)}</p>" for p in paras)
        body.append('<script>alert("this script must be stripped")</script>')
        html = (
            '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}">'
            f'<head><title>{escape(ch["title"])}</title><style>p{{margin:0}}</style></head>'
            f'<body>{"".join(body)}</body></html>'
        )
        files.append((f"OEBPS/ch{i}.xhtml", html))
        nav_items.append(f'<li><a href="ch{i}.xhtml#c{i}">{escape(ch["title"])}</a></li>')
        ncx_points.append(
            f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{escape(ch["title"])}</text></navLabel>'
            f'<content src="ch{i}.xhtml"/></navPoint>'
        )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body>'
        f'<nav epub:type="toc"><h1>Contents</h1><ol>{"".join(nav_items)}</ol></nav></body></html>'
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head/><docTitle><text>{escape(book["title"])}</text></docTitle><navMap>{"".join(ncx_points)}</navMap></ncx>'
    )
    manifest = "".join(
        f'<item id="ch{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(1, len(files) + 1)
    )
    spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(1, len(files) + 1))
    if version == 3:
        manifest += '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    manifest += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    creator = f"<dc:creator>{escape(book['author'])}</dc:creator>" if book.get("author") else ""
    opf = (
        f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="{version}.0" '
        'unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="bookid">urn:readbit:{book["id"]}</dc:identifier><dc:title>{escape(book["title"])}</dc:title>'
        f"{creator}<dc:language>{lang}</dc:language></metadata>"
        f'<manifest>{manifest}</manifest><spine toc="ncx">{spine}</spine></package>'
    )
    container = (
        '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
        "</container>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        if version == 3:
            zf.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        for name, content in files:
            zf.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mind = load("attentive_mind")
    compost = load("backyard_compost")
    hindi = load("hindi_reading")
    injection = load("injection_test")

    outputs: dict[str, bytes] = {
        "attentive_mind.pdf": make_pdf(mind),
        "attentive_mind_no_outline.pdf": make_pdf(mind, outline=False),
        "attentive_mind.epub": make_epub(mind),
        "backyard_compost.epub": make_epub(compost),
        "backyard_compost.pdf": make_pdf(compost),
        "hindi_reading.epub": make_epub(hindi, version=2),
        "injection_test.pdf": make_pdf(injection),
        "no_structure.pdf": make_pdf(mind, outline=False, headings=False, running_header=False),
        "scanned.pdf": make_scanned_pdf(),
        "malformed.pdf": b"%PDF-1.7\n1 0 obj << /Type /Catalog /Pages 2 0 R >>\nthis is not a real pdf\n%%EOF",
        "fake_pdf.pdf": b"Just some text pretending to be a PDF file.",
        "notes.txt": b"Plain text is not a supported upload format.",
    }
    outputs["encrypted.pdf"] = make_encrypted_pdf(outputs["attentive_mind.pdf"])
    for name, data in outputs.items():
        (OUT / name).write_bytes(data)
        print(f"wrote {name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
