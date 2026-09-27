from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session, optional_actor
from app.core.ratelimit import enforce
from app.schemas.api import ClientEvent
from app.services.actors import CurrentActor
from app.services.analytics import CLIENT_EVENTS, track

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.post("/events", status_code=202, summary="Record an allowlisted, content-free client analytics event")
def client_event(body: ClientEvent, db: Session = Depends(db_session), actor: CurrentActor | None = Depends(optional_actor)) -> dict:
    if body.name not in CLIENT_EVENTS:
        return {"accepted": False}
    if actor is not None:
        enforce(actor.key, "events", limit=120)
    book_id = None
    if body.book_id and actor is not None:
        from app.models.books import Book

        book = db.get(Book, body.book_id)
        book_id = book.id if book is not None and ((actor.user and book.owner_user_id == actor.user_id) or (actor.guest_id and book.guest_session_id == actor.guest_id)) else None
    track(db, body.name, actor.key if actor else None, book_id, **body.properties)
    db.commit()
    return {"accepted": True}
