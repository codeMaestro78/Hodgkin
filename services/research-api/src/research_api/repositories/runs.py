from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.config import get_settings
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
    max_provider_operations: int | None = None
    max_sources: int | None = None


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
        mode: str | None = None,
        mode_policy_version: str | None = None,
        approval_required: bool = False,
    ) -> ResearchRun:
        run, _ = await self.create_once(
            user_id=user_id,
            question=question,
            report_requirements=report_requirements,
            idempotency_key=idempotency_key,
            budget=budget,
            mode=mode,
            mode_policy_version=mode_policy_version,
            approval_required=approval_required,
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
        mode: str | None = None,
        mode_policy_version: str | None = None,
        budget_resolver: Callable[[str | None], RunBudgetDefaults] | None = None,
    ) -> tuple[ResearchRun, bool]:
        """The unique constraint arbitrates concurrent inserts; only its winner dispatches."""
        run_id = uuid.uuid4()
        if mode is not None and mode_policy_version is None:
            from research_api.mode_policy import MODE_POLICY_VERSION

            mode_policy_version = MODE_POLICY_VERSION
        if (mode is None) != (mode_policy_version is None):
            raise ValueError("mode and policy version must both be null or both be explicit")
        prior = (
            await self.get_by_idempotency_key(user_id=user_id, idempotency_key=idempotency_key)
            if idempotency_key is not None
            else None
        )
        if prior is not None and prior.mode != mode:
            raise IdempotencyConflictError("idempotency key belongs to another mode")
        effective_policy_version = prior.mode_policy_version if prior else mode_policy_version
        defaults = (
            budget_resolver(effective_policy_version)
            if budget_resolver
            else budget or RunBudgetDefaults()
        )
        if mode is not None:
            from research_api.mode_policy import resolve_mode_budget, validate_mode_budget

            assert effective_policy_version is not None
            if budget is None and budget_resolver is None:
                defaults = resolve_mode_budget(mode, policy_version=effective_policy_version)
            validate_mode_budget(mode, defaults, policy_version=effective_policy_version)
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
            model_routing=get_settings().model_routing_snapshot(),
            mode=mode,
            mode_policy_version=mode_policy_version,
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
            if run.mode != mode:
                raise IdempotencyConflictError("idempotency key belongs to another mode")
            if budget_resolver:
                defaults = budget_resolver(run.mode_policy_version)
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
                or run.mode != mode
                or (not budget_resolver and run.mode_policy_version != mode_policy_version)
                or stored_budget is None
                or any(
                    getattr(stored_budget, field) != getattr(defaults, field)
                    for field in RunBudgetDefaults.__dataclass_fields__
                )
            ):
                raise IdempotencyConflictError("idempotency key belongs to another request")
            if mode is not None:
                assert run.mode_policy_version is not None
                validate_mode_budget(mode, defaults, policy_version=run.mode_policy_version)
            return run, False
        self._session.add_all(
            [
                Budget(
                    tenant_id=self._tenant_id,
                    run_id=run_id,
                    max_wall_clock_ms=defaults.max_wall_clock_ms,
                    max_search_calls=defaults.max_search_calls,
                    max_provider_operations=defaults.max_provider_operations,
                    max_sources=defaults.max_sources,
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
