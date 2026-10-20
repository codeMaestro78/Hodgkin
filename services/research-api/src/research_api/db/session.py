import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from research_api.config import get_settings
from research_api.events.wakeups import event_wakeups
from research_api.runtime_context import LeaseLostError, current_job
from research_api.telemetry import operation_event

settings = get_settings()
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    pool_pre_ping=True,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


def command_category(statement: str | None) -> str:
    """Only allowlisted SQL verbs; never expose SQL text, identifiers or literals."""
    first = (statement or "").lstrip().split(None, 1)
    verb = first[0].upper() if first else ""
    return verb if verb in {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "SET"} else "OTHER"


def query_family(statement: str | None) -> str:
    """Static, non-sensitive table-family labels; never expose SQL or parameters."""
    sql = statement or ""
    command = command_category(sql)
    if command not in {"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"}:
        return "other"
    for table, label in (
        ("runtime_jobs", "runtime_job"),
        ("research_runs", "run"),
        ("sub_question_attempts", "sub_question_attempt"),
        ("sub_questions", "sub_question"),
        ("node_executions", "node_execution"),
        ("provider_calls", "provider_call"),
        ("run_events", "run_event"),
        ("evidence_claims", "evidence_claim"),
        ("citations", "citation"),
        ("sources", "source"),
        ("reports", "report"),
        ("research_assessments", "assessment"),
        ("research_plans", "research_plan"),
        ("plan_approvals", "plan_approval"),
        ("budgets", "budget"),
        ("usage_ledger", "usage_ledger"),
    ):
        operation = {
            "INSERT": "INTO",
            "UPDATE": "UPDATE",
            "DELETE": "FROM",
        }.get(command)
        matcher = (
            rf"\b{operation}\s+\"?{table}\"?\b"
            if operation
            else (rf"\b(?:FROM|JOIN)\s+\"?{table}\"?\b")
        )
        if re.search(matcher, sql, re.IGNORECASE):
            if re.search(r"\bFOR\s+UPDATE\b", sql, re.IGNORECASE):
                return f"{label}_exclusive"
            if re.search(r"\bFOR\s+SHARE\b", sql, re.IGNORECASE):
                return f"{label}_shared"
            return label
    return "other"


slow_query_family = query_family


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def statement_start(
    _conn: Any,
    _cursor: Any,
    _statement: str,
    _parameters: Any,
    context: Any,
    _executemany: bool,
) -> None:
    context.research_started = monotonic()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def statement_finish(
    _conn: Any,
    _cursor: Any,
    _statement: str,
    _parameters: Any,
    context: Any,
    _executemany: bool,
) -> None:
    started = context.research_started
    duration_ms = (monotonic() - started) * 1000
    if duration_ms >= settings.DATABASE_SLOW_STATEMENT_MS:
        operation_event(
            "db.statement.slow",
            started=started,
            commandCategory=command_category(_statement),
            queryFamily=slow_query_family(_statement),
            executemany=_executemany,
        )
    elif settings.DATABASE_QUERY_TIMING_ENABLED:
        operation_event(
            "db.statement.timing",
            started=started,
            commandCategory=command_category(_statement),
            queryFamily=query_family(_statement),
            executemany=_executemany,
        )


@event.listens_for(engine.sync_engine, "handle_error")
def statement_failure(context: Any) -> None:
    execution = context.execution_context
    started = getattr(execution, "research_started", monotonic())
    operation_event(
        "db.statement",
        started=started,
        outcome="failed",
        error=context.sqlalchemy_exception or context.original_exception,
        commandCategory=command_category(getattr(context, "statement", None)),
        queryFamily=query_family(getattr(context, "statement", None)),
    )


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """Open a transaction whose PostgreSQL RLS context is fixed to one tenant."""
    started = monotonic()
    setup_ms = None
    acquire_ms = None
    try:
        async with session_factory() as session:
            async with session.begin():
                # This checks out the same connection the first execute would
                # acquire. No extra SQL; includes queue wait, connect and pre-ping.
                acquired = monotonic()
                await session.connection()
                acquire_ms = round((monotonic() - acquired) * 1000, 2)
                operation_event("db.connection.acquire", started=acquired)
                await _tenant_transaction(session, tenant_id)
                setup_ms = round((monotonic() - started) * 1000, 2)
                yield session
            # Commit has succeeded and the connection is released. Hints contain
            # only routing IDs, never event bodies; Redis is not awaited here.
            committed = {
                (row.tenant_id, row.run_id)
                for row in session.info.pop("outbox_wakeups", [])
                if inspect(row).persistent
            }
            for tenant, run in committed:
                event_wakeups.committed(tenant, run)
    except BaseException as exc:
        operation_event(
            "db.transaction",
            started=started,
            outcome="failed",
            error=exc,
            setupMs=setup_ms,
            acquireMs=acquire_ms,
        )
        raise
    else:
        operation_event("db.transaction", started=started, setupMs=setup_ms, acquireMs=acquire_ms)


async def set_user_context(session: AsyncSession, user_id: str) -> None:
    """Bind the authenticated owner for user-scoped RLS policies in this transaction."""
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": user_id},
    )


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Open a narrowly scoped transaction for system-owned, non-tenant records.

    Use only for tables whose ownership is intentionally global (such as the
    Stripe event inbox); request payloads must never choose a tenant here.
    """
    async with session_factory() as session:
        async with session.begin():
            await session.connection()
            yield session


async def _tenant_transaction(session: AsyncSession, tenant_id: str) -> None:
    """Set up tenant isolation and optional execution fencing before yielding."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )
    fence = current_job.get()
    if fence is not None:
        if str(fence.tenant_id) != tenant_id:
            raise LeaseLostError("cross-tenant execution context")
        alive = await session.scalar(
            text("""
                SELECT run_id FROM runtime_jobs
                WHERE tenant_id=:tenant AND run_id=:run AND owner_id=:owner
                    AND generation=:generation AND state='running'
                    AND lease_expires_at > clock_timestamp()
                FOR SHARE
            """),
            {
                "tenant": fence.tenant_id,
                "run": fence.run_id,
                "owner": fence.owner_id,
                "generation": fence.generation,
            },
        )
        if alive is None:
            raise LeaseLostError("execution lease is no longer owned")
