"""Anthropic Claude adapter using the official SDK and JSON-schema structured outputs."""

from __future__ import annotations

import json

import anthropic

from app.ai.providers.base import GenerationRequest, GenerationResult, LLMProvider, ProviderError
from app.core.config import get_settings


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        # Retries are owned by the router (bounded, with backoff and cost accounting), so the SDK does not retry.
        self.client = anthropic.Anthropic(
            api_key=api_key or settings.llm_api_key, max_retries=0, timeout=settings.llm_timeout_seconds
        )
        self.effort = settings.llm_effort

    def generate(self, request: GenerationRequest, timeout: float) -> GenerationResult:
        try:
            with self.client.messages.stream(
                model=request.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": request.schema},
                },
                timeout=timeout,
            ) as stream:
                message = stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise ProviderError("rate limited", retryable=True, category="rate_limited") from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("timeout", retryable=True, category="timeout") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("connection error", retryable=True, category="connection") from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderError("authentication failed", retryable=False, category="auth") from exc
        except anthropic.BadRequestError as exc:
            raise ProviderError("bad request", retryable=False, category="bad_request") from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409, 429, 529)
            raise ProviderError(f"status {exc.status_code}", retryable=retryable, category="api_status") from exc

        if message.stop_reason == "refusal":
            raise ProviderError("model declined the request", retryable=False, category="refusal")
        if message.stop_reason == "max_tokens":
            raise ProviderError("output exceeded max_tokens", retryable=False, category="max_tokens")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("invalid JSON output", retryable=True, category="invalid_json") from exc
        usage = message.usage
        return GenerationResult(
            data=data,
            provider=self.name,
            model=request.model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            stop_reason=message.stop_reason,
        )
