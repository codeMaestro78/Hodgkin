"""Offline mode evaluation. No provider, database, or application startup imports."""

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation/modes/v1"
Mode = Literal["focused", "balanced", "deep"]
Count = Annotated[int, Field(ge=0)]
Positive = Annotated[int, Field(gt=0)]
Text = Annotated[str, Field(min_length=1)]
Number = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Dimension(Record):
    id: Text
    description: Text
    tier: Literal["core", "tail"]


class Case(Record):
    version: Literal["modes-v1"]
    id: Text
    category: Literal[
        "comparison",
        "factual",
        "current",
        "academic",
        "conflicting",
        "multi_requirement",
        "insufficient",
    ]
    question: Text
    evaluation_owner: Text
    label_status: Literal["draft_awaiting_human_adjudication"]
    draft_answerability: Literal["answerable", "partial", "insufficient", "time_dependent"]
    requirements: list[Text] = Field(min_length=1)
    dimensions: list[Dimension] = Field(min_length=1)
    draft_gold_expectations: list[Text] = Field(min_length=1)
    reference_selection: Text

    @model_validator(mode="after")
    def unique_dimensions(self):
        ids = [d.id for d in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate dimension ID")
        return self


class Limits(Record):
    provider_operations: Positive
    sources: Positive
    candidate_findings: Positive
    context_chars: Positive
    output_tokens: Positive
    plan_questions: Positive


class Usage(Record):
    operations: dict[Literal["search", "extract", "browser", "academic"], Count]
    sources: Count
    verified_findings: Count
    input_tokens: Count | None
    output_tokens: Count | None


class Ratio(Record):
    numerator: Count
    denominator: Count

    @model_validator(mode="after")
    def bounded(self):
        if self.numerator > self.denominator:
            raise ValueError("numerator exceeds denominator")
        return self


METRICS = (
    "claim_precision",
    "exact_citation_correctness",
    "citation_completeness",
    "evidence_attribution",
    "provenance_completeness",
    "independence_assessment",
    "primary_source_coverage",
    "secondary_source_coverage",
    "contradiction_recall",
    "disagreement_preservation",
    "unsupported_assertion_rate",
    "abstention_calibration",
)


class Measurement(Record):
    value: Number | None
    source: Text | None

    @model_validator(mode="after")
    def sourced(self):
        if (self.value is None) != (self.source is None):
            raise ValueError("measurement requires both value and source, or neither")
        return self


class Observation(Record):
    version: Literal["modes-observation-v1"]
    case_id: Text
    mode: Mode
    requested_mode: Mode | None
    policy_origin: Literal["legacy-inferred", "explicit"]
    evidence_kind: Literal["synthetic", "frozen_provider_replay", "live_observation"]
    snapshot: dict[Text, Text]
    receipt_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    limits: Limits
    usage: Usage
    dimension_states: dict[Text, Literal["established", "partial", "not_established", "unknown"]]
    quality: Literal["partial", "insufficient_evidence"]
    failed: bool
    human_review_reference: Text | None
    metrics: dict[Text, Ratio | None]
    human_scores: dict[
        Literal["directness", "decision_usefulness", "information_density"],
        Annotated[int, Field(ge=1, le=5)] | None,
    ]
    measurements: dict[
        Literal[
            "queue_wait_ms",
            "first_useful_evidence_ms",
            "end_to_end_ms",
            "estimated_cost_usd",
            "settled_cost_usd",
        ],
        Measurement,
    ]

    @model_validator(mode="after")
    def consistent(self):
        if self.requested_mode is None:
            if self.policy_origin != "legacy-inferred":
                raise ValueError("null mode must mean legacy")
        elif self.policy_origin != "explicit" or self.requested_mode != self.mode:
            raise ValueError("explicit mode must be preserved, including small budgets")
        if sum(self.usage.operations.values()) > self.limits.provider_operations:
            raise ValueError("operation ceiling exceeded")
        if self.usage.sources > self.limits.sources:
            raise ValueError("source ceiling exceeded")
        if self.usage.verified_findings > self.limits.candidate_findings:
            raise ValueError("finding ceiling exceeded")
        if set(self.metrics) != set(METRICS):
            raise ValueError("metric keys must match v1 rubric")
        if set(self.human_scores) != {"directness", "decision_usefulness", "information_density"}:
            raise ValueError("human score keys must match rubric")
        if (
            any(v is not None for v in self.human_scores.values())
            and not self.human_review_reference
        ):
            raise ValueError("human scores require review reference")
        if set(self.measurements) != {
            "queue_wait_ms",
            "first_useful_evidence_ms",
            "end_to_end_ms",
            "estimated_cost_usd",
            "settled_cost_usd",
        }:
            raise ValueError("measurement keys must match v1 schema")
        if self.evidence_kind == "synthetic":
            if self.human_review_reference or any(
                m.value is not None for m in self.measurements.values()
            ):
                raise ValueError(
                    "synthetic observations cannot claim human review/live measurements"
                )
        return self


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique_pairs)


def load_cases(path):
    rows = [Case.model_validate(json.loads(line)) for line in path.read_text().splitlines() if line]
    if len(rows) != 20 or len({row.id for row in rows}) != 20:
        raise ValueError("v1 workload requires exactly 20 unique cases")
    return rows


def validate_observations(raw, cases):
    rows = [Observation.model_validate(row) for row in raw]
    by_id = {case.id: case for case in cases}
    seen = set()
    for row in rows:
        key = row.case_id, row.mode
        if key in seen:
            raise ValueError("duplicate case/mode observation; use separate experiment files")
        seen.add(key)
        if row.case_id not in by_id:
            raise ValueError("unknown case ID")
        if set(row.dimension_states) != {d.id for d in by_id[row.case_id].dimensions}:
            raise ValueError("dimension IDs must exactly match case")
    if not rows:
        raise ValueError("empty observations")
    if len({canonical(row.snapshot) for row in rows}) != 1:
        raise ValueError("mixed model/provider/prompt/schema/graph snapshots")
    if len({row.evidence_kind for row in rows}) != 1:
        raise ValueError("synthetic, replay, and live observations must be separate experiments")
    required = {"model", "provider", "prompt", "schema", "graph", "policy"}
    if not required <= rows[0].snapshot.keys():
        raise ValueError("missing reproducibility snapshot fields")
    return rows


def percentile(values, percentile_value):
    """Nearest-rank percentile; no interpolation, no invented zero for missing samples."""
    return sorted(values)[max(0, math.ceil(len(values) * percentile_value) - 1)] if values else None


def aggregate(rows, cases):
    by_id = {case.id: case for case in cases}
    summaries = {}
    for mode in ("focused", "balanced", "deep"):
        group = [row for row in rows if row.mode == mode]
        ratios = {}
        for metric in METRICS:
            values = [row.metrics[metric] for row in group if row.metrics[metric] is not None]
            numerator = sum(v.numerator for v in values)
            denominator = sum(v.denominator for v in values)
            ratios[metric] = {
                "numerator": numerator,
                "denominator": denominator,
                "value": numerator / denominator if denominator else None,
                "measured_runs": len(values),
            }
        for tier in ("core", "tail"):
            states = [
                row.dimension_states[d.id]
                for row in group
                for d in by_id[row.case_id].dimensions
                if d.tier == tier
            ]
            ratios[f"{tier}_dimension_coverage"] = {
                "numerator": states.count("established"),
                "denominator": len(states),
                "value": states.count("established") / len(states) if states else None,
            }
        measurements = {}
        for name in (
            "queue_wait_ms",
            "first_useful_evidence_ms",
            "end_to_end_ms",
            "estimated_cost_usd",
            "settled_cost_usd",
        ):
            values = [
                row.measurements[name].value
                for row in group
                if row.measurements[name].value is not None
            ]
            measurements[name] = {
                "samples": len(values),
                "p50": percentile(values, 0.50),
                "p95": percentile(values, 0.95),
                "total": sum(values) if values else None,
            }
        cost_rows = [row for row in group if row.measurements["settled_cost_usd"].value is not None]
        cost = sum(row.measurements["settled_cost_usd"].value for row in cost_rows)
        findings = sum(row.usage.verified_findings for row in cost_rows)
        covered = sum(list(row.dimension_states.values()).count("established") for row in cost_rows)
        summaries[mode] = {
            "runs": len(group),
            "failures": sum(row.failed for row in group),
            "quality": dict(sorted(Counter(row.quality for row in group).items())),
            "effective_limits": [
                json.loads(value)
                for value in sorted({canonical(row.limits.model_dump()) for row in group})
            ],
            "operations": sum(sum(row.usage.operations.values()) for row in group),
            "sources": sum(row.usage.sources for row in group),
            "verified_findings": sum(row.usage.verified_findings for row in group),
            "tokens": {
                name: {
                    "samples": sum(getattr(row.usage, name) is not None for row in group),
                    "total": sum(getattr(row.usage, name) or 0 for row in group)
                    if any(getattr(row.usage, name) is not None for row in group)
                    else None,
                }
                for name in ("input_tokens", "output_tokens")
            },
            "metrics": ratios,
            "measurements": measurements,
            "settled_cost_per_verified_finding": cost / findings if findings else None,
            "settled_cost_per_established_dimension": cost / covered if covered else None,
            "human_scores": {
                name: {
                    "samples": len(scores),
                    "mean": sum(scores) / len(scores) if scores else None,
                }
                for name in ("directness", "decision_usefulness", "information_density")
                for scores in [
                    [row.human_scores[name] for row in group if row.human_scores[name] is not None]
                ]
            },
        }
    blockers = [
        "phase5 thresholds/non-inferiority margins not preregistered",
        "phase5 safety/recovery/tenant/cancellation suite receipts not evaluated by this tool",
        "draft case gold expectations await independent human adjudication",
        "phase5 matched quality/effort comparisons require a separate reviewed release decision",
    ]
    if any(row.evidence_kind != "live_observation" for row in rows):
        blockers.append(
            "no matched live observations; synthetic/replay is regression evidence only"
        )
    if any(not row.human_review_reference for row in rows):
        blockers.append("human-reviewed output labels missing")
    if any(value["runs"] != len(cases) for value in summaries.values()):
        blockers.append("incomplete 20-case x 3-mode matrix")
    if any(m.value is None for row in rows for m in row.measurements.values()):
        blockers.append("latency/cost observations missing")
    return {
        "version": "modes-summary-v1",
        "evidence_kind": rows[0].evidence_kind,
        "snapshot": rows[0].snapshot,
        "modes": summaries,
        "release_gate": {"status": "blocked", "reasons": blockers},
    }


def replay(cases, fixture_dir=FIXTURES):
    """Replay authored toy receipts; does not run the LangGraph/provider/verifier pipeline."""
    receipts = load_json(fixture_dir / "synthetic-receipts.json")
    if set(receipts) != {case.id for case in cases}:
        raise ValueError("synthetic receipt IDs must match cases")
    # The v1 baseline records the legacy policy as it was evaluated. Importing
    # current runtime policy here would silently re-interpret frozen receipts.
    policies = load_json(fixture_dir / "legacy-policy.json")
    if not isinstance(policies, dict) or set(policies) != {
        "6",
        "12",
        "20",
        "source_reports_py_sha256",
    }:
        raise ValueError("invalid archived legacy policy modes")
    original_hash = policies.pop("source_reports_py_sha256")
    if (
        not isinstance(original_hash, str)
        or len(original_hash) != 64
        or any(character not in "0123456789abcdef" for character in original_hash)
    ):
        raise ValueError("invalid archived source policy fingerprint")
    for calls, mode in ((6, "focused"), (12, "balanced"), (20, "deep")):
        policy = policies[str(calls)]
        if not isinstance(policy, dict) or set(policy) != {"mode", "limits"}:
            raise ValueError("invalid archived legacy policy fields")
        limits = Limits.model_validate(policy["limits"])
        if policy["mode"] != mode or limits.provider_operations != calls:
            raise ValueError("archived legacy policy mode/operation mismatch")
        policies[str(calls)] = {"mode": mode, "limits": limits}
    policy_hash = sha256(fixture_dir / "legacy-policy.json")
    snapshot = {
        "model": "not_invoked",
        "provider": "authored_synthetic_receipts_v1",
        "prompt": "not_invoked",
        "schema": "modes-observation-v1",
        "graph": "not_executed",
        "policy": "archived_legacy_policy_sha256:" + policy_hash,
    }
    rows = []
    for case in cases:
        receipt = receipts[case.id]
        if set(receipt) != {"source_id", "text", "quote", "semantic_label", "dimension_id"}:
            raise ValueError("invalid synthetic receipt fields")
        if receipt["semantic_label"] not in {"supported", "unsupported"}:
            raise ValueError("invalid synthetic semantic label")
        if receipt["dimension_id"] not in {d.id for d in case.dimensions}:
            raise ValueError("receipt dimension is not in case")
        exact = bool(receipt["quote"]) and receipt["quote"] in receipt["text"]
        admitted = exact and receipt["semantic_label"] == "supported"
        for calls in (6, 12, 20):
            policy = policies[str(calls)]
            limits = policy["limits"]
            rows.append(
                {
                    "version": "modes-observation-v1",
                    "case_id": case.id,
                    "mode": policy["mode"],
                    "requested_mode": None,
                    "policy_origin": "legacy-inferred",
                    "evidence_kind": "synthetic",
                    "snapshot": snapshot,
                    "receipt_sha256": hashlib.sha256(canonical(receipt).encode()).hexdigest(),
                    "limits": limits.model_dump(),
                    "usage": {
                        "operations": {"search": 1, "extract": 1},
                        "sources": 1,
                        "verified_findings": int(admitted),
                        "input_tokens": None,
                        "output_tokens": None,
                    },
                    "dimension_states": {
                        d.id: "partial"
                        if admitted and d.id == receipt["dimension_id"]
                        else "unknown"
                        for d in case.dimensions
                    },
                    "quality": "partial" if admitted else "insufficient_evidence",
                    "failed": False,
                    "human_review_reference": None,
                    # These counters check the toy fixture only, never real provider quality.
                    "metrics": {
                        name: {"numerator": int(exact), "denominator": 1}
                        if name == "exact_citation_correctness"
                        else None
                        for name in METRICS
                    },
                    "human_scores": {
                        name: None
                        for name in ("directness", "decision_usefulness", "information_density")
                    },
                    "measurements": {
                        name: {"value": None, "source": None}
                        for name in (
                            "queue_wait_ms",
                            "first_useful_evidence_ms",
                            "end_to_end_ms",
                            "estimated_cost_usd",
                            "settled_cost_usd",
                        )
                    },
                }
            )
    return validate_observations(rows, cases)


def baseline(fixture_dir=FIXTURES):
    cases = load_cases(fixture_dir / "cases.jsonl")
    rows = replay(cases, fixture_dir)
    return {
        "version": "modes-baseline-v1",
        "scope": "synthetic_offline_harness_only",
        "inputs_sha256": {
            name: sha256(fixture_dir / name)
            for name in (
                "cases.jsonl",
                "synthetic-receipts.json",
                "legacy-policy.json",
                "rubric.md",
                "schema.json",
            )
        },
        "observations": [row.model_dump() for row in rows],
        "summary": aggregate(rows, cases),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("baseline", "aggregate", "schema", "check"))
    parser.add_argument("--input", type=Path, help="JSON array of v1 observations for aggregate")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument(
        "--require-release", action="store_true", help="exit 2 while release blocked"
    )
    args = parser.parse_args()
    try:
        if args.command == "schema":
            result = {
                "case": Case.model_json_schema(),
                "observation": Observation.model_json_schema(),
            }
        elif args.command == "aggregate":
            if args.input is None:
                parser.error("aggregate requires --input")
            raw = load_json(args.input)
            if not isinstance(raw, list):
                raise ValueError("input must be a JSON array of observations")
            cases = load_cases(args.fixtures / "cases.jsonl")
            result = aggregate(validate_observations(raw, cases), cases)
        else:
            result = baseline(args.fixtures)
            if args.command == "check":
                frozen = args.fixtures / "baseline.json"
                if frozen.read_text() != canonical(result):
                    raise ValueError(
                        "baseline differs; inspect policy/fixture changes before refreezing"
                    )
                manifest = load_json(args.fixtures / "manifest.json")
                for name, digest in manifest.items():
                    if name not in {
                        "cases.jsonl",
                        "synthetic-receipts.json",
                        "legacy-policy.json",
                        "rubric.md",
                        "schema.json",
                        "baseline.json",
                    }:
                        raise ValueError("unexpected manifest path")
                    if sha256(args.fixtures / name) != digest:
                        raise ValueError(f"artifact hash mismatch: {name}")
                if len(manifest) != 6:
                    raise ValueError("incomplete manifest")
                result = {"reproducible": True, "summary": result["summary"]}
        print(canonical(result), end="")
        gate = result.get("release_gate", result.get("summary", {}).get("release_gate", {}))
        return 2 if args.require_release and gate.get("status") != "passed" else 0
    except (ValueError, OSError, TypeError) as exc:
        print(f"evaluation input error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
