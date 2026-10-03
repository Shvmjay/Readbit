"""SMTP mail adapter, production mail validation, and ClamAV upload scanning (fake clamd speaking INSTREAM)."""

import socket
import struct
import threading

import pytest

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.mail import MailError, send_password_reset
from app.document_processing.scanning import scan_upload
from tests.conftest import make_client, register, start_guest

EICAR_MARKER = b"EICAR-TEST"


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        if FakeSMTP.fail:
            import smtplib

            raise smtplib.SMTPServerDisconnected("down")
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setenv("EMAIL_DELIVERY", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM", "Readbit <no-reply@readbit.example>")
    monkeypatch.setenv("SMTP_USERNAME", "apikey")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    get_settings.cache_clear()
    yield FakeSMTP
    get_settings.cache_clear()


def test_reset_email_sent_over_smtp_in_users_language(smtp):
    c = make_client()
    r = c.post(
        "/api/v1/auth/register",
        json={"email": "hi@example.com", "password": "correct-horse-42", "language": "hi"},
    )
    assert r.status_code == 201
    assert c.post("/api/v1/auth/password-reset/request", json={"email": "hi@example.com"}).status_code == 200
    assert len(smtp.sent) == 1
    msg = smtp.sent[0]
    assert msg["To"] == "hi@example.com" and "Readbit" in msg["Subject"] and "पासवर्ड" in msg["Subject"]
    assert "/reset-password?token=" in msg.get_content()
    # unknown accounts: same response, no email
    r2 = c.post("/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert r2.status_code == 200 and len(smtp.sent) == 1


def test_smtp_failure_does_not_leak_through_the_api(smtp):
    c = make_client()
    register(c, "fail@example.com")
    smtp.fail = True
    r = c.post("/api/v1/auth/password-reset/request", json={"email": "fail@example.com"})
    assert r.status_code == 200 and r.json()["ok"] is True
    with pytest.raises(MailError):
        send_password_reset("fail@example.com", "http://x/reset", "en")


def test_production_rejects_log_delivery_and_incomplete_smtp():
    base = dict(
        app_env="production",
        secret_key="x" * 40,
        database_url="postgresql+psycopg://u@h/db",
        job_backend="celery",
        storage_provider="s3",
    )
    with pytest.raises(ValueError, match="EMAIL_DELIVERY"):
        Settings(**base, email_delivery="log")
    with pytest.raises(ValueError, match="SMTP_HOST"):
        Settings(**base, email_delivery="smtp")
    Settings(**base, email_delivery="smtp", smtp_host="smtp.example.com", smtp_from="a@b.c")


# ------------------------------------------------------------------ ClamAV
def _fake_clamd(reply_for):
    """Minimal clamd: reads zINSTREAM + length-prefixed chunks, answers based on the content."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                f = conn.makefile("rb")
                assert f.read(10) == b"zINSTREAM\0"
                data = b""
                while True:
                    (n,) = struct.unpack("!L", f.read(4))
                    if n == 0:
                        break
                    data += f.read(n)
                conn.sendall(reply_for(data) + b"\0")

    threading.Thread(target=serve, daemon=True).start()
    return srv


@pytest.fixture
def clamd(monkeypatch):
    srv = _fake_clamd(lambda d: b"stream: Eicar-Test-Signature FOUND" if EICAR_MARKER in d else b"stream: OK")
    monkeypatch.setenv("MALWARE_SCANNER", "clamav")
    monkeypatch.setenv("CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMAV_PORT", str(srv.getsockname()[1]))
    get_settings.cache_clear()
    yield srv
    srv.close()
    get_settings.cache_clear()


def test_scanner_passes_clean_and_blocks_infected(clamd):
    scan_upload(b"%PDF-1.7 clean" * 10_000)  # multi-chunk stream
    with pytest.raises(AppError) as exc:
        scan_upload(b"%PDF-1.7 " + EICAR_MARKER)
    assert exc.value.code == ErrorCode.MALWARE_DETECTED


def test_infected_upload_rejected_and_not_stored(clamd, tmp_path):
    c = start_guest(make_client())
    r = c.post(
        "/api/v1/books/upload", files={"file": ("bad.pdf", b"%PDF-1.7\n" + EICAR_MARKER, "application/pdf")}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "malware_detected"
    assert c.get("/api/v1/books").json()["items"] == []


def test_scanner_unreachable_fails_closed(monkeypatch):
    monkeypatch.setenv("MALWARE_SCANNER", "clamav")
    monkeypatch.setenv("CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMAV_PORT", "1")  # nothing listens here
    get_settings.cache_clear()
    with pytest.raises(AppError) as exc:
        scan_upload(b"%PDF-1.7")
    assert exc.value.code == ErrorCode.SCANNER_UNAVAILABLE and exc.value.retryable
    get_settings.cache_clear()
