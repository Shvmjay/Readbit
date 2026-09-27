"""Job dispatch abstraction.

JOB_BACKEND=celery   → Redis-backed Celery workers (production).
JOB_BACKEND=thread   → bounded in-process thread pool (local development without Redis).
JOB_BACKEND=inline   → run synchronously in the calling thread (tests).

Handlers are idempotent and load all state from the database by id, so any backend can retry them safely.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("readbit.jobs")

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()

QUEUE_FOR = {
    "ingest": "documents",
    "summary": "summaries",
    "question_bank": "questions",
    "cleanup": "maintenance",
}


def _handlers() -> dict[str, Callable[[uuid.UUID], None]]:
    from app.services.ingestion import run_ingest_job
    from app.services.quiz_service import run_question_bank_job
    from app.services.summary_service import run_summary_job

    return {"ingest": run_ingest_job, "summary": run_summary_job, "question_bank": run_question_bank_job}


def run_job(job_type: str, job_id: uuid.UUID) -> None:
    handler = _handlers()[job_type]
    try:
        handler(job_id)
    except Exception:  # noqa: BLE001 - handlers record their own failures; never crash the worker loop
        log.exception("job crashed", extra={"job_type": job_type, "job_id": str(job_id)})


def enqueue(job_type: str, job_id: uuid.UUID) -> None:
    backend = get_settings().job_backend
    if backend == "inline":
        run_job(job_type, job_id)
        return
    if backend == "celery":
        from app.workers.celery_app import run_job_task

        run_job_task.apply_async(args=[job_type, str(job_id)], queue=QUEUE_FOR.get(job_type, "default"))
        return
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=max(1, get_settings().worker_concurrency), thread_name_prefix="rb-job")
    _executor.submit(run_job, job_type, job_id)


def wait_for_idle(timeout: float = 30.0) -> None:
    """Test helper for the thread backend: block until queued jobs finish."""
    global _executor
    with _lock:
        ex, _executor = _executor, None
    if ex is not None:
        ex.shutdown(wait=True)
