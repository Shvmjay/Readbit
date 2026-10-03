"""Error taxonomy. Every user-facing failure maps to a stable code and a safe message.

Messages never include stack traces, provider secrets or database details.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    UNSUPPORTED_FILE = "unsupported_file"
    FILE_TOO_LARGE = "file_too_large"
    CORRUPTED_DOCUMENT = "corrupted_document"
    PASSWORD_PROTECTED = "password_protected"  # noqa: S105 - error code, not a secret
    OCR_UNAVAILABLE = "ocr_unavailable"
    EXTRACTION_QUALITY_LOW = "extraction_quality_low"
    CHAPTER_DETECTION_UNCERTAIN = "chapter_detection_uncertain"
    PROCESSING_TIMEOUT = "processing_timeout"
    DOCUMENT_TOO_LONG = "document_too_long"
    DUPLICATE_UPLOAD = "duplicate_upload"
    MALWARE_DETECTED = "malware_detected"
    SCANNER_UNAVAILABLE = "scanner_unavailable"
    AI_PROVIDER_UNAVAILABLE = "ai_provider_unavailable"
    AI_OUTPUT_INVALID = "ai_output_invalid"
    AI_BUDGET_EXCEEDED = "ai_budget_exceeded"
    LANGUAGE_UNSUPPORTED = "language_unsupported"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    RATE_LIMITED = "rate_limited"
    STORAGE_FAILURE = "storage_failure"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    SESSION_EXPIRED = "session_expired"
    VALIDATION_ERROR = "validation_error"
    CONFLICT = "conflict"
    CSRF_FAILED = "csrf_failed"
    NOT_READY = "not_ready"
    INTERNAL = "internal_error"


# Whether a client may reasonably retry the same request later.
RETRYABLE = {
    ErrorCode.AI_PROVIDER_UNAVAILABLE,
    ErrorCode.PROCESSING_TIMEOUT,
    ErrorCode.RATE_LIMITED,
    ErrorCode.STORAGE_FAILURE,
    ErrorCode.SCANNER_UNAVAILABLE,
    ErrorCode.AI_OUTPUT_INVALID,
    ErrorCode.INTERNAL,
}


class AppError(Exception):
    status_code = 400

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": str(self.code),
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            }
        }


def not_found(what: str = "Resource") -> AppError:
    # Deliberately identical for "missing" and "belongs to someone else" to avoid IDOR probing.
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found.", status_code=404)


def unauthorized(message: str = "Please sign in or start a guest session.") -> AppError:
    return AppError(ErrorCode.UNAUTHORIZED, message, status_code=401)
