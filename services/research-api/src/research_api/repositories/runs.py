from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import Budget, ResearchRun, UsageLedger


@dataclass(frozen=True, slots=True)
class RunBudgetDefaults:
    max_wall_clock_ms: int = 120_000
    max_search_calls: int = 12
    max_browser_sessions: int = 0
    max_reflection_rounds: int = 1
    max_input_tokens: int = 100_000
    max_output_tokens: int = 20_000
    max_estimated_cost_usd: Decimal = Decimal("5.00")


class RunRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        report_requirements: list[str] | None = None,
        idempotency_key: str | None = None,
        budget: RunBudgetDefaults | None = None,
    ) -> ResearchRun:
        run_id = uuid.uuid4()
        defaults = budget or RunBudgetDefaults()
        run = ResearchRun(
            id=run_id,
            tenant_id=self._tenant_id,
            user_id=user_id,
            status="queued",
            original_question=question,
            normalized_question=" ".join(question.split()),
            report_requirements=report_requirements or [],
            thread_id=f"run:{run_id}",
            concurrency_limit=3,
            idempotency_key=idempotency_key,
        )
        self._session.add(run)
        # The models intentionally avoid a large ORM relationship graph. Flush the run so its
        # foreign-key target exists before adding the authoritative budget and usage rows.
        await self._session.flush()
        self._session.add_all(
            [
                Budget(
                    tenant_id=self._tenant_id,
                    run_id=run_id,
                    max_wall_clock_ms=defaults.max_wall_clock_ms,
                    max_search_calls=defaults.max_search_calls,
                    max_browser_sessions=defaults.max_browser_sessions,
                    max_reflection_rounds=defaults.max_reflection_rounds,
                    max_input_tokens=defaults.max_input_tokens,
                    max_output_tokens=defaults.max_output_tokens,
                    max_estimated_cost_usd=defaults.max_estimated_cost_usd,
                ),
                UsageLedger(tenant_id=self._tenant_id, run_id=run_id),
            ]
        )
        await self._session.flush()
        return run

    async def get(self, run_id: uuid.UUID) -> ResearchRun | None:
        return await self._session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == self._tenant_id, ResearchRun.id == run_id
            )
        )

    async def get_by_idempotency_key(
        self, *, user_id: uuid.UUID, idempotency_key: str
    ) -> ResearchRun | None:
        return await self._session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == self._tenant_id,
                ResearchRun.user_id == user_id,
                ResearchRun.idempotency_key == idempotency_key,
            )
        )
