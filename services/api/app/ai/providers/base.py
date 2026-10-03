"""Provider interface. Business logic never talks to a vendor SDK directly."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationRequest:
    task: str  # prompt id, e.g. "summary_generator"
    prompt_version: str
    system: str
    user: str
    schema: dict[str, Any]
    model: str
    max_tokens: int
    output_language: str = "en"
    # Structured inputs for providers that do not read prompts (the offline extractive engine).
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    data: dict[str, Any]
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


class ProviderError(Exception):
    """Raised by providers. `retryable` controls router retries; `category` feeds AIExecution.failure_category."""

    def __init__(self, message: str, *, retryable: bool, category: str) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.category = category


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, request: GenerationRequest, timeout: float) -> GenerationResult: ...

    def supports_language(self, task: str, output_language: str, source_language: str | None) -> bool:
        return True
