"""Summarize existing mode-evaluation receipts for non-binding unit economics."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TextIO

MODES = ("focused", "balanced", "deep")
PROVISIONAL_UNIT_WEIGHTS = {
    "focused": Decimal(1),
    "balanced": Decimal(2),
    "deep": Decimal(4),
}
MAX_LINE_CHARS = 1_048_576
MAX_RECORDS = 100_000


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    parts = number.as_tuple()
    if (
        not number.is_finite()
        or number < 0
        or number.adjusted() > 12
        or len(parts.digits) > 32
        or not isinstance(parts.exponent, int)
        or parts.exponent < -18
    ):
        return None
    return number


def _format(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.000001')):.6f}"


def _distribution(values: list[Decimal]) -> dict[str, Any]:
    ordered = sorted(values)

    def percentile(fraction: float) -> str | None:
        if not ordered:
            return None
        index = max(0, math.ceil(len(ordered) * fraction) - 1)
        return _format(ordered[index])

    return {
        "count": len(ordered),
        "total": _format(sum(ordered, Decimal(0))) if ordered else None,
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "max": _format(ordered[-1]) if ordered else None,
    }


def analyze_receipts(
    rows: list[Any], *, unit_weights: dict[str, Decimal] | None = None
) -> dict[str, Any]:
    """Aggregate only mode, outcome, and cost fields; never retain prompts or IDs.

    Duplicate `(case_id, mode)` rows use the last receipt, matching the live
    evaluation runner's resume semantics. Rows without a case ID remain separate.
    Costs are estimates from the existing run ledger/model pricing receipts, not
    provider invoices or a customer charge.
    """
    weights = PROVISIONAL_UNIT_WEIGHTS if unit_weights is None else unit_weights
    if set(weights) != set(MODES) or any(
        not isinstance(weight, Decimal) or not weight.is_finite() or weight <= 0
        for weight in weights.values()
    ):
        raise ValueError("unit weights must be positive Decimal values for every mode")
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    standalone: list[dict[str, Any]] = []
    malformed = unknown_mode = duplicate_receipts = 0

    for row in rows:
        if not isinstance(row, dict):
            malformed += 1
            continue
        mode, status = row.get("mode"), row.get("status")
        if mode not in MODES or not isinstance(status, str):
            unknown_mode += 1
            continue
        safe_row = {
            "mode": mode,
            "status": status,
            "ledger_cost": _decimal(row.get("ledger_cost_usd")),
            "model_cost": _decimal(row.get("model_cost_usd")),
        }
        case_id = row.get("case_id")
        if isinstance(case_id, str) and case_id and len(case_id) <= 200:
            key = (case_id, mode)
            if key in latest:
                duplicate_receipts += 1
            latest[key] = safe_row
        else:
            standalone.append(safe_row)

    selected = [*latest.values(), *standalone]
    result: dict[str, Any] = {
        "schema": "billing-economics-shadow-v1",
        "interpretation": {
            "costs": "Estimated provider cost, not an invoice or user charge.",
            "weights": "Provisional scenario only; not approved pricing or quota policy.",
            "coverage": "Only supplied receipts are measured; missing costs are not zero.",
            "duplicateReceipts": "Last row per case_id and mode is retained.",
        },
        "unitPolicy": {
            "version": "provisional-mode-weights-1-2-4",
            "status": "not_approved",
            "weights": {mode: str(weights[mode]) for mode in MODES},
        },
        "input": {
            "rows": len(rows),
            "accepted": len(selected),
            "malformed": malformed,
            "unknown_mode": unknown_mode,
            "duplicate_receipts": duplicate_receipts,
        },
        "modes": {},
    }

    for mode in MODES:
        mode_rows = [row for row in selected if row["mode"] == mode]
        outcomes = Counter(
            status if status in {"completed", "failed", "cancelled"} else "other"
            for status in (row["status"] for row in mode_rows)
        )
        ledger_costs = [row["ledger_cost"] for row in mode_rows if row["ledger_cost"] is not None]
        model_costs = [row["model_cost"] for row in mode_rows if row["model_cost"] is not None]
        unit_costs = [
            cost / weights[mode]
            for cost in ledger_costs
            if weights.get(mode) is not None and weights[mode] > 0
        ]
        ledger_distribution = _distribution(ledger_costs)
        model_distribution = _distribution(model_costs)
        ledger_distribution["missing"] = len(mode_rows) - len(ledger_costs)
        model_distribution["missing"] = len(mode_rows) - len(model_costs)
        result["modes"][mode] = {
            "runs": len(mode_rows),
            "outcomes": dict(sorted(outcomes.items())),
            "ledger_estimated_cost_usd": ledger_distribution,
            "model_estimated_cost_usd": model_distribution,
            "provisional_units": {
                "weight": str(weights[mode]),
                "cost_per_unit_total": (
                    _format(sum(ledger_costs, Decimal(0)) / (weights[mode] * len(ledger_costs)))
                    if ledger_costs and weights.get(mode) and weights[mode] > 0
                    else None
                ),
                "per_run_cost_distribution_usd": _distribution(unit_costs),
                "cost_sample_count": len(ledger_costs),
            },
        }
    return result


def load_receipts(stream: TextIO, *, max_records: int = MAX_RECORDS) -> list[Any]:
    rows: list[Any] = []
    while True:
        line = stream.readline(MAX_LINE_CHARS + 1)
        if not line:
            return rows
        if len(rows) >= max_records or len(line) > MAX_LINE_CHARS:
            raise ValueError("input limit exceeded; narrow the receipt file")
        try:
            rows.append(json.loads(line))
        except (json.JSONDecodeError, RecursionError):
            rows.append(None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("receipts", type=Path, help="JSONL receipts from live_mode_evaluation.py")
    parser.add_argument("--output", type=Path, help="write aggregate JSON here; defaults to stdout")
    args = parser.parse_args()
    try:
        with args.receipts.open(encoding="utf-8") as stream:
            result = analyze_receipts(load_receipts(stream))
        rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
