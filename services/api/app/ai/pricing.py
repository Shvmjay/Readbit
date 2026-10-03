"""Per-model token prices (USD per million tokens) for cost estimation. Update when provider pricing changes."""

from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "extractive-v1": (0.0, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICES.get(model, (5.0, 25.0))  # unknown models are priced conservatively
    return round(input_tokens / 1_000_000 * inp + output_tokens / 1_000_000 * out, 6)
