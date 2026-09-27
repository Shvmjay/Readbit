"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import annotations, auth, books, events, health, me, quiz, summaries
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, get_engine
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging, get_logger, request_id_var

log = get_logger("readbit.api")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-readbit-csrf"


def init_database() -> None:
    import app.models  # noqa: F401 - register tables
    from app.services.learning_service import seed_achievements

    settings = get_settings()
    if settings.is_sqlite and settings.app_env != "production":
        Base.metadata.create_all(get_engine())
    with SessionLocal() as db:
        seed_achievements(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    yield


def _error(code: ErrorCode, message: str, status: int, details: dict | None = None) -> JSONResponse:
    return JSONResponse(AppError(code, message, status_code=status, details=details).to_dict(), status_code=status)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Readbit API",
        version="0.1.0",
        description="Source-grounded book summarization, book Q&A and adaptive quizzes. All book-derived content "
        "comes only from the user's uploaded document.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Readbit-CSRF", "X-Request-ID"],
    )

    allowed_origins = {o.rstrip("/") for o in settings.cors_origin_list + [settings.app_url, settings.api_url]}

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid[:64])
        started = time.monotonic()
        try:
            if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
                # CSRF defence for cookie-authenticated JSON APIs: a custom header (not settable cross-site without
                # CORS approval) plus an Origin allowlist when the browser sends one.
                if request.headers.get(CSRF_HEADER) != "1":
                    return _error(ErrorCode.CSRF_FAILED, "Missing CSRF header.", 403)
                origin = request.headers.get("origin")
                if origin and origin.rstrip("/") not in allowed_origins:
                    host = urlparse(origin).netloc
                    if host != request.headers.get("host"):
                        return _error(ErrorCode.CSRF_FAILED, "Cross-origin request rejected.", 403)
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid[:64]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            log.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                                       "ms": int((time.monotonic() - started) * 1000)})
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(exc.to_dict(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")} for e in exc.errors()]
        return _error(ErrorCode.VALIDATION_ERROR, "Some fields are invalid.", 422, {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL
        return _error(code, "Not found." if exc.status_code == 404 else str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return _error(ErrorCode.INTERNAL, "Something went wrong on our side. Your data is safe; please retry.", 500)

    for r in (health.router, auth.router, me.router, books.router, summaries.router, annotations.router, quiz.router, events.router):
        app.include_router(r)
    return app


app = create_app()
