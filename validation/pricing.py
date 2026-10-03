"""Optional, transparent pricing for real-LLM cost estimation (v0.6.0-final, R1).

Design rules
------------
* Cost is derived **only** from this table and a real ``token_usage`` observation.
  There is no fall-back guess and no hard-coded cost anywhere else in the repo.
* Prices are per 1,000 tokens, in USD, and only for models we explicitly list.
  An unknown model yields ``None`` (never a fabricated number).
* This module is pure (no network, no secrets). It is imported lazily by the
  validation metrics layer so offline runs never touch it.
"""

from __future__ import annotations

from typing import Any

# (prompt_per_1k_usd, completion_per_1k_usd). Public list prices at the time of
# writing; treat as a *config* that the maintainer can update. Anything missing
# here means "cost not computable" -> reported as null, not as an estimate.
PRICES_USD_PER_1K: dict[str, tuple[float, float]] = {
    # DeepSeek (deepseek.com open platform)
    "deepseek-chat": (0.014, 0.028),          # cache-miss prompt / completion
    "deepseek-reasoner": (0.055, 0.55),
    "deepseek-v3": (0.014, 0.028),
    "deepseek-v4-pro": (0.0, 0.0),            # maintainer: fill when priced
    "deepseek-flash": (0.0, 0.0),             # maintainer: fill when priced
    # OpenAI-compatible reference prices (only used if such a model is configured)
    "gpt-4o-mini": (0.015, 0.06),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1-mini": (0.015, 0.06),
}


def compute_cost(model: str, token_usage: dict[str, Any] | None) -> float | None:
    """Return estimated USD cost, or ``None`` if it cannot be computed honestly.

    ``None`` is returned when there is no token usage, the model is unknown, or
    any price component is zero/unknown — never an invented figure.
    """
    if not isinstance(token_usage, dict):
        return None
    prompt = int(token_usage.get("prompt_tokens") or 0)
    completion = int(token_usage.get("completion_tokens") or 0)
    price = PRICES_USD_PER_1K.get((model or "").strip().lower())
    if price is None:
        return None
    prompt_price, completion_price = price
    if prompt_price <= 0 or completion_price <= 0:
        return None
    cost = (prompt / 1000.0) * prompt_price + (completion / 1000.0) * completion_price
    return round(cost, 6)
