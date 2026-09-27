"""Request/response models for the public API (documented in OpenAPI)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

Language = Literal["en", "hi"]
Depth = Literal["concise", "balanced", "comprehensive"]


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


class GuestStart(BaseModel):
    language: Language = "en"
    accepted_privacy: bool = Field(description="The visitor acknowledged the privacy and retention notice.")


class RegisterBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    display_name: str = Field(default="", max_length=120)
    language: Language = "en"


class LoginBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class ResetRequestBody(BaseModel):
    email: str = Field(max_length=320)


class ResetBody(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=200)


class PreferencesBody(BaseModel):
    preferred_language: Language | None = None
    content_language: Language | None = None
    theme_preference: Literal["light", "dark", "system"] | None = None
    display_name: str | None = Field(default=None, max_length=120)
    daily_goal_questions: int | None = Field(default=None, ge=1, le=200)


class DeleteAccountBody(BaseModel):
    confirm: Literal["DELETE"]


class SummaryRequest(BaseModel):
    chapter_id: uuid.UUID | None = None
    depth: Depth = "balanced"
    output_language: Language | None = None


class QuestionBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    chapter_id: uuid.UUID | None = None
    output_language: Language | None = None


class TranslateBody(BaseModel):
    target_language: Language


class AnnotationCreate(BaseModel):
    annotation_type: Literal["highlight", "bookmark", "note"]
    source_location: dict[str, Any]
    selected_text: str | None = Field(default=None, max_length=2000)
    note_text: str | None = Field(default=None, max_length=10000)
    color: str | None = None


class AnnotationUpdate(BaseModel):
    note_text: str | None = Field(default=None, max_length=10000)
    color: str | None = None


class ReadingStateBody(BaseModel):
    view: Literal["summary", "source", "overview"] | None = None
    chapter_id: uuid.UUID | None = None
    depth: Depth | None = None
    position: dict[str, Any] | None = None


class QuizSessionCreate(BaseModel):
    chapter_id: uuid.UUID | None = None


class AnswerBody(BaseModel):
    question_id: uuid.UUID
    selected_option_key: Literal["A", "B", "C", "D"]
    response_duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class ClientEvent(BaseModel):
    name: str = Field(max_length=64)
    book_id: uuid.UUID | None = None
    properties: dict[str, str | int | float | bool] = {}
