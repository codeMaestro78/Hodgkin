"""Bounded, redacted operational records; never log dependency bodies or prompts."""

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Any

from research_api.config import get_settings

logger = logging.getLogger("research_api.dependencies")
dependency_run: ContextVar[uuid.UUID | None] = ContextVar("dependency_run", default=None)
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


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
        "db.snapshot.collections",
        "auth.verify",
        "http.headers",
    }
    routine |= operation == "http.request" and (
        facts.get("route", "").endswith("/events")
        or (duration_ms < 1000 and facts.get("statusCode", 200) < 400)
    )
    level = (
        logging.ERROR
        if outcome == "failed"
        else logging.WARNING
        if outcome == "insufficient_evidence" or operation == "db.statement.slow"
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
) -> None:
    logger.info(
        json.dumps(
            {
                "event": "dependency.outcome",
                "requestId": request_id.get(),
                "provider": provider,
                "operation": operation,
                "outcome": outcome,
                "attempt": attempt,
                "runId": str(dependency_run.get()) if dependency_run.get() else None,
                "durationMs": round((monotonic() - started) * 1000, 2) if started else None,
                "reason": reason,
                **(
                    {"remoteDurationMs": round(remote_duration_ms, 2)}
                    if remote_duration_ms is not None
                    else {}
                ),
            },
            sort_keys=True,
        )
    )
