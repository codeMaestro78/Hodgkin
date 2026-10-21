"""Append-only purchased-credit fulfillment and per-run lot accounting."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.billing.ledger import (
    BillingConfigurationUnavailable,
    BillingReservationConflict,
    BillingSettlementConflict,
    _lock_account,
)
from research_api.db.models import (
    BillingCreditEntry,
    BillingCreditPurchase,
    ResearchRun,
)


async def credit_balance(
    session: AsyncSession, *, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> tuple[int, int]:
    available, reserved = (
        await session.execute(
            select(
                func.coalesce(func.sum(BillingCreditEntry.available_delta), 0),
                func.coalesce(func.sum(BillingCreditEntry.reserved_delta), 0),
            ).where(
                BillingCreditEntry.tenant_id == tenant_id,
                BillingCreditEntry.billing_account_id == account_id,
            )
        )
    ).one()
    if available < 0 or reserved < 0:
        raise BillingConfigurationUnavailable("credit wallet ledger is inconsistent")
    return int(available), int(reserved)


async def wallet_frozen(
    session: AsyncSession, *, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> bool:
    return bool(
        await session.scalar(
            select(BillingCreditPurchase.id)
            .where(
                BillingCreditPurchase.tenant_id == tenant_id,
                BillingCreditPurchase.billing_account_id == account_id,
                BillingCreditPurchase.state.in_(("disputed", "reconciliation_required")),
            )
            .limit(1)
        )
    )


async def reserve_credits(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    run_id: uuid.UUID,
    units: int,
    request_key: str,
) -> BillingCreditEntry:
    """Reserve oldest paid lots under the shared owner lock held by admission."""
    if units <= 0:
        raise ValueError("credit reservation must be positive")
    if await wallet_frozen(session, tenant_id=tenant_id, account_id=account_id):
        raise BillingConfigurationUnavailable("credit wallet requires reconciliation")
    lots = (
        await session.scalars(
            select(BillingCreditPurchase)
            .where(
                BillingCreditPurchase.tenant_id == tenant_id,
                BillingCreditPurchase.billing_account_id == account_id,
                BillingCreditPurchase.state == "paid",
            )
            .order_by(BillingCreditPurchase.created_at, BillingCreditPurchase.id)
        )
    ).all()
    remaining = units
    first: BillingCreditEntry | None = None
    for lot in lots:
        available = await session.scalar(
            select(func.coalesce(func.sum(BillingCreditEntry.available_delta), 0)).where(
                BillingCreditEntry.tenant_id == tenant_id,
                BillingCreditEntry.billing_account_id == account_id,
                BillingCreditEntry.purchase_id == lot.id,
            )
        )
        take = min(remaining, int(available or 0))
        if take <= 0:
            continue
        entry = BillingCreditEntry(
            tenant_id=tenant_id,
            billing_account_id=account_id,
            purchase_id=lot.id,
            run_id=run_id,
            entry_type="reservation",
            available_delta=-take,
            reserved_delta=take,
            idempotency_key=(
                f"credit-reserve:{hashlib.sha256(request_key.encode()).hexdigest()}:{run_id}:{lot.id}"
            ),
        )
        session.add(entry)
        first = first or entry
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise BillingReservationConflict("credit wallet balance changed during admission")
    await session.flush()
    assert first is not None
    return first


async def settle_credits(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    outcome: str,
) -> None:
    account = await _lock_account(session, tenant_id=tenant_id, user_id=user_id, create=False)
    if account is None:
        raise BillingReservationConflict("credit account missing")
    run_status = await session.scalar(
        select(ResearchRun.status).where(
            ResearchRun.tenant_id == tenant_id,
            ResearchRun.user_id == user_id,
            ResearchRun.id == run_id,
        )
    )
    if run_status not in ("completed", "failed", "cancelled"):
        raise BillingReservationConflict("only terminal runs may settle credits")
    reservations = (
        await session.scalars(
            select(BillingCreditEntry).where(
                BillingCreditEntry.tenant_id == tenant_id,
                BillingCreditEntry.billing_account_id == account.id,
                BillingCreditEntry.run_id == run_id,
                BillingCreditEntry.entry_type == "reservation",
            )
        )
    ).all()
    entry_type = "consumption" if outcome == "consume" else "release"
    for reservation in reservations:
        prior = await session.scalar(
            select(BillingCreditEntry).where(
                BillingCreditEntry.tenant_id == tenant_id,
                BillingCreditEntry.run_id == run_id,
                BillingCreditEntry.purchase_id == reservation.purchase_id,
                BillingCreditEntry.entry_type.in_(("consumption", "release")),
            )
        )
        if prior is not None:
            if prior.entry_type != entry_type:
                raise BillingSettlementConflict("credit settlement outcome changed")
            continue
        session.add(
            BillingCreditEntry(
                tenant_id=tenant_id,
                billing_account_id=account.id,
                purchase_id=reservation.purchase_id,
                run_id=run_id,
                entry_type=entry_type,
                available_delta=reservation.reserved_delta if outcome == "release" else 0,
                reserved_delta=-reservation.reserved_delta,
                idempotency_key=f"credit-{entry_type}:{run_id}:{reservation.purchase_id}",
            )
        )
    await session.flush()
