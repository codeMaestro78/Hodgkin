"""Bounded, redacted operational records; never log dependency bodies or prompts."""

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache
from time import monotonic
from typing import Any

from research_api.config import get_settings

logger = logging.getLogger("research_api.dependencies")
PROCESS_INSTANCE_ID = str(uuid.uuid4())
dependency_run: ContextVar[uuid.UUID | None] = ContextVar("dependency_run", default=None)
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
MILESTONES = {"research.first_verified_finding"}


def _safe_trace_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Allow only explicit, bounded correlation fields into LangSmith."""
    safe: dict[str, Any] = {}
    run_id_value = metadata.get("run_id")
    if isinstance(run_id_value, str):
        try:
            safe["run_id"] = str(uuid.UUID(run_id_value))
        except ValueError:
            pass
    graph_version = metadata.get("graph_version")
    if (
        isinstance(graph_version, str)
        and bool(graph_version)
        and len(graph_version) <= 100
        and graph_version.replace("-", "").replace("_", "").replace(".", "").isalnum()
    ):
        safe["graph_version"] = graph_version
    mode = metadata.get("mode")
    if isinstance(mode, str) and mode in {"focused", "balanced", "deep", "legacy"}:
        safe["mode"] = mode
    return safe


def _redact_trace_error(value: dict[str, Any]) -> dict[str, str]:
    """Do not upload provider exception text, which may contain request data."""
    return {"error": "exception details redacted"} if "error" in value else {}


@contextmanager
def _disabled_trace_scope(factory: Any, *, started: float) -> Iterator[None]:
    """Suppress environment-enabled tracing if opt-in setup did not succeed."""
    try:
        context = factory(enabled=False)
        context.__enter__()
    except Exception as exc:
        operation_event("langsmith.trace.suppress", started=started, outcome="failed", error=exc)
        yield
        return
    try:
        yield
    except BaseException as body_error:
        try:
            context.__exit__(type(body_error), body_error, body_error.__traceback__)
        except Exception as trace_error:
            operation_event(
                "langsmith.trace.suppress", started=started, outcome="failed", error=trace_error
            )
        raise
    else:
        try:
            context.__exit__(None, None, None)
        except Exception as exc:
            operation_event(
                "langsmith.trace.suppress", started=started, outcome="failed", error=exc
            )


@lru_cache(maxsize=4)
def _langsmith_client(api_key: str, endpoint: str | None) -> Any:
    """Create one privacy-configured client per process/configuration."""
    from langsmith import Client

    return Client(
        api_key=api_key,
        api_url=endpoint,
        hide_inputs=True,
        hide_outputs=True,
        hide_metadata=_safe_trace_metadata,
        anonymizer=_redact_trace_error,
        omit_traced_runtime_info=True,
    )


@contextmanager
def langsmith_trace_context(
    settings: Any,
    *,
    run_id: uuid.UUID,
    graph_version: str,
    mode: str | None,
) -> Iterator[None]:
    """Enable privacy-minimized LangGraph tracing only when explicitly configured.

    LangSmith is diagnostic only: initialization and export failures are logged
    without run contents and must not change the research result.
    """
    started = monotonic()
    trace_factory: Any | None = None
    try:
        from langsmith.run_helpers import tracing_context
        trace_factory = tracing_context

        tracing_enabled = (
            settings.LANGSMITH_TRACING_ENABLED and settings.LANGSMITH_API_KEY is not None
        )
        if tracing_enabled:
            client = _langsmith_client(
                settings.LANGSMITH_API_KEY.get_secret_value(), settings.LANGSMITH_ENDPOINT
            )
            metadata = {
                "run_id": str(run_id),
                "graph_version": graph_version[:100],
                "mode": mode if mode in {"focused", "balanced", "deep"} else "legacy",
            }
            trace_context = tracing_context(
                client=client,
                enabled=True,
                project_name=settings.LANGSMITH_PROJECT,
                metadata=metadata,
            )
        else:
            trace_context = tracing_context(enabled=False)
            if settings.LANGSMITH_TRACING_ENABLED:
                operation_event(
                    "langsmith.trace.setup",
                    started=started,
                    outcome="rejected",
                    reason="missing_api_key",
                )
        trace_context.__enter__()
    except Exception as exc:
        operation_event(
            "langsmith.trace.setup", started=started, outcome="failed", error=exc
        )
        if trace_factory is None:
            yield
        else:
            with _disabled_trace_scope(trace_factory, started=started):
                yield
        return

    try:
        yield
    except BaseException as exc:
        try:
            trace_context.__exit__(type(exc), exc, exc.__traceback__)
        except Exception as trace_error:
            operation_event(
                "langsmith.trace.export", started=started, outcome="failed", error=trace_error
            )
        raise
    else:
        try:
            trace_context.__exit__(None, None, None)
        except Exception as exc:
            operation_event(
                "langsmith.trace.export", started=started, outcome="failed", error=exc
            )


def dispatcher_slot_event(
    *,
    worker_instance_id: uuid.UUID,
    run_id: uuid.UUID,
    phase: str,
    active_workers: int,
    concurrency_limit: int,
) -> None:
    """Emit one replica-local worker-slot transition for log aggregation."""
    operation_event(
        "dispatcher.worker.slot",
        started=monotonic(),
        phase=phase,
        workerInstanceId=str(worker_instance_id),
        runId=str(run_id),
        activeWorkers=max(0, active_workers),
        concurrencyLimit=max(1, concurrency_limit),
    )


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
                "processInstanceId": PROCESS_INSTANCE_ID,
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
                "processInstanceId": PROCESS_INSTANCE_ID,
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
