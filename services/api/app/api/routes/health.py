from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.prompts import all_prompt_ids
from app.ai.router import ModelRouter
from app.api.deps import db_session
from app.core.config import get_settings
from app.storage.base import get_storage

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe (database, storage, prompts)")
def ready(db: Session = Depends(db_session)):
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "unavailable"
    try:
        get_storage().exists("healthcheck/probe.pdf")
        checks["storage"] = "ok"
    except Exception:  # noqa: BLE001
        checks["storage"] = "unavailable"
    try:
        checks["prompts"] = f"{len(all_prompt_ids())} loaded"
    except Exception:  # noqa: BLE001
        checks["prompts"] = "missing"
    ok = checks["database"] == "ok" and checks["storage"] == "ok" and checks["prompts"] != "missing"
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@router.get("/api/v1/meta", tags=["meta"], summary="Public capabilities: languages, AI engine mode and limits")
def meta(db: Session = Depends(db_session)) -> dict:
    s = get_settings()
    r = ModelRouter(db)
    return {
        "interface_languages": ["en", "hi"],
        "ai_engine": {
            "provider": r.provider_name,
            "mode": "extractive" if r.is_offline else "generative",
            "can_translate": not r.is_offline,
            "question_types": ["recall", "comprehension"] if r.is_offline else ["recall", "comprehension", "application", "inference"],
        },
        "limits": {
            "max_upload_size_mb": s.max_upload_size_mb,
            "max_document_pages": s.max_document_pages,
            "guest_retention_hours": s.guest_retention_hours,
            "lesson_size": s.lesson_size,
        },
        "ocr_enabled": s.ocr_provider != "none",
    }
