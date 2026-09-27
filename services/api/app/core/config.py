"""Application configuration.

All settings come from environment variables (see `.env.example` at the repository root).
Settings are validated at startup; production refuses to boot with unsafe defaults.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEV_SECRET = "dev-insecure-secret-change-me-0123456789abcdef"  # noqa: S105 - rejected in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore", case_sensitive=False)

    # --- Application
    app_env: Literal["development", "test", "production"] = "development"
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    secret_key: str = INSECURE_DEV_SECRET
    cors_origins: str = "http://localhost:3000"
    # Only enable when the API is reachable exclusively through a trusted proxy (the web app or a load balancer);
    # otherwise clients could spoof X-Forwarded-For to dodge per-IP rate limits.
    trust_proxy_headers: bool = False

    # --- Database
    database_url: str = "sqlite:///./readbit-dev.db"
    db_pool_size: int = 5
    db_echo: bool = False

    # --- Authentication
    auth_provider: Literal["local"] = "local"
    auth_issuer: str = "readbit"
    auth_client_id: str = ""
    auth_client_secret: str = ""
    session_ttl_hours: int = 24 * 14
    password_reset_ttl_minutes: int = 30
    email_delivery: Literal["log", "disabled"] = "log"

    # --- Object storage
    storage_provider: Literal["local", "s3"] = "local"
    storage_local_path: str = "./.data/storage"
    storage_bucket: str = "readbit-private"
    storage_region: str = "us-east-1"
    storage_endpoint: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""

    # --- Background jobs
    job_backend: Literal["inline", "thread", "celery"] = "thread"
    redis_url: str = "redis://localhost:6379/0"
    worker_concurrency: int = 2

    # --- AI
    default_llm_provider: Literal["extractive", "anthropic"] = "extractive"
    llm_api_key: str = ""
    summary_model: str = "claude-sonnet-5"
    qa_model: str = "claude-sonnet-5"
    quiz_model: str = "claude-sonnet-5"
    validation_model: str = "claude-sonnet-5"
    escalation_model: str = "claude-opus-5"
    translation_model: str = "claude-sonnet-5"
    llm_effort: Literal["low", "medium", "high"] = "medium"
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2
    embedding_provider: Literal["hashing"] = "hashing"
    embedding_model: str = "hashing-v1"
    embedding_dimensions: int = 256
    ocr_provider: Literal["none", "tesseract"] = "none"
    ocr_api_key: str = ""

    # --- Limits
    max_upload_size_mb: int = 50
    max_document_pages: int = 1500
    max_processing_duration: int = 900
    max_generation_tokens: int = 8000
    guest_retention_hours: int = 24
    user_rate_limit: int = 30  # AI requests per actor per minute
    upload_rate_limit: int = 10  # uploads per actor per 10 minutes
    ai_daily_budget: float = 25.0  # USD across the deployment per UTC day
    max_excerpt_chars: int = 320
    max_quote_ratio: float = 0.35
    lesson_size: int = 5
    dedup_similarity_threshold: float = 0.9

    # --- Observability
    log_level: str = "INFO"
    error_tracking_dsn: str = ""
    metrics_enabled: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        problems: list[str] = []
        if self.is_production:
            if self.secret_key == INSECURE_DEV_SECRET or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be set to a random value of at least 32 characters.")
            if self.is_sqlite:
                problems.append("DATABASE_URL must point to PostgreSQL in production.")
            if self.job_backend != "celery":
                problems.append("JOB_BACKEND must be 'celery' in production.")
            if self.storage_provider == "local":
                problems.append("STORAGE_PROVIDER must be 's3' in production.")
        if self.default_llm_provider == "anthropic" and not self.llm_api_key:
            problems.append("LLM_API_KEY is required when DEFAULT_LLM_PROVIDER=anthropic.")
        if self.storage_provider == "s3" and not self.storage_bucket:
            problems.append("STORAGE_BUCKET is required when STORAGE_PROVIDER=s3.")
        if problems:
            raise ValueError("Invalid configuration: " + " ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
