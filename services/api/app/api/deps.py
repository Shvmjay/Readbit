"""Request dependencies: database session, current actor (user or guest), and access guards."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, ErrorCode, unauthorized
from app.core.ratelimit import enforce
from app.services.actors import CurrentActor
from app.services.auth_service import resolve_guest, resolve_user

SESSION_COOKIE = "rb_session"
GUEST_COOKIE = "rb_guest"


def db_session() -> Iterator[Session]:
    yield from get_db()


def optional_actor(request: Request, db: Session = Depends(db_session)) -> CurrentActor | None:
    user, _ = resolve_user(db, request.cookies.get(SESSION_COOKIE))
    guest = resolve_guest(db, request.cookies.get(GUEST_COOKIE))
    if user is None and guest is None:
        return None
    return CurrentActor(user=user, guest=guest)


def require_actor(actor: CurrentActor | None = Depends(optional_actor)) -> CurrentActor:
    if actor is None:
        raise unauthorized()
    return actor


def require_user(actor: CurrentActor = Depends(require_actor)) -> CurrentActor:
    if actor.user is None:
        raise AppError(
            ErrorCode.UNAUTHORIZED, "Create an account or sign in to use this feature.", status_code=401
        )
    return actor


def ai_rate_limited(actor: CurrentActor = Depends(require_actor)) -> CurrentActor:
    enforce(actor.key, "ai")
    return actor


def upload_rate_limited(actor: CurrentActor = Depends(require_actor)) -> CurrentActor:
    enforce(actor.key, "upload", limit=10, window=600)
    return actor
