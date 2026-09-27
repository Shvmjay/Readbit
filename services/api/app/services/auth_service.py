"""Accounts, sessions and guest sessions (standards-based: argon2id password hashes, opaque hashed tokens)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import hash_password, hash_token, needs_rehash, new_token, verify_password
from app.models.books import Book
from app.models.content import Annotation, ReadingState
from app.models.learning import QuizSession, TopicMastery, UserAchievement
from app.models.ops import AIExecution
from app.models.users import AuthSession, GuestSession, PasswordResetToken, User
from app.services.analytics import track

log = get_logger("readbit.auth")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
SUPPORTED_LANGUAGES = ("en", "hi")
_DUMMY_HASH = hash_password("readbit-timing-equaliser")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Please enter a valid email address.", status_code=422)
    return email


def validate_password(password: str) -> None:
    if len(password) < 10 or len(password) > 200:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "Passwords must be 10–200 characters long.", status_code=422
        )
    if password.lower() == password and password.isalpha():
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "Use a mix of letters and numbers or symbols.", status_code=422
        )


# ---------------------------------------------------------------- guest sessions
def start_guest(db: Session, language: str = "en", consent: dict | None = None) -> tuple[GuestSession, str]:
    token = new_token()
    guest = GuestSession(
        secure_session_token_hash=hash_token(token),
        expires_at=_now() + timedelta(hours=get_settings().guest_retention_hours),
        consent_state=consent or {},
        preferred_language=language if language in SUPPORTED_LANGUAGES else "en",
    )
    db.add(guest)
    db.flush()
    track(db, "guest_session_started", f"g:{guest.id}")
    db.commit()
    return guest, token


def resolve_guest(db: Session, token: str | None) -> GuestSession | None:
    if not token:
        return None
    guest = db.scalar(select(GuestSession).where(GuestSession.secure_session_token_hash == hash_token(token)))
    if guest is None or guest.converted_user_id is not None or _aware(guest.expires_at) <= _now():
        return None
    if (_now() - _aware(guest.last_active_at)).total_seconds() > 300:
        guest.last_active_at = _now()
        db.commit()
    return guest


# ---------------------------------------------------------------- user sessions
def create_session(db: Session, user: User) -> str:
    token = new_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=_now() + timedelta(hours=get_settings().session_ttl_hours),
        )
    )
    db.commit()
    return token


def resolve_user(db: Session, token: str | None) -> tuple[User | None, AuthSession | None]:
    if not token:
        return None, None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if sess is None or sess.revoked_at is not None or _aware(sess.expires_at) <= _now():
        return None, None
    user = db.get(User, sess.user_id)
    if user is None or user.account_status != "active" or user.deleted_at is not None:
        return None, None
    # Sliding renewal: extend active sessions at most once per hour.
    if (_now() - _aware(sess.last_seen_at)).total_seconds() > 3600:
        sess.last_seen_at = _now()
        sess.expires_at = _now() + timedelta(hours=get_settings().session_ttl_hours)
        db.commit()
    return user, sess


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    db.execute(
        update(AuthSession).where(AuthSession.token_hash == hash_token(token)).values(revoked_at=_now())
    )
    db.commit()


def register(
    db: Session, email: str, password: str, display_name: str, language: str, guest: GuestSession | None
) -> User:
    email = normalize_email(email)
    validate_password(password)
    if db.scalar(select(User).where(User.email == email)):
        raise AppError(
            ErrorCode.CONFLICT, "An account with this email already exists. Try signing in.", status_code=409
        )
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=email,
        display_name=display_name.strip()[:120] or email.split("@")[0],
        authentication_subject=f"local:{user_id}",
        password_hash=hash_password(password),
        preferred_language=language if language in SUPPORTED_LANGUAGES else "en",
    )
    db.add(user)
    db.flush()
    if guest is not None:
        migrate_guest(db, guest, user)
    track(db, "account_created", f"u:{user.id}")
    db.commit()
    return user


def login(db: Session, email: str, password: str, guest: GuestSession | None) -> User:
    try:
        email = normalize_email(email)
    except AppError:
        email = ""
    user = db.scalar(select(User).where(User.email == email)) if email else None
    if user is None or not user.password_hash or user.deleted_at is not None:
        verify_password(password, _DUMMY_HASH)  # equalise timing to avoid account enumeration
        raise AppError(ErrorCode.UNAUTHORIZED, "Email or password is incorrect.", status_code=401)
    if not verify_password(password, user.password_hash):
        raise AppError(ErrorCode.UNAUTHORIZED, "Email or password is incorrect.", status_code=401)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    if guest is not None:
        migrate_guest(db, guest, user)
    db.commit()
    return user


def migrate_guest(db: Session, guest: GuestSession, user: User) -> None:
    """Move a guest's books, notes and learning history into the account (guest → registered conversion)."""
    new_key = f"u:{user.id}"
    for model in (Book, Annotation, QuizSession):
        db.execute(
            update(model)
            .where(model.guest_session_id == guest.id)
            .values(owner_user_id=user.id, guest_session_id=None)
        )
    for model in (ReadingState, TopicMastery, UserAchievement):
        # Skip rows that would collide with the user's existing rows (keep the account's own record).
        for row in db.scalars(select(model).where(model.guest_session_id == guest.id)):
            clash_stmt = select(model).where(model.actor_key == new_key)
            if model is ReadingState:
                clash_stmt = clash_stmt.where(ReadingState.book_id == row.book_id)
            elif model is TopicMastery:
                clash_stmt = clash_stmt.where(TopicMastery.topic_id == row.topic_id)
            else:
                clash_stmt = clash_stmt.where(
                    UserAchievement.achievement_id == row.achievement_id,
                    UserAchievement.scope_key == row.scope_key,
                )
            if db.scalar(clash_stmt) is not None:
                db.delete(row)
                continue
            row.owner_user_id, row.guest_session_id, row.actor_key = user.id, None, new_key
    db.execute(update(AIExecution).where(AIExecution.guest_session_id == guest.id).values(user_id=user.id))
    guest.converted_user_id = user.id
    db.flush()
    log.info("guest converted", extra={"user_id": str(user.id)})


def request_password_reset(db: Session, email: str) -> str | None:
    """Creates a reset token and 'delivers' it. Always behaves the same whether or not the email exists."""
    try:
        email = normalize_email(email)
    except AppError:
        return None
    user = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None:
        return None
    token = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=_now() + timedelta(minutes=get_settings().password_reset_ttl_minutes),
        )
    )
    db.commit()
    if get_settings().email_delivery == "log" and not get_settings().is_production:
        # Development delivery: the link is logged locally. Production must configure a real mail adapter.
        log.info(
            "password reset link",
            extra={"reset_url": f"{get_settings().app_url}/reset-password?token={token}"},
        )
    return token


def reset_password(db: Session, token: str, new_password: str) -> None:
    validate_password(new_password)
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    if row is None or row.used_at is not None or _aware(row.expires_at) <= _now():
        raise AppError(
            ErrorCode.SESSION_EXPIRED, "This reset link is invalid or has expired.", status_code=400
        )
    user = db.get(User, row.user_id)
    assert user is not None
    user.password_hash = hash_password(new_password)
    row.used_at = _now()
    # Sign out everywhere after a password change.
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()
