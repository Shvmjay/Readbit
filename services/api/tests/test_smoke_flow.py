from tests.conftest import upload


def test_guest_upload_to_summary_and_quiz(guest):
    book = upload(guest)
    b = guest.get(f"/api/v1/books/{book['id']}").json()["book"]
    assert b["processing_status"] == "ready"
    assert b["title"] == "The Attentive Mind"
    assert b["author"] == "Mira Solen"
    chapters = guest.get(f"/api/v1/books/{book['id']}/chapters").json()["items"]
    assert [c["title"] for c in chapters][0].startswith("Chapter 1")
    assert len(chapters) == 4
    r = guest.post(f"/api/v1/books/{book['id']}/summaries", json={"chapter_id": chapters[0]["id"], "depth": "balanced"})
    assert r.status_code in (200, 202), r.text
    sid = r.json()["summary"]["id"]
    s = guest.get(f"/api/v1/books/{book['id']}/summaries/{sid}").json()["summary"]
    assert s["status"] == "ready", s
    assert s["content"]["central_thesis"]["text"]
    r = guest.post(f"/api/v1/books/{book['id']}/quiz-sessions", json={"chapter_id": chapters[0]["id"]})
    assert r.status_code == 201, r.text
    view = r.json()
    assert view["session"]["status"] == "active", view
    q = view["question"]
    assert len(q["options"]) == 4
    assert "correct_option_key" not in q
