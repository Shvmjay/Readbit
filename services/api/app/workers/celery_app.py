"""Celery application. Start workers with:

    celery -A app.workers.celery_app worker -Q documents,summaries,questions,maintenance --concurrency 2
    celery -A app.workers.celery_app beat   # scheduled retention cleanup
"""

from __future__ import annotations

import uuid

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery = Celery("readbit", broker=settings.redis_url, backend=None)
celery.conf.update(
    task_acks_late=True,  # redeliver if a worker dies mid-task (handlers are idempotent)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # bounded concurrency / backpressure for heavy documents
    task_time_limit=settings.max_processing_duration + 60,
    task_soft_time_limit=settings.max_processing_duration,
    task_default_queue="default",
    broker_connection_retry_on_startup=True,
    beat_schedule={"retention-cleanup": {"task": "readbit.cleanup", "schedule": 3600.0}},
)


@celery.task(name="readbit.run_job", bind=True, max_retries=0)
def run_job_task(self, job_type: str, job_id: str) -> None:
    from app.workers.dispatch import run_job

    run_job(job_type, uuid.UUID(job_id))


@celery.task(name="readbit.cleanup")
def cleanup_task() -> dict:
    from app.core.db import SessionLocal
    from app.services.retention import run_retention_cleanup

    with SessionLocal() as db:
        return run_retention_cleanup(db)
