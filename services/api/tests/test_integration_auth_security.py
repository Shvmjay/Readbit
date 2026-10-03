"""Integration: accounts, sessions, guest conversion, deletion, CSRF, and authorization isolation (Journey E)."""

import logging
import re

import pytest

from app.core.db import SessionLocal
from app.models.users import AuthSession, GuestSession, User
from tests.conftest import make_client, register, start_guest, upload


def test_register_login_logout_persistence():
    c = make_client()
    register(c, "a@example.com")
    book = upload(c)
    assert c.get("/api/v1/me").json()["user"]["email"] == "a@example.com"
    c.post("/api/v1/auth/logout")
    assert c.get("/api/v1/me").json()["authenticated"] is False
    assert c.get("/api/v1/books").status_code == 401
    r = c.post("/api/v1/auth/login", json={"email": "A@Example.com", "password": "correct-horse-42"})
    assert r.status_code == 200
    items = c.get("/api/v1/books").json()["items"]
    assert [b["id"] for b in items] == [book["id"]]


def test_passwords_hashed_and_tokens_never_stored_raw():
    c = make_client()
    register(c, "h@example.com", "another-pass-99")
    token = c.cookies.get("rb_session")
    with SessionLocal() as db:
        u = db.query(User).one()
        assert u.password_hash.startswith("$argon2id$") and "another-pass-99" not in u.password_hash
        s = db.query(AuthSession).one()
        assert s.token_hash != token and len(s.token_hash) == 64


@pytest.mark.parametrize(
    "email,password,status", [("bad", "long-enough-pass-1", 422), ("x@example.com", "short", 422)]
)
def test_registration_validation(email, password, status):
    c = make_client()
    r = c.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == status


def test_duplicate_registration_and_wrong_password():
    c = make_client()
    register(c, "dup@example.com")
    c2 = make_client()
    assert (
        c2.post(
            "/api/v1/auth/register", json={"email": "dup@example.com", "password": "correct-horse-42"}
        ).status_code
        == 409
    )
    r = c2.post("/api/v1/auth/login", json={"email": "dup@example.com", "password": "wrong-password-1"})
    r2 = c2.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"})
    assert r.status_code == r2.status_code == 401
    assert r.json()["error"]["message"] == r2.json()["error"]["message"]  # no account enumeration


def test_guest_books_migrate_to_new_account():
    c = start_guest(make_client())
    book = upload(c)
    c.put(f"/api/v1/books/{book['id']}/reading-state", json={"view": "summary"})
    r = c.post("/api/v1/auth/register", json={"email": "conv@example.com", "password": "correct-horse-42"})
    assert r.json()["migrated_guest_data"] is True
    assert [b["id"] for b in c.get("/api/v1/books").json()["items"]] == [book["id"]]
    assert c.get(f"/api/v1/books/{book['id']}").json()["reading_state"]["last_view"] == "summary"
    with SessionLocal() as db:
        assert db.query(GuestSession).one().converted_user_id is not None


def test_password_reset_flow(caplog):
    c = make_client()
    register(c, "reset@example.com")
    with caplog.at_level(logging.INFO, logger="readbit.mail"):
        r = c.post("/api/v1/auth/password-reset/request", json={"email": "reset@example.com"})
    assert r.status_code == 200
    unknown = c.post("/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert unknown.json() == r.json()
    body = next(rec.body for rec in caplog.records if hasattr(rec, "body"))
    token = re.search(r"token=(\S+)", body).group(1)
    assert (
        c.post(
            "/api/v1/auth/password-reset/confirm", json={"token": token, "password": "brand-new-pass-7"}
        ).status_code
        == 200
    )
    assert c.get("/api/v1/me").json()["authenticated"] is False  # all sessions revoked
    assert (
        c.post(
            "/api/v1/auth/password-reset/confirm", json={"token": token, "password": "brand-new-pass-8"}
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/auth/login", json={"email": "reset@example.com", "password": "brand-new-pass-7"}
        ).status_code
        == 200
    )


def test_account_deletion_removes_everything():
    c = make_client()
    register(c, "del@example.com")
    upload(c)
    assert c.request("DELETE", "/api/v1/me", json={"confirm": "NOPE"}).status_code == 422
    assert c.request("DELETE", "/api/v1/me", json={"confirm": "DELETE"}).json() == {"deleted": True}
    with SessionLocal() as db:
        assert db.query(User).count() == 0
    assert (
        c.post(
            "/api/v1/auth/login", json={"email": "del@example.com", "password": "correct-horse-42"}
        ).status_code
        == 401
    )


def test_csrf_header_required_for_mutations():
    c = make_client()
    c.headers.pop("X-Readbit-CSRF")
    r = c.post("/api/v1/auth/guest", json={"language": "en", "accepted_privacy": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    c.headers["X-Readbit-CSRF"] = "1"
    r = c.post(
        "/api/v1/auth/guest",
        json={"language": "en", "accepted_privacy": True},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_security_headers_and_cookie_flags():
    c = make_client()
    r = c.post("/api/v1/auth/guest", json={"language": "en", "accepted_privacy": True})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def _full_setup(owner):
    """Create a book with a summary, evidence, note, quiz session for the owner; return all resource ids."""
    book = upload(owner)
    bid = book["id"]
    ch = owner.get(f"/api/v1/books/{bid}/chapters").json()["items"][0]
    s = owner.post(
        f"/api/v1/books/{bid}/summaries", json={"chapter_id": ch["id"], "depth": "concise"}
    ).json()["summary"]
    s = owner.get(f"/api/v1/books/{bid}/summaries/{s['id']}").json()["summary"]
    eid = s["content"]["central_thesis"]["evidence_ids"][0]
    note = owner.post(
        f"/api/v1/books/{bid}/annotations",
        json={"annotation_type": "bookmark", "source_location": {"kind": "chapter", "chapter_id": ch["id"]}},
    ).json()["annotation"]
    view = owner.post(f"/api/v1/books/{bid}/quiz-sessions", json={"chapter_id": ch["id"]}).json()
    return {
        "book": bid,
        "chapter": ch["id"],
        "summary": s["id"],
        "evidence": eid,
        "annotation": note["id"],
        "session": view["session"]["id"],
        "question": view["question"]["id"],
    }


def _assert_isolated(attacker, ids):
    b = ids["book"]
    gets = [
        f"/api/v1/books/{b}",
        f"/api/v1/books/{b}/chapters",
        f"/api/v1/books/{b}/processing-status",
        f"/api/v1/books/{b}/summaries",
        f"/api/v1/books/{b}/summaries/{ids['summary']}",
        f"/api/v1/books/{b}/summaries/{ids['summary']}/export",
        f"/api/v1/books/{b}/evidence/{ids['evidence']}",
        f"/api/v1/books/{b}/chapters/{ids['chapter']}/passages",
        f"/api/v1/books/{b}/annotations",
        f"/api/v1/books/{b}/annotations/export",
        f"/api/v1/books/{b}/lessons",
        f"/api/v1/books/{b}/progress",
        f"/api/v1/books/{b}/mastery",
        f"/api/v1/quiz-sessions/{ids['session']}",
        f"/api/v1/books/{b}/search?q=attention",
        f"/api/v1/books/{b}/reading-state",
    ]
    for url in gets:
        r = attacker.get(url)
        assert r.status_code == 404, (url, r.status_code)
    posts = [
        (f"/api/v1/books/{b}/summaries", {"depth": "concise"}),
        (f"/api/v1/books/{b}/questions", {"question": "What?"}),
        (f"/api/v1/books/{b}/quiz-sessions", {}),
        (f"/api/v1/books/{b}/revision-sessions", None),
        (
            f"/api/v1/books/{b}/annotations",
            {
                "annotation_type": "bookmark",
                "source_location": {"kind": "chapter", "chapter_id": ids["chapter"]},
            },
        ),
        (
            f"/api/v1/quiz-sessions/{ids['session']}/answers",
            {"question_id": ids["question"], "selected_option_key": "A"},
        ),
        (f"/api/v1/books/{b}/retry", None),
        (f"/api/v1/books/{b}/evidence/{ids['evidence']}/translate", {"target_language": "hi"}),
    ]
    for url, body in posts:
        r = attacker.post(url, json=body)
        assert r.status_code == 404, (url, r.status_code)
    assert (
        attacker.patch(f"/api/v1/annotations/{ids['annotation']}", json={"note_text": "x"}).status_code == 404
    )
    assert attacker.delete(f"/api/v1/annotations/{ids['annotation']}").status_code == 404
    assert attacker.put(f"/api/v1/books/{b}/reading-state", json={"view": "summary"}).status_code == 404
    assert attacker.delete(f"/api/v1/books/{b}").status_code == 404
    assert attacker.get("/api/v1/books").json()["items"] == []


def test_cross_user_access_is_rejected_everywhere():
    a, b = make_client(), make_client()
    register(a, "alice@example.com")
    register(b, "bob@example.com")
    ids = _full_setup(a)
    _assert_isolated(b, ids)
    assert a.get(f"/api/v1/books/{ids['book']}").status_code == 200  # owner still has access


def test_guest_sessions_are_isolated_from_each_other_and_from_users():
    g1, g2 = start_guest(make_client()), start_guest(make_client())
    ids = _full_setup(g1)
    _assert_isolated(g2, ids)
    u = make_client()
    register(u, "carol@example.com")
    _assert_isolated(u, ids)


def test_anonymous_requests_rejected(client):
    for url in ("/api/v1/books", "/api/v1/me/dashboard", "/api/v1/users/me/achievements"):
        assert client.get(url).status_code == 401
