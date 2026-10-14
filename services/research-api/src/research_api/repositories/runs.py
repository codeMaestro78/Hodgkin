from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import Budget, ResearchRun, UsageLedger


class IdempotencyConflictError(ValueError):
    """A submission key was already committed with a different request."""


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
        run, _ = await self.create_once(
            user_id=user_id,
            question=question,
            report_requirements=report_requirements,
            idempotency_key=idempotency_key,
            budget=budget,
        )
        return run

    async def create_once(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        report_requirements: list[str] | None = None,
        idempotency_key: str | None = None,
        budget: RunBudgetDefaults | None = None,
        parent_report_id: uuid.UUID | None = None,
        approval_required: bool = False,
    ) -> tuple[ResearchRun, bool]:
        """The unique constraint arbitrates concurrent inserts; only its winner dispatches."""
        run_id = uuid.uuid4()
        defaults = budget or RunBudgetDefaults()
        statement = insert(ResearchRun).values(
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
            parent_report_id=parent_report_id,
            approval_required=approval_required,
        )
        run = await self._session.scalar(
            statement.on_conflict_do_nothing(
                index_elements=[
                    ResearchRun.tenant_id,
                    ResearchRun.user_id,
                    ResearchRun.idempotency_key,
                ]
            ).returning(ResearchRun)
        )
        if run is None:
            if idempotency_key is None:
                raise RuntimeError("run insert did not return a row")
            run = await self.get_by_idempotency_key(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if run is None:
                raise RuntimeError("idempotent winner unavailable")
            stored_budget = await self._session.scalar(
                select(Budget).where(
                    Budget.tenant_id == self._tenant_id,
                    Budget.run_id == run.id,
                )
            )
            if (
                run.original_question != question
                or run.report_requirements != (report_requirements or [])
                or run.parent_report_id != parent_report_id
                or run.approval_required != approval_required
                or stored_budget is None
                or any(
                    getattr(stored_budget, field) != getattr(defaults, field)
                    for field in RunBudgetDefaults.__dataclass_fields__
                )
            ):
                raise IdempotencyConflictError("idempotency key belongs to another request")
            return run, False
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
        return run, True

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
