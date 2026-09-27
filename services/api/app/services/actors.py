"""The acting identity for a request: a registered user or a guest session (never both)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_

from app.ai.router import Actor
from app.models.users import GuestSession, User


@dataclass
class CurrentActor:
    user: User | None = None
    guest: GuestSession | None = None

    @property
    def is_guest(self) -> bool:
        return self.user is None and self.guest is not None

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user else None

    @property
    def guest_id(self) -> uuid.UUID | None:
        return self.guest.id if self.user is None and self.guest else None

    @property
    def key(self) -> str:
        if self.user:
            return f"u:{self.user.id}"
        assert self.guest is not None
        return f"g:{self.guest.id}"

    @property
    def language(self) -> str:
        if self.user:
            return self.user.preferred_language
        return self.guest.preferred_language if self.guest else "en"

    def owner_fields(self) -> dict:
        """Column values that assign ownership of a new row to this actor."""
        return {"owner_user_id": self.user_id, "guest_session_id": self.guest_id}

    def owns(self, model) -> object:
        """SQL clause restricting a query to rows owned by this actor."""
        if self.user:
            return model.owner_user_id == self.user.id
        return and_(model.guest_session_id == self.guest_id, model.owner_user_id.is_(None))

    def ai_actor(self) -> Actor:
        return Actor(user_id=self.user_id, guest_session_id=self.guest_id)
