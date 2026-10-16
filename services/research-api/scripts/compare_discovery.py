"""Compare matched paid benchmark records offline; preserve partial failures."""

import argparse
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any


def compare(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 2:
        raise ValueError("exactly two benchmark result records required")
    by_provider = {row.get("discoveryProvider"): row for row in rows}
    if set(by_provider) != {"tavily", "serper"}:
        raise ValueError("one record per discovery route required")
    baseline, candidate = by_provider["tavily"], by_provider["serper"]
    if baseline.get("mode") != "focused" or candidate.get("mode") != "focused":
        raise ValueError("matched Focused report records required")
    fingerprint = baseline.get("workloadFingerprint")
    if (
        not isinstance(fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
        or fingerprint != candidate.get("workloadFingerprint")
    ):
        raise ValueError("workload, model routes and budgets must match")

    def number(row: dict[str, Any], field: str, *, nullable: bool = False) -> float | None:
        value = row.get(field)
        if value is None and nullable:
            return None
        if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
            raise ValueError("missing or invalid measurement")
        return float(value)

    def metrics(row: dict[str, Any]) -> dict[str, Any]:
        run_status = row.get("status")
        if run_status not in {"completed", "failed"}:
            raise ValueError("unsupported run status")
        error_code = row.get("errorCode")
        if run_status == "failed" and not isinstance(error_code, str):
            raise ValueError("failed run error code required")
        quality = row.get("quality")
        coverage = row.get("coverage")
        if run_status == "completed" and (
            not isinstance(quality, dict) or not isinstance(coverage, dict)
        ):
            raise ValueError("quality assessment required")
        if quality is not None and not isinstance(quality, dict):
            raise ValueError("invalid quality assessment")
        if coverage is not None and not isinstance(coverage, dict):
            raise ValueError("invalid coverage assessment")
        findings = quality.get("verifiedFindings") if quality else None
        if findings is not None and (type(findings) is not int or not 0 <= findings <= 40):
            raise ValueError("invalid findings count")
        quality_status = quality.get("status") if quality else None
        if quality_status is not None and quality_status not in {
            "answered",
            "partial",
            "insufficient_evidence",
        }:
            raise ValueError("unknown quality status")
        if coverage:
            for field in (
                "requirementsTotal",
                "requirementsAddressed",
                "questionsTotal",
                "questionsAddressed",
            ):
                if type(coverage.get(field)) is not int or coverage[field] < 0:
                    raise ValueError("invalid coverage assessment")
            if (
                coverage["requirementsAddressed"] > coverage["requirementsTotal"]
                or coverage["questionsAddressed"] > coverage["questionsTotal"]
            ):
                raise ValueError("coverage counts exceed totals")
        diversity = row.get("sourceDiversity")
        if not isinstance(diversity, dict) or diversity.get("independenceAssessed") is not False:
            raise ValueError("source diversity must not claim source independence")
        for field in ("distinctHosts", "distinctPublishers"):
            if type(diversity.get(field)) is not int or diversity[field] < 0:
                raise ValueError("invalid source diversity measurement")
        try:
            cost = Decimal(row["accountedEstimatedCostUsd"])
        except (KeyError, InvalidOperation, TypeError, ValueError):
            raise ValueError("invalid cost estimate") from None
        if not cost.is_finite() or cost < 0:
            raise ValueError("invalid cost estimate")
        return {
            "status": run_status,
            "errorCode": error_code,
            "totalMs": number(row, "elapsedMs"),
            "firstSourceMs": number(row, "firstSourceFromCreationMs", nullable=True),
            "sources": number(row, "sources"),
            "providerOperations": number(row, "providerOperations"),
            "verifiedFindings": findings,
            "qualityStatus": quality_status,
            "coverage": coverage,
            "sourceDiversity": diversity,
            "estimatedCostUsd": str(cost),
            "execution": {
                field: row.get(field, [])
                for field in ("modelCalls", "synthesis", "dependencies", "nodes")
            },
        }

    base, test = metrics(baseline), metrics(candidate)
    return {
        "workloadFingerprint": fingerprint,
        "baseline": base,
        "candidate": test,
        "candidateMinusBaseline": {
            **{
                key: (
                    round(test[key] - base[key], 2)
                    if base[key] is not None and test[key] is not None
                    else None
                )
                for key in (
                    "totalMs",
                    "firstSourceMs",
                    "sources",
                    "providerOperations",
                    "verifiedFindings",
                )
            },
            "requirementsAddressed": _delta(
                base["coverage"], test["coverage"], "requirementsAddressed"
            ),
            "questionsAddressed": _delta(base["coverage"], test["coverage"], "questionsAddressed"),
            "distinctHosts": (
                test["sourceDiversity"]["distinctHosts"] - base["sourceDiversity"]["distinctHosts"]
            ),
            "distinctPublishers": (
                test["sourceDiversity"]["distinctPublishers"]
                - base["sourceDiversity"]["distinctPublishers"]
            ),
        },
        "estimatedCostDeltaUsd": str(
            Decimal(test["estimatedCostUsd"]) - Decimal(base["estimatedCostUsd"])
        ),
        "comparisonStatus": "complete_pair"
        if base["status"] == test["status"] == "completed"
        else "partial_pair_with_failure",
        "interpretation": "One matched pair is not a p95 or a causal speedup proof. "
        "Finding counts are not completeness, independence or factual certification. "
        "A failed arm has no completed report coverage and cannot establish answer-quality parity. "
        "Inspect unresolved requirements and source balance in each available report. "
        "Costs are ledger estimates, not vendor invoices.",
    }


def _delta(
    baseline: dict[str, Any] | None, candidate: dict[str, Any] | None, field: str
) -> int | None:
    if baseline is None or candidate is None:
        return None
    return candidate[field] - baseline[field]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    rows = []
    try:
        for index in range(1001):
            line = sys.stdin.readline(1_048_577)
            if not line:
                break
            if index >= 1000 or len(line) > 1_048_576:
                raise ValueError("input bound exceeded")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("invalid record")
            if row.get("event") in {"benchmark.result", "benchmark.completed"}:
                rows.append(row)
        print(json.dumps(compare(rows), sort_keys=True))
    except (ValueError, TypeError, OverflowError, RecursionError):
        print("Invalid or unmatched benchmark pair", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
