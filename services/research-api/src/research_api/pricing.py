"""Versioned standard text-rate snapshots; estimates are not provider invoices."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

PRICING_VERSION = "policy-estimate-v1"
POLICY_MODEL_COST = Decimal("0.10")
# Conservative policy reservation, not a vendor invoice or current price quote.
SERPER_SEARCH_POLICY_COST = Decimal("0.001")

_RATES: dict[tuple[str, str], tuple[str, "TextRate"]] = {}


@dataclass(frozen=True)
class TextRate:
    input: Decimal
    cached_input: Decimal
    output: Decimal

    def cost(self, input_tokens: int, output_tokens: int, cached: int = 0) -> Decimal:
        if min(input_tokens, output_tokens, cached) < 0 or cached > input_tokens:
            raise ValueError("invalid model usage")
        return (
            (
                (input_tokens - cached) * self.input
                + cached * self.cached_input
                + output_tokens * self.output
            )
            / Decimal(1_000_000)
        ).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


_RATES.update(
    {
        ("openai", "gpt-4o-mini"): (
            "openai-standard-text-2026-10-13",
            TextRate(Decimal("0.15"), Decimal("0.075"), Decimal("0.60")),
        ),
        ("openai", "gpt-4o-mini-2024-07-18"): (
            "openai-standard-text-2026-10-13",
            TextRate(Decimal("0.15"), Decimal("0.075"), Decimal("0.60")),
        ),
        ("openai", "gpt-5.4-mini"): (
            "openai-standard-text-2026-10-16",
            TextRate(Decimal("0.75"), Decimal("0.075"), Decimal("4.50")),
        ),
        ("openai", "gpt-6-luna"): (
            "openai-standard-text-2026-10-16",
            TextRate(Decimal("0.10"), Decimal("0.01"), Decimal("0.50")),
        ),
        ("openrouter", "deepseek/deepseek-v4.1-flash"): (
            "openrouter-deepseek-v4.1-flash-2026-10-17",
            TextRate(Decimal("0.08"), Decimal("0.007"), Decimal("0.55")),
        ),
    }
)


def model_rate(model: str, provider: str = "openai") -> TextRate | None:
    entry = _RATES.get((provider, model))
    return entry[1] if entry else None


def model_pricing_version(model: str, provider: str = "openai") -> str | None:
    entry = _RATES.get((provider, model))
    return entry[0] if entry else None
