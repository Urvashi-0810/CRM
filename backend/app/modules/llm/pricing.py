"""Prices (USD per 1M tokens) used to log the cost of each call.

Sources (checked 9 Oct 2026):
- Claude: https://platform.claude.com/docs/en/about-claude/pricing
- Gemini: https://ai.google.dev/gemini-api/docs/pricing
Update this file when prices change; past calls keep the cost stored at call time.
A model not listed here is still usable — its cost is just recorded as unknown.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal


def _p(i, o, r, w=None) -> Price:
    i, o, r = Decimal(str(i)), Decimal(str(o)), Decimal(str(r))
    return Price(i, o, r, Decimal(str(w)) if w is not None else i)


# (model prefix, price for prompts <= threshold, price above threshold, threshold tokens)
CLAUDE = [
    ("claude-sonnet-5-5", _p(2, 10, 0.10, 2.50), None, None),
    ("claude-opus-5-5", _p(4, 20, 0.20, 5), None, None),
    ("claude-haiku-5-5", _p(0.10, 0.50, 0.01, 0.125), _p(0.50, 2.50, 0.05, 0.625), 100_000),
]

# Gemini 3.6-3.8 Flash prices change on 1 Jan 2027.
_FLASH_2026 = _p(0.75, 3.75, 0.075)
_FLASH_2027 = _p(1.50, 7.50, 0.15)
GEMINI = [
    ("gemini-3.1-pro", _p(2, 12, 0.20), _p(4, 18, 0.40), 200_000),
    ("gemini-3.5-flash-lite", _p(0.30, 2.50, 0.03), None, None),
    ("gemini-3.1-flash-lite", _p(0.25, 1.50, 0.025), None, None),
    ("gemini-3.5-flash", _p(1.50, 9.00, 0.15), None, None),
]
GEMINI_NEW_FLASH = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash")


def price_for(provider: str, model: str, prompt_tokens: int, today: date | None = None) -> Price | None:
    today = today or date.today()
    if provider == "gemini" and model.startswith(GEMINI_NEW_FLASH):
        return _FLASH_2026 if today < date(2027, 1, 1) else _FLASH_2027
    table = CLAUDE if provider == "claude" else GEMINI if provider == "gemini" else []
    # Longest prefix first so "flash-lite" wins over "flash".
    for prefix, low, high, threshold in sorted(table, key=lambda t: -len(t[0])):
        if model.startswith(prefix):
            return high if (high and threshold and prompt_tokens > threshold) else low
    return None


def cost_usd(
    provider: str,
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal | None:
    """input_tokens = uncached input only (cache reads/writes are passed separately)."""
    prompt_total = input_tokens + cache_read_tokens + cache_write_tokens
    price = price_for(provider, model, prompt_total)
    if price is None:
        return None
    million = Decimal(1_000_000)
    total = (
        price.input * input_tokens
        + price.output * output_tokens
        + price.cache_read * cache_read_tokens
        + price.cache_write * cache_write_tokens
    ) / million
    return total.quantize(Decimal("0.000001"))
