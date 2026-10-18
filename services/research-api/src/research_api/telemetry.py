"""Bounded, redacted operational records; never log dependency bodies or prompts."""

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from research_api.config import get_settings

logger = logging.getLogger("research_api.dependencies")
dependency_run: ContextVar[uuid.UUID | None] = ContextVar("dependency_run", default=None)
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
MILESTONES = {"research.first_verified_finding"}


def error_facts(error: BaseException) -> list[dict[str, object]]:
    """Bounded leaf facts, not exception messages/SQL parameters/traceback locals."""
    leaves: list[dict[str, object]] = []
    pending = [error]
    while pending and len(leaves) < 8:
        item = pending.pop()
        if isinstance(item, BaseExceptionGroup):
            pending.extend(item.exceptions[:8])
            continue
        original = getattr(item, "orig", item)
        code = getattr(original, "sqlstate", None)
        fact: dict[str, object] = {"type": type(item).__name__}
        if isinstance(code, str) and len(code) == 5 and code.isalnum():
            fact["sqlstate"] = code
        frame = item.__traceback__
        while frame:
            module = frame.tb_frame.f_globals.get("__name__", "")
            if isinstance(module, str) and module.startswith("research_api."):
                fact["location"] = f"{module}:{frame.tb_lineno}"
            frame = frame.tb_next
        leaves.append(fact)
    return leaves


def operation_event(
    operation: str,
    *,
    started: float,
    outcome: str = "succeeded",
    error: BaseException | None = None,
    **facts: Any,
) -> None:
    """Callers supply only static operations and non-sensitive numeric facts."""
    duration_ms = round((monotonic() - started) * 1000, 2)
    routine = operation in {
        "db.transaction",
        "db.connection.acquire",
        "db.snapshot.collections",
        "db.statement.timing",
        "auth.verify",
        "auth.verify.coalesced",
        "http.headers",
    }
    routine |= operation == "http.request" and (
        facts.get("route", "").endswith("/events")
        or (duration_ms < 1000 and facts.get("statusCode", 200) < 400)
    )
    slow_snapshot = (
        operation == "db.snapshot.collections"
        and duration_ms >= get_settings().DATABASE_SLOW_STATEMENT_MS
    )
    if slow_snapshot:
        routine = False
    level = (
        logging.ERROR
        if outcome == "failed"
        else logging.WARNING
        if outcome in {"insufficient_evidence", "rejected"}
        or operation == "db.statement.slow"
        or slow_snapshot
        or (operation == "db.connection.acquire" and duration_ms >= 1000)
        else logging.DEBUG
        if routine
        else logging.INFO
    )
    if not logger.isEnabledFor(level):
        return
    logger.log(
        level,
        json.dumps(
            {
                "event": "operation.outcome",
                "operation": operation,
                "recordedAt": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "requestId": request_id.get(),
                "runId": str(dependency_run.get()) if dependency_run.get() else None,
                "durationMs": duration_ms,
                "outcome": outcome,
                "errors": error_facts(error) if error else [],
                **facts,
            },
            sort_keys=True,
        ),
    )


def milestone_event(milestone: str, *, verified_finding_count: int) -> None:
    """Record a timestamped lifecycle marker without inventing a duration sample."""
    if (
        milestone not in MILESTONES
        or type(verified_finding_count) is not int
        or not 1 <= verified_finding_count <= 40
    ):
        raise ValueError("unsupported research milestone")
    if not logger.isEnabledFor(logging.INFO):
        return
    logger.info(
        json.dumps(
            {
                "event": "research.milestone",
                "milestone": milestone,
                "recordedAt": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "requestId": request_id.get(),
                "runId": str(dependency_run.get()) if dependency_run.get() else None,
                "verifiedFindingCount": verified_finding_count,
            },
            sort_keys=True,
        )
    )


@contextmanager
def dependency_logging() -> Iterator[None]:
    """Emit JSON under Uvicorn without changing SDK/root logging or logging bodies."""
    previous = logger.level, logger.handlers[:], logger.propagate
    logger.setLevel(getattr(logging, get_settings().RESEARCH_LOG_LEVEL))
    logger.handlers = logging.getLogger("uvicorn.error").handlers[:] or [logging.StreamHandler()]
    logger.propagate = False
    try:
        yield
    finally:
        logger.setLevel(previous[0])
        logger.handlers, logger.propagate = previous[1], previous[2]


def dependency_event(
    *,
    provider: str,
    operation: str,
    outcome: str,
    attempt: int = 1,
    started: float | None = None,
    reason: str | None = None,
    remote_duration_ms: float | None = None,
    model: str | None = None,
    role: str | None = None,
    max_attempts: int | None = None,
    retry_scheduled: bool | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Record a dependency boundary without request/response content or credentials."""
    if role is not None and role not in {"planner", "writer", "claim_review"}:
        raise ValueError("unsupported telemetry model role")
    if model is not None and (not model.strip() or len(model) > 200):
        raise ValueError("invalid telemetry model name")
    if any(
        value is not None and (type(value) is not int or value < 0)
        for value in (input_tokens, output_tokens)
    ):
        raise ValueError("invalid telemetry token count")
    logger.info(
        json.dumps(
            {
                "event": "dependency.outcome",
                "requestId": request_id.get(),
                "provider": provider,
                "operation": operation,
                "recordedAt": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "outcome": outcome,
                "attempt": attempt,
                "runId": str(dependency_run.get()) if dependency_run.get() else None,
                "durationMs": (
                    round((monotonic() - started) * 1000, 2)
                    if started is not None and outcome != "started"
                    else None
                ),
                "reason": reason,
                **({"model": model} if model is not None else {}),
                **({"role": role} if role is not None else {}),
                **({"maxAttempts": max_attempts} if max_attempts is not None else {}),
                **({"retryScheduled": retry_scheduled} if retry_scheduled is not None else {}),
                **({"inputTokens": input_tokens} if input_tokens is not None else {}),
                **({"outputTokens": output_tokens} if output_tokens is not None else {}),
                **(
                    {"remoteDurationMs": round(remote_duration_ms, 2)}
                    if remote_duration_ms is not None
                    else {}
                ),
            },
            sort_keys=True,
        )
    )
