"""Embedding providers.

The default `hashing` embedder is a deterministic, dependency-free lexical embedding (signed feature hashing of
unigrams and bigrams, L2-normalised). It needs no API key and is language-agnostic, which makes retrieval and
semantic deduplication reproducible in tests. It captures lexical rather than deep semantic similarity; a neural
embedding provider can be added behind the same interface (see docs/AI_GROUNDING.md).
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import get_settings
from app.document_processing.text import content_words


class Embedder(ABC):
    name: str
    dimensions: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _stem(tok: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


class HashingEmbedder(Embedder):
    name = "hashing-v1"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        toks = [_stem(t) for t in content_words(text)]
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            idx = h % self.dimensions
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign * (1.0 if "_" not in f else 0.5)
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False))


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    return HashingEmbedder(s.embedding_dimensions)
