"""Offline JSONL latency summaries. No application imports or network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import uuid
from collections import Counter
from contextlib import nullcontext
from typing import Any, TextIO

MAX_LINE_CHARS = 1_048_576
DEFAULT_MAX_RECORDS = 100_000
NODES = {
    "intake",
    "planner",
    "planner_delta",
    "research_worker",
    "reflector",
    "verifier",
    "synthesizer",
    "approval_gate",
}
OPERATIONS = {
    "auth.verify",
    "http.headers",
    "http.request",
    "db.transaction",
    "db.connection.acquire",
    "db.statement.slow",
    "db.statement.timing",
    "db.statement",
    "db.snapshot.collections",
    "dispatcher.claim",
    "dispatcher.finish",
    "dispatcher.budget",
    "dispatcher.execute",
    "dispatcher.poll",
    "dispatcher.heartbeat",
    "research.graph",
    "research.collect",
    "research.collect.provider",
    "research.semantic_review",
    "research.extract.admission",
    "research.source.artifacts",
    "research.source.persistence",
    "synthesis.audit",
    "synthesis.findings",
    "model",
    "search",
    "extract",
    "source",
    "admission",
    "accounting",
    "response_artifact",
} | {f"node.{node}" for node in NODES}
MILESTONES = {"research.first_verified_finding"}
PROVIDERS = {"openai", "openrouter", "tavily", "internal", "serper", "parallel"}
SQL_COMMANDS = {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "SET", "OTHER"}
_QUERY_FAMILY_BASE = {
    "runtime_job",
    "run",
    "sub_question_attempt",
    "sub_question",
    "node_execution",
    "provider_call",
    "run_event",
    "evidence_claim",
    "citation",
    "source",
    "report",
    "assessment",
    "research_plan",
    "plan_approval",
    "budget",
    "usage_ledger",
    "other",
}
QUERY_FAMILIES = _QUERY_FAMILY_BASE | {
    f"{family}_{lock}" for family in _QUERY_FAMILY_BASE for lock in ("exclusive", "shared")
}
SUCCESS = {"succeeded", "consumed"}
ERROR = {"failed", "released", "uncertain", "not_dispatched", "cancelled", "rejected"}
OTHER = {"estimated", "insufficient_evidence", "skipped", "cached", "paused"}


class InputLimitError(ValueError):
    """A fixed input bound was exceeded; no partial report should be emitted."""


def safe_label(value: Any, allowed: set[str]) -> str:
    """Only audited static labels survive verbatim, including in grouping keys."""
    if isinstance(value, str):
        if value in allowed:
            return value
        return "redacted:" + hashlib.sha256(value.encode(errors="surrogatepass")).hexdigest()[:16]
    return "missing"


def run_label(value: Any) -> str:
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except ValueError:
            return safe_label(value, set())
    return "missing"


def duration(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) and result >= 0 else None


def summarize(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": ordered[math.ceil(len(ordered) * 0.50) - 1] if ordered else None,
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
        "max_ms": ordered[-1] if ordered else None,
    }


def analyze(
    stream: TextIO, *, run_id: str | None = None, max_records: int = DEFAULT_MAX_RECORDS
) -> dict[str, Any]:
    """Exact nearest-rank percentiles, bounded by input lines rather than sampling.

    Each accepted event enters one operation/dependency group. run_nodes is a
    projection of node operations, never an additional source of observations.
    Unknown fields and exception messages are never retained or returned.
    """
    if max_records < 1:
        raise ValueError("max_records must be positive")
    selected_run = str(uuid.UUID(run_id)) if run_id is not None else None
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    milestones: Counter[str] = Counter()

    def observe(key: tuple[str, ...], record: dict[str, Any], field: str) -> None:
        group = groups.setdefault(
            key,
            {
                "records": 0,
                "excluded_durations": 0,
                "outcomes": Counter(),
                "record_counts": Counter(),
                "success": [],
                "errors": [],
                "other": [],
                "attempt_numbers": Counter(),
                "retries_scheduled": 0,
            },
        )
        outcome = record.get("outcome")
        if not isinstance(outcome, str) or outcome not in SUCCESS | ERROR | OTHER:
            outcome = "other"
        status = record.get("statusCode")
        bucket = "success" if outcome in SUCCESS else "errors" if outcome in ERROR else "other"
        if type(status) is int and status >= 400:
            bucket = "errors"
        group["records"] += 1
        group["record_counts"][bucket] += 1
        group["outcomes"][outcome] += 1
        if key[:2] == ("dependencies", "attempt"):
            attempt = record.get("attempt")
            if type(attempt) is int and 1 <= attempt <= 10:
                group["attempt_numbers"][str(attempt)] += 1
            if record.get("retryScheduled") is True:
                group["retries_scheduled"] += 1
        value = duration(record.get(field))
        if value is None:
            group["excluded_durations"] += 1
        else:
            group[bucket].append(value)
        if key[:2] == ("dependencies", "attempt"):
            remote = duration(record.get("remoteDurationMs"))
            if remote is None:
                group["excluded_remote_durations"] = group.get("excluded_remote_durations", 0) + 1
            else:
                group.setdefault(f"remote_{bucket}", []).append(remote)

    while True:
        line = stream.readline(MAX_LINE_CHARS + 1)
        if not line:
            break
        counts["lines"] += 1
        if counts["lines"] > max_records or len(line) > MAX_LINE_CHARS:
            raise InputLimitError("input limit exceeded; narrow the input or raise --max-records")
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            counts["malformed"] += 1
            continue
        if not isinstance(record, dict):
            counts["ignored"] += 1
            continue
        event = record.get("event")
        if event == "research.milestone":
            milestone = record.get("milestone")
            if milestone in MILESTONES:
                milestones[milestone] += 1
                counts["milestones"] += 1
            else:
                counts["ignored"] += 1
            continue
        if event not in ("operation.outcome", "dependency.outcome"):
            counts["ignored"] += 1
            continue
        run = run_label(record.get("runId"))
        if selected_run is not None and run != selected_run:
            counts["filtered"] += 1
            continue
        if (
            event == "operation.outcome"
            and record.get("operation") == "research.first_verified_finding"
        ):
            # Older builds encoded this timestamp marker as a zero-duration operation.
            milestones["research.first_verified_finding"] += 1
            counts["milestones"] += 1
            continue
        if event == "dependency.outcome" and record.get("outcome") == "started":
            counts["lifecycle"] += 1
            continue
        counts["accepted"] += 1
        operation = safe_label(record.get("operation"), OPERATIONS)
        if event == "dependency.outcome":
            provider = safe_label(record.get("provider"), PROVIDERS)
            # Model/search/extract are individual dispatch attempts. Accounting,
            # source, admission, etc. must never inflate completion counts.
            category = "attempt" if operation in {"model", "search", "extract"} else "diagnostic"
            observe(("dependencies", category, provider, operation), record, "durationMs")
        else:
            labels = [operation]
            if operation.startswith("db.statement"):
                labels.extend(
                    (
                        safe_label(record.get("commandCategory"), SQL_COMMANDS),
                        safe_label(record.get("queryFamily"), QUERY_FAMILIES),
                    )
                )
            observe(("operations", *labels), record, "durationMs")
            if operation.startswith("node."):
                observe(("run_nodes", run, operation[5:]), record, "durationMs")
            if operation == "http.request":
                observe(("response_headers",), record, "firstByteMs")

    result: dict[str, Any] = {
        "method": "exact nearest-rank; milliseconds; counts are valid-duration observations",
        "limits": {"max_input_lines": max_records, "max_line_chars": MAX_LINE_CHARS},
        "input": dict(counts),
        "operations": [],
        "dependencies": [],
        "run_nodes": [],
        "response_headers": [],
        "milestones": [
            {"milestone": name, "count": count} for name, count in sorted(milestones.items())
        ],
        "missing_signals": {
            "queue_wait": "No enqueue-to-claim duration in the supported logs.",
        },
        "interpretation": (
            "Do not sum nested operations, dependency attempts, or the run_nodes projection. "
            "Remote timing includes SDK/client/network work, not provider compute alone; "
            "it is contained within total attempt timing (including accounting), not additive. "
            "No attempt deduplication: logs lack unique dispatch IDs. "
            "Headers are not first evidence or first token. Missing records are not zero latency."
        ),
    }
    for key, group in sorted(groups.items()):
        section, *labels = key
        names = {
            "operations": (
                ("operation", "command_category", "query_family")
                if len(labels) == 3
                else ("operation",)
            ),
            "dependencies": ("category", "provider", "operation"),
            "run_nodes": ("run_id", "node"),
            "response_headers": (),
        }[section]
        result[section].append(
            {
                **dict(zip(names, labels, strict=True)),
                "records": group["records"],
                "excluded_durations": group["excluded_durations"],
                "outcomes": dict(group["outcomes"]),
                "record_counts": dict(group["record_counts"]),
                **{bucket: summarize(group[bucket]) for bucket in ("success", "errors", "other")},
                **(
                    {
                        "excluded_remote_durations": group.get("excluded_remote_durations", 0),
                        "attempt_numbers": dict(group["attempt_numbers"]),
                        "retries_scheduled": group["retries_scheduled"],
                        **{
                            f"remote_{bucket}": summarize(group.get(f"remote_{bucket}", []))
                            for bucket in ("success", "errors", "other")
                        },
                    }
                    if key[:2] == ("dependencies", "attempt")
                    else {}
                ),
            }
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", default="-", help="JSONL file, or - for stdin")
    parser.add_argument("--run-id", help="Only include this run UUID")
    parser.add_argument(
        "--max-records",
        type=int,
        default=DEFAULT_MAX_RECORDS,
        help="Maximum input lines (default: 100000); exact, no sampling",
    )
    args = parser.parse_args(argv)
    try:
        source = nullcontext(sys.stdin) if args.file == "-" else open(args.file, encoding="utf-8")
        with source as stream:
            report = analyze(stream, run_id=args.run_id, max_records=args.max_records)
    except (OSError, ValueError, RecursionError):
        # Do not echo paths, malformed records, filter values, or exception text.
        print(
            "latency_report: input unreadable, invalid option value, or input limit exceeded",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
