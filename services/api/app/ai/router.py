"""Task-specific model router.

Responsibilities: choose provider+model per task, render the versioned prompt, enforce language support and the
daily AI budget, call the provider with timeouts and bounded retries (exponential backoff), validate the output
against the task's JSON Schema, escalate to a more capable model when output is invalid, and record every call
in `ai_executions` (tokens, cost, latency — never prompts or book text).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jsonschema
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.pricing import estimate_cost
from app.ai.prompts import load_prompt
from app.ai.providers.base import GenerationRequest, GenerationResult, LLMProvider, ProviderError
from app.ai.providers.extractive import ExtractiveProvider
from app.ai.schemas import SCHEMAS
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.models.ops import AIExecution

log = get_logger("readbit.ai")

TASK_MODEL_SETTING = {
    "summary_generator": "summary_model",
    "summary_passage_notes": "summary_model",
    "book_summary_aggregator": "summary_model",
    "chapter_detector": "summary_model",
    "document_extraction_repair": "summary_model",
    "book_qa": "qa_model",
    "quiz_question_generator": "quiz_model",
    "answer_explainer": "quiz_model",
    "quiz_question_validator": "validation_model",
    "source_faithfulness_evaluator": "validation_model",
    "translation": "translation_model",
}
TASK_MAX_TOKENS = {
    "summary_generator": 8000,
    "summary_passage_notes": 4000,
    "book_summary_aggregator": 8000,
    "book_qa": 1500,
    "quiz_question_generator": 6000,
    "quiz_question_validator": 800,
    "answer_explainer": 800,
    "chapter_detector": 1000,
    "document_extraction_repair": 6000,
    "translation": 2000,
    "source_faithfulness_evaluator": 4000,
}

_provider_overrides: dict[str, LLMProvider] = {}
_provider_cache: dict[str, LLMProvider] = {}


def set_provider_override(name: str, provider: LLMProvider | None) -> None:
    """Test hook: replace a provider implementation (e.g. with a scripted fake)."""
    if provider is None:
        _provider_overrides.pop(name, None)
    else:
        _provider_overrides[name] = provider


def get_provider(name: str) -> LLMProvider:
    if name in _provider_overrides:
        return _provider_overrides[name]
    if name not in _provider_cache:
        if name == "anthropic":
            from app.ai.providers.anthropic_provider import AnthropicProvider

            _provider_cache[name] = AnthropicProvider()
        elif name == "extractive":
            _provider_cache[name] = ExtractiveProvider()
        else:
            raise AppError(ErrorCode.AI_PROVIDER_UNAVAILABLE, "The AI provider is not configured.", status_code=503)
    return _provider_cache[name]


@dataclass
class Actor:
    user_id: uuid.UUID | None = None
    guest_session_id: uuid.UUID | None = None


@dataclass
class RoutedResult:
    data: dict[str, Any]
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost: float
    latency_ms: int


class ModelRouter:
    def __init__(self, db: Session, *, provider_name: str | None = None) -> None:
        self.db = db
        self.settings = get_settings()
        self.provider_name = provider_name or self.settings.default_llm_provider

    @property
    def provider(self) -> LLMProvider:
        return get_provider(self.provider_name)

    @property
    def is_offline(self) -> bool:
        return self.provider_name == "extractive"

    def model_for(self, task: str) -> str:
        if self.is_offline:
            return "extractive-v1"
        return getattr(self.settings, TASK_MODEL_SETTING.get(task, "summary_model"))

    def spent_today(self) -> float:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        total = self.db.scalar(select(func.coalesce(func.sum(AIExecution.estimated_cost), 0.0)).where(AIExecution.created_at >= start))
        return float(total or 0.0)

    def supports_language(self, task: str, output_language: str, source_language: str | None) -> bool:
        return self.provider.supports_language(task, output_language, source_language)

    def generate(
        self,
        task: str,
        *,
        variables: dict[str, Any],
        context: dict[str, Any],
        output_language: str = "en",
        source_language: str | None = None,
        book_id: uuid.UUID | None = None,
        actor: Actor | None = None,
        escalate: bool = False,
    ) -> RoutedResult:
        settings = self.settings
        provider = self.provider
        if not provider.supports_language(task, output_language, source_language):
            raise AppError(
                ErrorCode.LANGUAGE_UNSUPPORTED,
                "This output language is not available with the current AI engine. The offline engine can only "
                "produce content in the book's own language; configure an LLM provider for translated output.",
                status_code=422,
                details={"output_language": output_language, "source_language": source_language},
            )
        if not self.is_offline and self.spent_today() >= settings.ai_daily_budget:
            raise AppError(
                ErrorCode.AI_BUDGET_EXCEEDED,
                "Readbit has reached today's AI usage limit. Existing summaries and quizzes remain available.",
                status_code=503,
            )
        template = load_prompt(task)
        system, user = template.render(output_language=output_language, **variables)
        schema = SCHEMAS[task]
        models = [self.model_for(task)]
        if not self.is_offline and settings.escalation_model not in models:
            if escalate:
                models = [settings.escalation_model]
            else:
                models.append(settings.escalation_model)
        max_tokens = min(TASK_MAX_TOKENS.get(task, 4000), max(settings.max_generation_tokens, 1000))

        last_error: Exception | None = None
        for model in models:
            attempts = 1 + max(0, settings.llm_max_retries)
            for attempt in range(attempts):
                request = GenerationRequest(
                    task=task,
                    prompt_version=template.version,
                    system=system,
                    user=user,
                    schema=schema,
                    model=model,
                    max_tokens=max_tokens,
                    output_language=output_language,
                    context=context,
                )
                started = time.monotonic()
                try:
                    result = provider.generate(request, timeout=settings.llm_timeout_seconds)
                    jsonschema.validate(result.data, schema)
                    self._record(task, template.version, result, started, book_id, actor, success=True)
                    if result.data.get("language_ok") is False:
                        raise AppError(
                            ErrorCode.LANGUAGE_UNSUPPORTED,
                            "The AI engine could not reliably write in the requested language.",
                            status_code=422,
                        )
                    return RoutedResult(
                        data=result.data,
                        provider=result.provider,
                        model=result.model,
                        prompt_version=template.version,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        cost=estimate_cost(result.model, result.input_tokens, result.output_tokens),
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                except jsonschema.ValidationError as exc:
                    last_error = exc
                    self._record_failure(task, template.version, model, started, book_id, actor, "schema_invalid")
                    log.warning("ai output failed schema", extra={"task": task, "model": model})
                    break  # escalate to the next model rather than repeating the same one
                except ProviderError as exc:
                    last_error = exc
                    self._record_failure(task, template.version, model, started, book_id, actor, exc.category)
                    log.warning("ai provider error", extra={"task": task, "model": model, "category": exc.category})
                    if not exc.retryable:
                        break
                    if attempt + 1 < attempts:
                        time.sleep(min(8.0, 0.5 * (2**attempt)))
        if isinstance(last_error, ProviderError) and last_error.category in ("rate_limited", "timeout", "connection", "api_status", "auth"):
            raise AppError(
                ErrorCode.AI_PROVIDER_UNAVAILABLE,
                "The AI service is temporarily unavailable. Your book and progress are safe; please retry shortly.",
                status_code=503,
            )
        raise AppError(
            ErrorCode.AI_OUTPUT_INVALID,
            "The AI engine did not produce a valid, source-grounded result. Nothing was saved; please retry.",
            status_code=502,
        )

    def _record(self, task, version, result: GenerationResult, started, book_id, actor, success: bool) -> None:
        self.db.add(
            AIExecution(
                book_id=book_id,
                user_id=actor.user_id if actor else None,
                guest_session_id=actor.guest_session_id if actor else None,
                task_type=task,
                provider=result.provider,
                model=result.model,
                prompt_version=version,
                input_token_count=result.input_tokens,
                output_token_count=result.output_tokens,
                estimated_cost=estimate_cost(result.model, result.input_tokens, result.output_tokens),
                latency_ms=int((time.monotonic() - started) * 1000),
                success=success,
            )
        )
        self.db.flush()

    def _record_failure(self, task, version, model, started, book_id, actor, category: str) -> None:
        self.db.add(
            AIExecution(
                book_id=book_id,
                user_id=actor.user_id if actor else None,
                guest_session_id=actor.guest_session_id if actor else None,
                task_type=task,
                provider=self.provider_name,
                model=model,
                prompt_version=version,
                latency_ms=int((time.monotonic() - started) * 1000),
                success=False,
                failure_category=category,
            )
        )
        self.db.flush()


