"""Integration: upload → processing lifecycle, failures, duplicates, retry, deletion, retention."""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.db import SessionLocal
from app.models.books import Book, DocumentChunk, EvidenceReference, SourceFile
from app.models.users import GuestSession
from app.services.retention import run_retention_cleanup
from app.storage.base import get_storage
from tests.conftest import fixture_bytes, make_client, start_guest, upload


def _post_file(client, name, mime):
    return client.post("/api/v1/books/upload", files={"file": (name, fixture_bytes(name), mime)})


def test_unauthenticated_upload_rejected(client):
    r = _post_file(client, "attentive_mind.pdf", "application/pdf")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_epub_processing_with_sections(guest):
    book = upload(guest, "backyard_compost.epub")
    b = guest.get(f"/api/v1/books/{book['id']}").json()["book"]
    assert b["processing_status"] == "ready" and b["file_format"] == "epub"
    assert b["detected_language"] == "en" and b["chapter_count"] == 3
    status = guest.get(f"/api/v1/books/{book['id']}/processing-status").json()
    assert status["job"]["status"] == "succeeded" and status["job"]["progress_percent"] == 100
    ch = guest.get(f"/api/v1/books/{book['id']}/chapters").json()["items"][0]
    passages = guest.get(f"/api/v1/books/{book['id']}/chapters/{ch['id']}/passages").json()["items"]
    assert passages[0]["section_title"] == "The four ingredients"


def test_unsupported_and_fake_files_rejected_with_actionable_message(guest):
    r = _post_file(guest, "notes.txt", "text/plain")
    assert r.status_code == 415 and "PDF and EPUB" in r.json()["error"]["message"]
    r = _post_file(guest, "fake_pdf.pdf", "application/pdf")
    assert r.status_code == 415
    assert guest.get("/api/v1/books").json()["items"] == []


def test_malformed_pdf_fails_visibly_and_is_never_ready(guest):
    r = _post_file(guest, "malformed.pdf", "application/pdf")
    assert r.status_code == 202
    bid = r.json()["book"]["id"]
    st = guest.get(f"/api/v1/books/{bid}/processing-status").json()
    assert st["processing_status"] == "failed"
    assert st["job"]["error"]["code"] == "corrupted_document"
    assert guest.post(f"/api/v1/books/{bid}/summaries", json={"depth": "concise"}).status_code == 409
    # retry is allowed and fails again deterministically; the book is still not ready
    assert guest.post(f"/api/v1/books/{bid}/retry").status_code == 202
    assert guest.get(f"/api/v1/books/{bid}").json()["book"]["processing_status"] == "failed"


def test_encrypted_and_scanned_pdfs_fail_with_specific_codes(guest):
    enc = _post_file(guest, "encrypted.pdf", "application/pdf").json()["book"]["id"]
    assert (
        guest.get(f"/api/v1/books/{enc}/processing-status").json()["job"]["error"]["code"]
        == "password_protected"
    )
    scan = _post_file(guest, "scanned.pdf", "application/pdf").json()["book"]["id"]
    assert (
        guest.get(f"/api/v1/books/{scan}/processing-status").json()["job"]["error"]["code"]
        == "ocr_unavailable"
    )


def test_no_structure_book_is_ready_with_disclosed_warning(guest):
    book = upload(guest, "no_structure.pdf")
    b = guest.get(f"/api/v1/books/{book['id']}").json()["book"]
    assert b["processing_status"] == "ready"
    assert any(w["code"] == "chapter_detection_uncertain" for w in b["warnings"])


def test_duplicate_upload_reuses_existing_book(guest):
    first = upload(guest)
    r = _post_file(guest, "attentive_mind.pdf", "application/pdf")
    assert r.status_code == 200 and r.json()["duplicate"] is True
    assert r.json()["book"]["id"] == first["id"]


def test_retry_rebuilds_idempotently(guest):
    book = upload(guest)
    with SessionLocal() as db:
        n_chunks = db.query(DocumentChunk).filter_by(book_id=uuid.UUID(book["id"])).count()
        b = db.get(Book, uuid.UUID(book["id"]))
        b.processing_status = "failed"
        db.commit()
    assert guest.post(f"/api/v1/books/{book['id']}/retry").status_code == 202
    with SessionLocal() as db:
        assert db.query(DocumentChunk).filter_by(book_id=uuid.UUID(book["id"])).count() == n_chunks
        assert db.get(Book, uuid.UUID(book["id"])).processing_status == "ready"


def test_delete_book_removes_file_and_derived_data(ready_book, guest):
    bid = ready_book["id"]
    guest.post(f"/api/v1/books/{bid}/summaries", json={"depth": "concise"})
    with SessionLocal() as db:
        key = db.get(Book, uuid.UUID(bid)).source_file.storage_key
    assert get_storage().exists(key)
    assert guest.delete(f"/api/v1/books/{bid}").json() == {"deleted": True}
    assert guest.get(f"/api/v1/books/{bid}").status_code == 404
    assert not get_storage().exists(key)
    with SessionLocal() as db:
        assert db.query(DocumentChunk).filter_by(book_id=uuid.UUID(bid)).count() == 0
        assert db.query(EvidenceReference).filter_by(book_id=uuid.UUID(bid)).count() == 0
        assert db.query(SourceFile).count() == 0


def test_guest_retention_cleanup_removes_expired_sessions_and_files():
    c = start_guest(make_client())
    book = upload(c)
    with SessionLocal() as db:
        key = db.get(Book, uuid.UUID(book["id"])).source_file.storage_key
        for g in db.query(GuestSession).all():
            g.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        result = run_retention_cleanup(db)
    assert result["guests_expired"] == 1 and result["books_removed"] == 1
    assert not get_storage().exists(key)
    assert c.get("/api/v1/books").status_code == 401  # expired guest cookie no longer authenticates


def test_library_pagination(guest):
    for name in ("attentive_mind.pdf", "backyard_compost.epub", "hindi_reading.epub"):
        upload(guest, name)
    page1 = guest.get("/api/v1/books?limit=2").json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = guest.get(f"/api/v1/books?limit=2&cursor={page1['next_cursor']}").json()
    assert len(page2["items"]) == 1 and page2["next_cursor"] is None
    ids = {b["id"] for b in page1["items"] + page2["items"]}
    assert len(ids) == 3


def test_search_within_book(ready_book, guest):
    items = guest.get(f"/api/v1/books/{ready_book['id']}/search?q=switching tax").json()["items"]
    assert items and "switching" in items[0]["snippet"].lower()
