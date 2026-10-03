"""Custom column types."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator, UserDefinedType

from app.core.config import get_settings


class _PgVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dim})"


class EmbeddingType(TypeDecorator):
    """pgvector `vector(n)` on PostgreSQL; JSON array elsewhere (SQLite tests).

    Values are always Python lists of floats at the application boundary.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int | None = None) -> None:
        super().__init__()
        self.dim = dim or get_settings().embedding_dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return "[" + ",".join(f"{float(v):.6f}" for v in value) + "]"
        return [float(v) for v in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return [float(v) for v in value.strip("[]").split(",") if v]
        return [float(v) for v in value]
