from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import ResearchRun, RunEvent
from research_api.schemas.generated.agent_event import AgentEvent


class EventOutbox:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def append(
        self,
        *,
        run_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
        event_id: uuid.UUID | None = None,
    ) -> RunEvent:
        run = await self._session.scalar(
            select(ResearchRun)
            .where(ResearchRun.tenant_id == self._tenant_id, ResearchRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise LookupError("run not found for tenant")

        run.next_event_sequence += 1
        identity = event_id or uuid.uuid4()
        occurred_at = datetime.now(UTC)
        if event_type == "task.state":
            AgentEvent.model_validate(
                {
                    "schemaVersion": "1.2",
                    "eventId": str(identity),
                    "eventSequence": run.next_event_sequence,
                    "tenantId": str(self._tenant_id),
                    "runId": str(run_id),
                    "timestamp": occurred_at.isoformat(),
                    "type": event_type,
                    **payload,
                }
            )
        event = RunEvent(
            tenant_id=self._tenant_id,
            event_id=identity,
            run_id=run_id,
            event_sequence=run.next_event_sequence,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def replay_after(self, *, run_id: uuid.UUID, sequence: int) -> list[RunEvent]:
        result = await self._session.scalars(
            select(RunEvent)
            .where(
                RunEvent.tenant_id == self._tenant_id,
                RunEvent.run_id == run_id,
                RunEvent.event_sequence > sequence,
            )
            .order_by(RunEvent.event_sequence)
        )
        return list(result)
