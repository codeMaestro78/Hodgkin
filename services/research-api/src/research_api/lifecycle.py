"""One lock and one guard for run writes; terminal state and cancel intent are monotonic."""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import ResearchRun

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})


async def lock_run(session: AsyncSession, tenant: uuid.UUID, run: uuid.UUID) -> ResearchRun:
    row = await session.scalar(
        select(ResearchRun)
        .where(ResearchRun.tenant_id == tenant, ResearchRun.id == run)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise LookupError("research run not found")
    return row


def ensure_active(run: ResearchRun) -> None:
    """Must be called under lock_run in the same transaction as the write."""
    if run.status in TERMINAL_RUN_STATUSES or run.cancellation_requested_at is not None:
        raise asyncio.CancelledError
