from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_actor
from app.schemas.api import AnnotationCreate, AnnotationUpdate
from app.services import annotation_service as ann
from app.services import book_service as bs
from app.services.actors import CurrentActor

router = APIRouter(prefix="/api/v1", tags=["annotations"])


@router.get("/books/{book_id}/annotations", summary="My highlights, bookmarks and notes for a book")
def list_annotations(
    book_id: uuid.UUID,
    type: Literal["highlight", "bookmark", "note"] | None = None,  # noqa: A002
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_actor),
) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    return {"items": [ann.serialize_annotation(a) for a in ann.list_annotations(db, actor, book, type)]}


@router.post("/books/{book_id}/annotations", status_code=201, summary="Create a highlight, bookmark or note")
def create_annotation(
    book_id: uuid.UUID,
    body: AnnotationCreate,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_actor),
) -> dict:
    book = bs.get_owned_book(db, actor, book_id)
    return {"annotation": ann.serialize_annotation(ann.create_annotation(db, actor, book, body.model_dump()))}


@router.patch("/annotations/{annotation_id}", summary="Edit a note or highlight colour")
def update_annotation(
    annotation_id: uuid.UUID,
    body: AnnotationUpdate,
    db: Session = Depends(db_session),
    actor: CurrentActor = Depends(require_actor),
) -> dict:
    a = ann.get_owned_annotation(db, actor, annotation_id)
    return {
        "annotation": ann.serialize_annotation(
            ann.update_annotation(db, a, body.model_dump(exclude_unset=True))
        )
    }


@router.delete("/annotations/{annotation_id}", summary="Delete an annotation")
def delete_annotation(
    annotation_id: uuid.UUID, db: Session = Depends(db_session), actor: CurrentActor = Depends(require_actor)
) -> dict:
    a = ann.get_owned_annotation(db, actor, annotation_id)
    db.delete(a)
    db.commit()
    return {"deleted": True}
