from __future__ import annotations

from fastapi import Response

from app.api.deps import GUEST_COOKIE, SESSION_COOKIE
from app.core.config import get_settings


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name, value, max_age=max_age, httponly=True, secure=get_settings().is_production, samesite="lax", path="/"
    )


def set_session_cookie(response: Response, token: str) -> None:
    set_cookie(response, SESSION_COOKIE, token, get_settings().session_ttl_hours * 3600)


def set_guest_cookie(response: Response, token: str) -> None:
    set_cookie(response, GUEST_COOKIE, token, get_settings().guest_retention_hours * 3600)


def clear_auth_cookies(response: Response, *, guest: bool = False) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    if guest:
        response.delete_cookie(GUEST_COOKIE, path="/")
