from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.cookies import clear_auth_cookies, set_guest_cookie, set_session_cookie
from app.api.deps import GUEST_COOKIE, SESSION_COOKIE, db_session, optional_actor
from app.api.serializers import serialize_user
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.ratelimit import enforce
from app.schemas.api import GuestStart, LoginBody, RegisterBody, ResetBody, ResetRequestBody
from app.services import auth_service
from app.services.actors import CurrentActor

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


@router.post("/guest", summary="Start a temporary guest session")
def start_guest(
    body: GuestStart,
    response: Response,
    request: Request,
    db: Session = Depends(db_session),
    actor: CurrentActor | None = Depends(optional_actor),
) -> dict:
    if not body.accepted_privacy:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "Please acknowledge the privacy notice to continue.", status_code=422
        )
    if actor is not None and actor.guest is not None and actor.user is None:
        return {"guest": True, "expires_at": actor.guest.expires_at.isoformat(), "resumed": True}
    enforce(_client_key(request), "guest", limit=20, window=3600)
    guest, token = auth_service.start_guest(db, body.language, {"privacy_ack": True})
    set_guest_cookie(response, token)
    return {"guest": True, "expires_at": guest.expires_at.isoformat(), "resumed": False}


@router.post("/register", status_code=201, summary="Create an account (moves any guest books into it)")
def register(
    body: RegisterBody,
    response: Response,
    request: Request,
    db: Session = Depends(db_session),
    actor: CurrentActor | None = Depends(optional_actor),
) -> dict:
    enforce(_client_key(request), "register", limit=10, window=3600)
    guest = actor.guest if actor and actor.user is None else None
    user = auth_service.register(db, body.email, body.password, body.display_name, body.language, guest)
    set_session_cookie(response, auth_service.create_session(db, user))
    if guest is not None:
        response.delete_cookie(GUEST_COOKIE, path="/")
    return {"user": serialize_user(user), "migrated_guest_data": guest is not None}


@router.post("/login", summary="Sign in")
def login(
    body: LoginBody,
    response: Response,
    request: Request,
    db: Session = Depends(db_session),
    actor: CurrentActor | None = Depends(optional_actor),
) -> dict:
    enforce(_client_key(request) + ":" + body.email.lower(), "login", limit=10, window=900)
    guest = actor.guest if actor and actor.user is None else None
    user = auth_service.login(db, body.email, body.password, guest)
    set_session_cookie(response, auth_service.create_session(db, user))
    if guest is not None:
        response.delete_cookie(GUEST_COOKIE, path="/")
    return {"user": serialize_user(user), "migrated_guest_data": guest is not None}


@router.post("/logout", summary="Sign out of this browser")
def logout(request: Request, response: Response, db: Session = Depends(db_session)) -> dict:
    auth_service.revoke_session(db, request.cookies.get(SESSION_COOKIE))
    clear_auth_cookies(response, guest=True)
    return {"ok": True}


@router.post("/password-reset/request", summary="Request a password reset link")
def request_reset(body: ResetRequestBody, request: Request, db: Session = Depends(db_session)) -> dict:
    enforce(_client_key(request), "reset", limit=5, window=3600)
    auth_service.request_password_reset(db, body.email)
    # Same response whether or not the account exists (no account enumeration).
    return {"ok": True, "message": "If an account exists for this email, a reset link has been sent."}


@router.post("/password-reset/confirm", summary="Set a new password with a reset token")
def confirm_reset(body: ResetBody, response: Response, db: Session = Depends(db_session)) -> dict:
    auth_service.reset_password(db, body.token, body.password)
    clear_auth_cookies(response)
    return {"ok": True}
