"""Validated book processing lifecycle.

UPLOADED → VALIDATING → EXTRACTING → STRUCTURING → CHUNKING → INDEXING → READY
Any stage → FAILED; FAILED → UPLOADED (retry). Learning material is tracked separately on `learning_status`:
not_started → generating_questions → validating_questions → learning_ready | learning_failed.
"""

from __future__ import annotations

from app.core.errors import AppError, ErrorCode

PIPELINE = ["uploaded", "validating", "extracting", "structuring", "chunking", "indexing", "ready"]
TRANSITIONS: dict[str, set[str]] = {
    "uploaded": {"validating", "failed"},
    "validating": {"extracting", "failed"},
    "extracting": {"structuring", "failed"},
    "structuring": {"chunking", "failed"},
    "chunking": {"indexing", "failed"},
    "indexing": {"ready", "failed"},
    "ready": set(),
    "failed": {"uploaded"},
}
PROGRESS = {"uploaded": 5, "validating": 10, "extracting": 30, "structuring": 55, "chunking": 70, "indexing": 85, "ready": 100, "failed": 0}

LEARNING_TRANSITIONS: dict[str, set[str]] = {
    "not_started": {"generating_questions"},
    "generating_questions": {"validating_questions", "learning_failed"},
    "validating_questions": {"learning_ready", "learning_failed"},
    "learning_ready": {"generating_questions"},
    "learning_failed": {"generating_questions"},
}


def transition(book, new_status: str) -> None:
    current = book.processing_status
    if new_status == current:
        return
    if new_status not in TRANSITIONS.get(current, set()):
        raise AppError(ErrorCode.CONFLICT, f"Invalid processing transition {current} → {new_status}.", status_code=409)
    book.processing_status = new_status


def learning_transition(book, new_status: str) -> None:
    current = book.learning_status
    if new_status == current:
        return
    if new_status not in LEARNING_TRANSITIONS.get(current, set()):
        raise AppError(ErrorCode.CONFLICT, f"Invalid learning transition {current} → {new_status}.", status_code=409)
    book.learning_status = new_status
