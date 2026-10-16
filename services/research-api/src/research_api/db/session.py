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
    if (monotonic() - started) * 1000 >= settings.DATABASE_SLOW_STATEMENT_MS:
        operation_event(
            "db.statement.slow",
            started=started,
            commandCategory=command_category(_statement),
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
