from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import (
    Budget,
    ExtractionSlot,
    ProviderCall,
    ProviderCallReservation,
    UsageLedger,
)
from research_api.research_limits import operation_limit


class BudgetExceededError(RuntimeError):
    pass


class InvalidReservationTransitionError(RuntimeError):
    pass


class ReservationReplayError(RuntimeError):
    """An existing attempt is not permission to repeat a paid operation."""


def nonexecution_proof(
    call: ProviderCall, reservation: ProviderCallReservation
) -> dict[str, object] | None:
    """Accept only private evidence emitted by the server model boundary.

    Provider payloads, caller-supplied receipts/costs and elapsed time are not
    proof. Metadata is trusted only as persisted by the privileged DB writer;
    this is deliberately not an import/upload interface for external evidence.
    """
    proof = (call.provider_usage or {}).get("nonexecution")
    if (
        reservation.provider != "internal"
        or reservation.operation != "model"
        or call.tenant_id != reservation.tenant_id
        or call.run_id != reservation.run_id
        or call.reservation_id != reservation.id
        or call.provider != reservation.provider
        or call.operation != reservation.operation
        or call.request_fingerprint != reservation.request_fingerprint
        or call.outcome != "failed"
        or call.completed_at is None
        or not isinstance(proof, dict)
        or proof.get("version") != "model-nonexecution-v1"
        or proof.get("source") != "model_boundary"
        or proof.get("reason") != "rejected_without_usage"
        or type(proof.get("retryable")) is not bool
    ):
        return None
    if proof.get("kind") == "pre_dispatch":
        if proof.get("statusCode") is not None or proof["retryable"] is not True:
            return None
    elif proof.get("kind") == "http_rejection":
        status = proof.get("statusCode")
        if (
            type(status) is not int
            or status not in {400, 401, 403, 404, 422, 429}
            or proof["retryable"] is not (status == 429)
        ):
            return None
    else:
        return None
    return proof


class BudgetReservationRepository:
    """PostgreSQL-authoritative call and cost reservation transitions."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def _locked_reservation(self, reservation_id: uuid.UUID) -> ProviderCallReservation:
        # Match reserve's budget-first order, including replay settlement, to
        # avoid a reservation/usage lock inversion between recovery and admission.
        run_id = await self._session.scalar(
            select(ProviderCallReservation.run_id).where(
                ProviderCallReservation.tenant_id == self._tenant_id,
                ProviderCallReservation.id == reservation_id,
            )
        )
        if run_id is None:
            raise LookupError("reservation not found for tenant")
        await self._session.scalar(
            select(Budget)
            .where(
                Budget.tenant_id == self._tenant_id,
                Budget.run_id == run_id,
            )
            .with_for_update()
        )
        reservation = await self._session.scalar(
            select(ProviderCallReservation)
            .where(
                ProviderCallReservation.tenant_id == self._tenant_id,
                ProviderCallReservation.id == reservation_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if reservation is None:
            raise LookupError("reservation not found for tenant")
        return reservation

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
        input_tokens: int = 0,
        output_tokens: int = 0,
        require_existing_call: bool = False,
    ) -> ProviderCallReservation:
        if (
            not estimated_cost_usd.is_finite()
            or min(search_calls, input_tokens, output_tokens) < 0
            or estimated_cost_usd < 0
        ):
            raise ValueError("negative reservation")
        if attempt < 1:
            raise ValueError("invalid attempt")
        budget = await self._session.scalar(
            select(Budget)
            .where(Budget.tenant_id == self._tenant_id, Budget.run_id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        usage = await self._session.scalar(
            select(UsageLedger)
            .where(UsageLedger.tenant_id == self._tenant_id, UsageLedger.run_id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if budget is None or usage is None:
            raise LookupError("run budget and usage ledger must exist before reservation")

        # Recheck after the per-run budget lock: concurrent identical requests must
        # see the committed winner, rather than race the reservation constraint.
        existing = await self._session.scalar(
            select(ProviderCallReservation)
            .where(
                ProviderCallReservation.tenant_id == self._tenant_id,
                ProviderCallReservation.run_id == run_id,
                ProviderCallReservation.request_fingerprint == request_fingerprint,
                ProviderCallReservation.attempt == attempt,
            )
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            if existing.provider != provider or existing.operation != operation:
                raise ReservationReplayError("reservation identity conflicts with operation")
            if require_existing_call:
                call_id = await self._session.scalar(
                    select(ProviderCall.id).where(
                        ProviderCall.tenant_id == self._tenant_id,
                        ProviderCall.reservation_id == existing.id,
                    )
                )
                if call_id is None:
                    raise ReservationReplayError("existing reservation has no dispatch evidence")
            return existing

        projected_calls = usage.search_calls + usage.reserved_search_calls + search_calls
        projected_cost = (
            usage.estimated_cost_usd + usage.reserved_estimated_cost_usd + estimated_cost_usd
        )
        if projected_calls > operation_limit(budget):
            raise BudgetExceededError("search-call budget exhausted")
        if projected_cost > budget.max_estimated_cost_usd:
            raise BudgetExceededError("estimated-cost budget exhausted")
        if (
            usage.input_tokens + input_tokens > budget.max_input_tokens
            or usage.output_tokens + output_tokens > budget.max_output_tokens
        ):
            raise BudgetExceededError("model token budget exhausted")

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
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        self._session.add(reservation)
        await self._session.flush()
        return reservation

    async def transition(
        self,
        reservation_id: uuid.UUID,
        *,
        new_state: str,
        actual_cost_usd: Decimal | None = None,
    ) -> ProviderCallReservation:
        if new_state not in {"consumed", "released", "uncertain"}:
            raise InvalidReservationTransitionError(f"unsupported terminal state: {new_state}")

        reservation = await self._locked_reservation(reservation_id)
        if reservation.state == new_state:
            return reservation
        if reservation.state != "reserved":
            raise InvalidReservationTransitionError(
                f"cannot transition {reservation.state} to {new_state}"
            )

        if actual_cost_usd is not None and (not actual_cost_usd.is_finite() or actual_cost_usd < 0):
            raise ValueError("negative settlement")

        usage = await self._session.scalar(
            select(UsageLedger)
            .where(
                UsageLedger.tenant_id == self._tenant_id,
                UsageLedger.run_id == reservation.run_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if usage is None:
            raise LookupError("usage ledger not found for tenant")

        if new_state in {"consumed", "released"}:
            usage.reserved_search_calls -= reservation.reserved_search_calls
            usage.reserved_estimated_cost_usd -= reservation.reserved_estimated_cost_usd
        if new_state == "consumed":
            usage.search_calls += reservation.reserved_search_calls
            usage.estimated_cost_usd += (
                actual_cost_usd
                if actual_cost_usd is not None
                else reservation.reserved_estimated_cost_usd
            )
        call = await self._session.scalar(
            select(ProviderCall).where(
                ProviderCall.tenant_id == self._tenant_id,
                ProviderCall.reservation_id == reservation.id,
            )
        )
        accounting = (
            (call.provider_usage or {}).get("accounting", {})
            if call and reservation.provider == "internal" and reservation.operation == "model"
            else {}
        )
        reserved_input = int(accounting.get("reservedInputTokens", 0))
        reserved_output = int(accounting.get("reservedOutputTokens", 0))
        if new_state == "released":
            usage.input_tokens -= reserved_input
            usage.output_tokens -= reserved_output
        elif new_state == "consumed":
            # Missing usage remains conservative. A larger actual count must also
            # be recorded, not silently clamped down to the input heuristic.
            usage.input_tokens += (
                int(accounting.get("inputTokens", reserved_input)) - reserved_input
            )
            usage.output_tokens += (
                int(accounting.get("outputTokens", reserved_output)) - reserved_output
            )
        # An uncertain outcome intentionally remains in reserved totals until reconciled.
        reservation.state = new_state
        reservation.terminal_at = datetime.now(UTC)
        await self._session.flush()
        return reservation

    async def reconcile_from_receipt(self, reservation_id: uuid.UUID) -> ProviderCallReservation:
        """Settle uncertainty only from an already persisted successful receipt.

        No age-based refunds, redispatch, global scan or cross-tenant access.
        Rejection/timeout evidence without a success receipt stays unresolved.
        """
        reservation = await self._locked_reservation(reservation_id)
        if reservation.state == "consumed":
            return reservation
        if reservation.state not in {"reserved", "uncertain"}:
            raise InvalidReservationTransitionError("only unresolved calls need reconciliation")
        call = await self._session.scalar(
            select(ProviderCall).where(
                ProviderCall.tenant_id == self._tenant_id,
                ProviderCall.reservation_id == reservation_id,
            )
        )
        if (
            call is None
            or call.outcome != "succeeded"
            or call.completed_at is None
            or call.run_id != reservation.run_id
            or call.provider != reservation.provider
            or call.operation != reservation.operation
            or call.request_fingerprint != reservation.request_fingerprint
        ):
            raise InvalidReservationTransitionError("trusted success receipt missing")
        accounting = (
            (call.provider_usage or {}).get("accounting", {})
            if reservation.provider == "internal" and reservation.operation == "model"
            else {}
        )
        cost = accounting.get("costUsd")
        # Reuse the normal atomic settlement while holding the row lock. This
        # temporary state is never committed independently.
        reservation.state = "reserved"
        result = await self.transition(
            reservation_id,
            new_state="consumed",
            actual_cost_usd=Decimal(cost) if cost is not None else None,
        )
        await self._session.execute(
            update(ExtractionSlot)
            .where(
                ExtractionSlot.tenant_id == self._tenant_id,
                ExtractionSlot.reservation_id == reservation_id,
                ExtractionSlot.state == "uncertain",
            )
            .values(state="consumed")
        )
        return result

    async def release_from_nonexecution_proof(
        self, reservation_id: uuid.UUID
    ) -> ProviderCallReservation:
        """Release only from trusted persisted nonexecution, never age or costs."""
        reservation = await self._locked_reservation(reservation_id)
        call = await self._session.scalar(
            select(ProviderCall).where(
                ProviderCall.tenant_id == self._tenant_id,
                ProviderCall.reservation_id == reservation_id,
            )
        )
        if call is None or nonexecution_proof(call, reservation) is None:
            raise InvalidReservationTransitionError("trusted nonexecution proof missing")
        if reservation.state == "released":
            return reservation
        if reservation.state not in {"reserved", "uncertain"}:
            raise InvalidReservationTransitionError("only unresolved calls may be released")
        reservation.state = "reserved"
        result = await self.transition(reservation_id, new_state="released")
        await self._session.execute(
            update(ExtractionSlot)
            .where(
                ExtractionSlot.tenant_id == self._tenant_id,
                ExtractionSlot.reservation_id == reservation_id,
                ExtractionSlot.state.in_(["reserved", "uncertain"]),
            )
            .values(state="released")
        )
        return result
