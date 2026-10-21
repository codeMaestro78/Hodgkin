"""Policy-based, replay-safe settlement inside each terminal run transaction."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.billing.ledger import settle_units
from research_api.db.models import (
    BillingCreditEntry,
    BillingUnitEntry,
    ProviderCall,
    ProviderCallReservation,
    ResearchRun,
)


def settlement_outcome(
    status: str, *, unresolved_provider_call: bool, provider_dispatched: bool
) -> Literal["consume", "release"] | None:
    if status not in {"completed", "failed", "cancelled"} or unresolved_provider_call:
        return None
    if status == "completed":
        return "consume"
    if status == "failed":
        return "release"
    return "consume" if provider_dispatched else "release"


async def settle_terminal_run(session: AsyncSession, run: ResearchRun) -> bool:
    """Settle a run reservation atomically with terminal status, preserving uncertainty.

    Complete reports consume. Definite platform failures release. Cancellation
    releases only before any provider dispatch; cancellation after dispatch
    consumes. Any unresolved provider-call reservation keeps units held until
    its own durable accounting reconciliation has resolved the ambiguity.
    """
    if run.status not in {"completed", "failed", "cancelled"}:
        return False
    reservation = await session.scalar(
        select(BillingUnitEntry).where(
            BillingUnitEntry.tenant_id == run.tenant_id,
            BillingUnitEntry.run_id == run.id,
            BillingUnitEntry.entry_type == "reservation",
        )
    )
    credit_reservation = None
    if await session.scalar(
        text("SELECT to_regclass('public.billing_credit_entries') IS NOT NULL")
    ):
        credit_reservation = await session.scalar(
            select(BillingCreditEntry.id).where(
                BillingCreditEntry.tenant_id == run.tenant_id,
                BillingCreditEntry.run_id == run.id,
                BillingCreditEntry.entry_type == "reservation",
            )
        )
    if reservation is None and credit_reservation is None:
        return False
    unresolved = await session.scalar(
        select(
            exists().where(
                ProviderCallReservation.tenant_id == run.tenant_id,
                ProviderCallReservation.run_id == run.id,
                ProviderCallReservation.state.in_(("reserved", "uncertain")),
            )
        )
    )
    if unresolved:
        return False
    dispatched = False
    if run.status == "cancelled":
        dispatched = bool(
            await session.scalar(
                select(
                    exists().where(
                        ProviderCall.tenant_id == run.tenant_id,
                        ProviderCall.run_id == run.id,
                    )
                )
            )
        )
    outcome = settlement_outcome(
        run.status,
        unresolved_provider_call=bool(unresolved),
        provider_dispatched=bool(dispatched),
    )
    if outcome is None:
        return False
    if reservation is not None:
        await settle_units(
            session,
            tenant_id=run.tenant_id,
            user_id=run.user_id,
            run_id=run.id,
            outcome=outcome,
            idempotency_key=f"run-settlement-v1:{run.id}",
        )
    if credit_reservation is not None:
        from research_api.billing.credits import settle_credits

        await settle_credits(
            session,
            tenant_id=run.tenant_id,
            user_id=run.user_id,
            run_id=run.id,
            outcome=outcome,
        )
    return True
