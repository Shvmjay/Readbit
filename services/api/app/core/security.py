"""Password hashing and opaque token helpers. No custom cryptography: argon2id + SHA-256 + secrets."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """Opaque, URL-safe, 256-bit random token. Only its hash is ever stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def pseudonymous_id(value: str) -> str:
    """Stable pseudonymous identifier for analytics (keyed hash, not reversible without SECRET_KEY)."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, ("analytics:" + value).encode(), hashlib.sha256).hexdigest()[:24]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
