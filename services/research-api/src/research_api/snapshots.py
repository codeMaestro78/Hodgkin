"""Bounded collections for an already authorized run in an existing tenant transaction."""

from contextlib import AsyncExitStack
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import (
    NodeExecution,
    ProviderCall,
    Report,
    ResearchGap,
    RunEvent,
    Source,
    SubQuestion,
    SubQuestionAttempt,
)
from research_api.telemetry import operation_event


@dataclass(frozen=True)
class SnapshotCollections:
    """Transient ORM records for reading only; never add these to a session."""

    sources: list[Source]
    questions: list[SubQuestion]
    nodes: list[NodeExecution]
    attempts: list[SubQuestionAttempt]
    gaps: list[ResearchGap]
    versions: list[Report]
    calls: list[ProviderCall]
    events: list[RunEvent]


# Static SQL only. Keep ordering and bounds aligned with the API projection.
_QUERIES = (
    "SELECT * FROM sources WHERE tenant_id = %s AND run_id = %s "
    "ORDER BY retrieved_at DESC LIMIT 200",
    "SELECT * FROM sub_questions WHERE tenant_id = %s AND run_id = %s ORDER BY created_at LIMIT 16",
    "SELECT * FROM node_executions WHERE tenant_id = %s AND run_id = %s "
    "ORDER BY started_at LIMIT 60",
    "SELECT * FROM sub_question_attempts WHERE tenant_id = %s AND run_id = %s "
    "ORDER BY started_at LIMIT 32",
    "SELECT * FROM gaps WHERE tenant_id = %s AND run_id = %s ORDER BY created_at LIMIT 40",
    "SELECT * FROM reports WHERE tenant_id = %s AND run_id = %s ORDER BY version DESC LIMIT 20",
    "SELECT * FROM provider_calls WHERE tenant_id = %s AND run_id = %s "
    "ORDER BY started_at LIMIT 100",
    "SELECT * FROM run_events WHERE tenant_id = %s AND run_id = %s "
    "ORDER BY event_sequence DESC LIMIT 40",
)


async def load_collections(
    session: AsyncSession, tenant_id: UUID, run_id: UUID
) -> SnapshotCollections:
    """Load after API authorization, with exclusive use of this AsyncSession.

    Reuse SQLAlchemy's driver and RLS/transaction context. No autoflush, writes,
    commit, rollback, independent connection, or identity-map changes occur.
    Like sequential SELECTs at READ COMMITTED, this is not a repeatable-read
    snapshot. Report-specific gap filtering remains the caller's responsibility.
    A driver error propagates so the owning transaction can roll back.
    """
    started = monotonic()
    try:
        connection = await session.connection()
        raw = await connection.get_raw_connection()
        driver = raw.driver_connection
        if not isinstance(driver, AsyncConnection):
            raise TypeError("snapshot collections require psycopg AsyncConnection")
        if driver.info.transaction_status != TransactionStatus.INTRANS:
            raise RuntimeError("snapshot collections require an existing database transaction")
        async with AsyncExitStack() as stack:
            cursors = [
                await stack.enter_async_context(driver.cursor(row_factory=dict_row))
                for _ in _QUERIES
            ]
            async with driver.pipeline():
                for cursor, query in zip(cursors, _QUERIES, strict=True):
                    await cursor.execute(query, (tenant_id, run_id))
            # Fetch only after pipeline exit synchronizes every queued SELECT.
            rows = [await cursor.fetchall() for cursor in cursors]
            result = SnapshotCollections(
                sources=[Source(**row) for row in rows[0]],
                questions=[SubQuestion(**row) for row in rows[1]],
                nodes=[NodeExecution(**row) for row in rows[2]],
                attempts=[SubQuestionAttempt(**row) for row in rows[3]],
                gaps=[ResearchGap(**row) for row in rows[4]],
                versions=[Report(**row) for row in rows[5]],
                calls=[ProviderCall(**row) for row in rows[6]],
                events=[RunEvent(**row) for row in rows[7]],
            )
    except BaseException as exc:
        operation_event("db.snapshot.collections", started=started, outcome="failed", error=exc)
        raise
    operation_event("db.snapshot.collections", started=started)
    return result
