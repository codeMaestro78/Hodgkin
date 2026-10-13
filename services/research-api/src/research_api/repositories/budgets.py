from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import Budget, ProviderCallReservation, UsageLedger


class BudgetExceededError(RuntimeError):
    pass


class InvalidReservationTransitionError(RuntimeError):
    pass


class BudgetReservationRepository:
    """PostgreSQL-authoritative call and cost reservation transitions."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def reserve(
        self,
        *,
        run_id: uuid.UUID,
        provider: str,
        operation: str,
        request_fingerprint: str,
        estimated_cost_usd: Decimal,
        search_calls: int = 1,
        attempt: int = 1,
    ) -> ProviderCallReservation:
        existing = await self._session.scalar(
            select(ProviderCallReservation).where(
                ProviderCallReservation.tenant_id == self._tenant_id,
                ProviderCallReservation.run_id == run_id,
                ProviderCallReservation.request_fingerprint == request_fingerprint,
                ProviderCallReservation.attempt == attempt,
            )
        )
        if existing is not None:
            return existing

        budget = await self._session.scalar(
            select(Budget)
            .where(Budget.tenant_id == self._tenant_id, Budget.run_id == run_id)
            .with_for_update()
        )
        usage = await self._session.scalar(
            select(UsageLedger)
            .where(UsageLedger.tenant_id == self._tenant_id, UsageLedger.run_id == run_id)
            .with_for_update()
        )
        if budget is None or usage is None:
            raise LookupError("run budget and usage ledger must exist before reservation")

        projected_calls = usage.search_calls + usage.reserved_search_calls + search_calls
        projected_cost = (
            usage.estimated_cost_usd + usage.reserved_estimated_cost_usd + estimated_cost_usd
        )
        if projected_calls > budget.max_search_calls:
            raise BudgetExceededError("search-call budget exhausted")
        if projected_cost > budget.max_estimated_cost_usd:
            raise BudgetExceededError("estimated-cost budget exhausted")

        reservation = ProviderCallReservation(
            tenant_id=self._tenant_id,
            run_id=run_id,
            provider=provider,
            operation=operation,
            request_fingerprint=request_fingerprint,
            attempt=attempt,
            reserved_search_calls=search_calls,
            reserved_estimated_cost_usd=estimated_cost_usd,
            state="reserved",
        )
        usage.reserved_search_calls += search_calls
        usage.reserved_estimated_cost_usd += estimated_cost_usd
        self._session.add(reservation)
        await self._session.flush()
        return reservation

    async def transition(
        self, reservation_id: uuid.UUID, *, new_state: str
    ) -> ProviderCallReservation:
        if new_state not in {"consumed", "released", "uncertain"}:
            raise InvalidReservationTransitionError(f"unsupported terminal state: {new_state}")

        reservation = await self._session.scalar(
            select(ProviderCallReservation)
            .where(
                ProviderCallReservation.tenant_id == self._tenant_id,
                ProviderCallReservation.id == reservation_id,
            )
            .with_for_update()
        )
        if reservation is None:
            raise LookupError("reservation not found for tenant")
        if reservation.state == new_state:
            return reservation
        if reservation.state != "reserved":
            raise InvalidReservationTransitionError(
                f"cannot transition {reservation.state} to {new_state}"
            )

        usage = await self._session.scalar(
            select(UsageLedger)
            .where(
                UsageLedger.tenant_id == self._tenant_id,
                UsageLedger.run_id == reservation.run_id,
            )
            .with_for_update()
        )
        if usage is None:
            raise LookupError("usage ledger not found for tenant")

        if new_state in {"consumed", "released"}:
            usage.reserved_search_calls -= reservation.reserved_search_calls
            usage.reserved_estimated_cost_usd -= reservation.reserved_estimated_cost_usd
        if new_state == "consumed":
            usage.search_calls += reservation.reserved_search_calls
            usage.estimated_cost_usd += reservation.reserved_estimated_cost_usd
        # An uncertain outcome intentionally remains in reserved totals until reconciled.
        reservation.state = new_state
        reservation.terminal_at = datetime.now(UTC)
        await self._session.flush()
        return reservation
