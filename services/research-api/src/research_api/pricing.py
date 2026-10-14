"""Versioned standard text-rate snapshot, not a provider invoice.

Reviewed 2026-10-13 against https://developers.openai.com/api/docs/models/gpt-4o-mini
Unknown models retain an explicitly labelled policy estimate. No tool/service-tier fees.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

PRICING_VERSION = "openai-standard-text-2026-10-13"
POLICY_MODEL_COST = Decimal("0.10")


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


def model_rate(model: str) -> TextRate | None:
    if model in {"gpt-4o-mini", "gpt-4o-mini-2024-07-18"}:
        return TextRate(Decimal("0.15"), Decimal("0.075"), Decimal("0.60"))
    return None
