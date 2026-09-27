"""Test configuration: isolated database + storage per test, inline jobs, offline AI engine (no paid calls).

Set TEST_DATABASE_URL=postgresql+psycopg://... to run the same suite against PostgreSQL + pgvector.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="readbit-tests-"))
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP}/test.db"),
        "JOB_BACKEND": "inline",
        "STORAGE_PROVIDER": "local",
        "STORAGE_LOCAL_PATH": str(_TMP / "storage"),
        "DEFAULT_LLM_PROVIDER": "extractive",
        "LOG_LEVEL": "WARNING",
        "USER_RATE_LIMIT": "1000",
        "SECRET_KEY": "test-secret-key-0123456789abcdef0123456789",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, configure_engine, get_engine  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "evals" / "fixtures"


def fixture_bytes(name: str) -> bytes:
    path = FIXTURES / name
    if not path.exists():
        import subprocess
        import sys

        subprocess.run([sys.executable, str(FIXTURES.parents[1] / "scripts" / "generate_fixtures.py")], check=True)
    return path.read_bytes()


@pytest.fixture(autouse=True)
def _fresh_db():
    import app.models  # noqa: F401
    from app.ai.router import _provider_overrides
    from app.core.ratelimit import reset_rate_limits

    get_settings.cache_clear()
    configure_engine()
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_rate_limits()
    _provider_overrides.clear()
    yield
    _provider_overrides.clear()
    shutil.rmtree(_TMP / "storage", ignore_errors=True)


def make_client() -> TestClient:
    from app.main import create_app

    client = TestClient(create_app(), base_url="http://testserver")
    client.headers.update({"X-Readbit-CSRF": "1"})
    client.__enter__()  # run lifespan (seed achievements)
    return client


@pytest.fixture
def client() -> TestClient:
    return make_client()


def start_guest(client: TestClient) -> TestClient:
    r = client.post("/api/v1/auth/guest", json={"language": "en", "accepted_privacy": True})
    assert r.status_code == 200, r.text
    return client


def register(client: TestClient, email: str = "reader@example.com", password: str = "correct-horse-42") -> dict:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "display_name": "Reader"})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client: TestClient, name: str = "attentive_mind.pdf", mime: str | None = None) -> dict:
    data = fixture_bytes(name)
    mime = mime or ("application/pdf" if name.endswith(".pdf") else "application/epub+zip")
    r = client.post("/api/v1/books/upload", files={"file": (name, data, mime)})
    assert r.status_code in (200, 202), r.text
    return r.json()["book"]


@pytest.fixture
def guest(client):
    return start_guest(client)


@pytest.fixture
def ready_book(guest):
    book = upload(guest)
    r = guest.get(f"/api/v1/books/{book['id']}")
    assert r.json()["book"]["processing_status"] == "ready", r.json()
    return r.json()["book"]
