"""EPUB 2/3 extraction without third-party EPUB libraries.

Reads the OPF package (via defusedxml), follows the spine in reading order, reads the navigation document (EPUB 3)
or NCX (EPUB 2) for the table of contents, and extracts text blocks from sanitized XHTML. Scripts, styles and
embedded active content are discarded; no markup ever reaches the client.
"""

from __future__ import annotations

import io
import posixpath
import warnings
import zipfile
from urllib.parse import unquote, urldefrag

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from defusedxml import ElementTree as SafeET

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.document_processing.text import collapse_whitespace, normalize_text
from app.document_processing.types import Block, ExtractedDocument, TocEntry
from app.document_processing.validation import check_epub_archive

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
STRIP_TAGS = [
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "form",
    "input",
    "button",
    "noscript",
    "audio",
    "video",
    "canvas",
    "template",
    "head",
]
BLOCK_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "blockquote",
    "pre",
    "dt",
    "dd",
    "figcaption",
    "td",
    "th",
    "caption",
}
MAX_MEMBER_BYTES = 20 * 1024 * 1024


def _read(zf: zipfile.ZipFile, name: str) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > MAX_MEMBER_BYTES:
        raise AppError(ErrorCode.FILE_TOO_LARGE, "An EPUB section is too large to process.", status_code=422)
    return zf.read(name)


def _resolve(base_dir: str, href: str) -> str:
    return (
        posixpath.normpath(posixpath.join(base_dir, unquote(href)))
        if base_dir
        else posixpath.normpath(unquote(href))
    )


def extract_epub(data: bytes) -> ExtractedDocument:
    check_epub_archive(data)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        container = SafeET.fromstring(_read(zf, "META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", NS)
        if rootfile is None:
            raise ValueError("no rootfile")
        opf_path = rootfile.attrib["full-path"]
        opf = SafeET.fromstring(_read(zf, opf_path))
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            ErrorCode.CORRUPTED_DOCUMENT, "The EPUB package could not be read.", status_code=422
        ) from exc

    base = posixpath.dirname(opf_path)
    doc = ExtractedDocument(format="epub", blocks=[])
    md = opf.find("opf:metadata", NS)
    if md is not None:
        t = md.find("dc:title", NS)
        a = md.find("dc:creator", NS)
        lang = md.find("dc:language", NS)
        doc.title = collapse_whitespace(t.text or "") or None if t is not None and t.text else None
        doc.author = collapse_whitespace(a.text or "") or None if a is not None and a.text else None
        doc.language = (
            (lang.text or "").strip().split("-")[0].lower() or None
            if lang is not None and lang.text
            else None
        )

    manifest: dict[str, dict] = {}
    for item in opf.findall("opf:manifest/opf:item", NS):
        manifest[item.attrib.get("id", "")] = {
            "href": _resolve(base, item.attrib.get("href", "")),
            "media": item.attrib.get("media-type", ""),
            "props": item.attrib.get("properties", ""),
        }
    spine_el = opf.find("opf:spine", NS)
    if spine_el is None:
        raise AppError(
            ErrorCode.CORRUPTED_DOCUMENT, "The EPUB has no reading order (spine).", status_code=422
        )
    spine = []
    for ref in spine_el.findall("opf:itemref", NS):
        item = manifest.get(ref.attrib.get("idref", ""))
        if item and item["media"] in ("application/xhtml+xml", "text/html"):
            spine.append(item["href"])
    if len(spine) > get_settings().max_document_pages:
        raise AppError(
            ErrorCode.DOCUMENT_TOO_LONG, "This EPUB has too many sections to process.", status_code=422
        )
    doc.page_count = None

    # Table of contents: EPUB3 nav document first, then EPUB2 NCX.
    names = set(zf.namelist())
    nav = next((m for m in manifest.values() if "nav" in m["props"].split()), None)
    if nav and nav["href"] in names:
        doc.toc = _parse_nav(_read(zf, nav["href"]), posixpath.dirname(nav["href"]))
    if not doc.toc:
        toc_id = spine_el.attrib.get("toc")
        ncx = manifest.get(toc_id or "") or next(
            (m for m in manifest.values() if m["media"] == "application/x-dtbncx+xml"), None
        )
        if ncx and ncx["href"] in names:
            doc.toc = _parse_ncx(_read(zf, ncx["href"]), posixpath.dirname(ncx["href"]))

    nav_href = nav["href"] if nav else None
    for spine_index, href in enumerate(spine):
        if href not in names or href == nav_href:
            continue
        _extract_xhtml(_read(zf, href), href, spine_index, doc)

    words = sum(len(b.text.split()) for b in doc.blocks)
    doc.quality = 1.0 if words > 0 else 0.0
    return doc


def _parse_nav(raw: bytes, base: str) -> list[TocEntry]:
    soup = BeautifulSoup(raw, "lxml")
    navs = soup.find_all("nav")
    toc_nav = next(
        (n for n in navs if "toc" in (n.get("epub:type") or n.get("type") or "")), navs[0] if navs else None
    )
    if toc_nav is None:
        return []
    out: list[TocEntry] = []

    def walk(ol, level: int) -> None:
        for li in ol.find_all("li", recursive=False):
            a = li.find(["a", "span"], recursive=False)
            if a is not None:
                title = collapse_whitespace(a.get_text(" "))
                href = a.get("href")
                if title and href:
                    path, frag = urldefrag(href)
                    out.append(
                        TocEntry(
                            title=title[:300], level=level, href=_resolve(base, path), fragment=frag or None
                        )
                    )
            child = li.find("ol", recursive=False)
            if child is not None:
                walk(child, level + 1)

    root = toc_nav.find("ol")
    if root is not None:
        walk(root, 1)
    return out


def _parse_ncx(raw: bytes, base: str) -> list[TocEntry]:
    root = SafeET.fromstring(raw)
    out: list[TocEntry] = []

    def walk(parent, level: int) -> None:
        for np in parent.findall("ncx:navPoint", NS):
            label = np.find("ncx:navLabel/ncx:text", NS)
            content = np.find("ncx:content", NS)
            if label is not None and content is not None and label.text:
                path, frag = urldefrag(content.attrib.get("src", ""))
                out.append(
                    TocEntry(
                        title=collapse_whitespace(label.text)[:300],
                        level=level,
                        href=_resolve(base, path),
                        fragment=frag or None,
                    )
                )
            walk(np, level + 1)

    nav_map = root.find("ncx:navMap", NS)
    if nav_map is not None:
        walk(nav_map, 1)
    return out


def _extract_xhtml(raw: bytes, href: str, spine_index: int, doc: ExtractedDocument) -> None:
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()
    body = soup.body or soup
    pending_anchors: list[str] = []
    # Anchor ids for the document itself resolve to its first block.
    pending_anchors.append("")

    def emit(text: str, kind: str, level: int) -> None:
        text = collapse_whitespace(normalize_text(text))
        if not text:
            return
        doc.blocks.append(
            Block(text, kind, level=level, spine_index=spine_index, href=href, anchors=list(pending_anchors))  # type: ignore[arg-type]
        )
        pending_anchors.clear()

    for el in body.descendants:
        name = getattr(el, "name", None)
        if name is None:
            continue
        if el.get("id"):
            pending_anchors.append(el["id"])
        if name in BLOCK_TAGS:
            if any(getattr(p, "name", None) in BLOCK_TAGS for p in el.parents):
                continue
            if name.startswith("h") and len(name) == 2:
                emit(el.get_text(" "), "heading", int(name[1]))
            else:
                emit(el.get_text(" "), "paragraph", 0)
        elif name == "div":
            has_block_child = el.find(list(BLOCK_TAGS) + ["div"]) is not None
            in_block = any(getattr(p, "name", None) in BLOCK_TAGS for p in el.parents)
            if not has_block_child and not in_block:
                emit(el.get_text(" "), "paragraph", 0)
