"""Upload malware scanning via ClamAV's clamd INSTREAM protocol (no extra dependencies).

Fails closed: when scanning is enabled and clamd cannot be reached, the upload is rejected as retryable rather than
stored unscanned.
"""

from __future__ import annotations

import socket
import struct

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

log = get_logger("readbit.scan")
CHUNK = 64 * 1024


def clamd_scan(data: bytes, host: str, port: int, timeout: float) -> str:
    """Return clamd's verdict line, e.g. 'stream: OK' or 'stream: Eicar-Signature FOUND'."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), CHUNK):
            part = data[i : i + CHUNK]
            sock.sendall(struct.pack("!L", len(part)) + part)
        sock.sendall(struct.pack("!L", 0))
        reply = b""
        while not reply.endswith(b"\0"):
            buf = sock.recv(4096)
            if not buf:
                break
            reply += buf
    return reply.rstrip(b"\0").decode("utf-8", "replace").strip()


def scan_upload(data: bytes) -> None:
    s = get_settings()
    if s.malware_scanner == "none":
        return
    try:
        verdict = clamd_scan(data, s.clamav_host, s.clamav_port, s.clamav_timeout_seconds)
    except OSError as exc:
        log.warning("malware scanner unreachable", extra={"error": type(exc).__name__})
        raise AppError(
            ErrorCode.SCANNER_UNAVAILABLE,
            "We couldn't safety-check your file right now. Nothing was stored; please try again shortly.",
            status_code=503,
        ) from exc
    if verdict.endswith("FOUND"):
        log.warning(
            "malware detected in upload", extra={"signature": verdict.removeprefix("stream:").strip()}
        )
        raise AppError(
            ErrorCode.MALWARE_DETECTED,
            "This file was flagged by our malware scanner and was not stored.",
            status_code=422,
        )
    if not verdict.endswith("OK"):
        log.warning("unexpected scanner reply", extra={"reply": verdict[:200]})
        raise AppError(
            ErrorCode.SCANNER_UNAVAILABLE,
            "We couldn't safety-check your file right now. Nothing was stored; please try again shortly.",
            status_code=503,
        )
