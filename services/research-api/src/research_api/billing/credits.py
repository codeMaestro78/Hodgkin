"""Append-only purchased-credit fulfillment and per-run lot accounting."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.billing.ledger import (
    BillingConfigurationUnavailable,
    BillingReservationConflict,
    BillingSettlementConflict,
    _lock_account,
)
from research_api.billing.stripe import stripe_request
from research_api.config import Settings
from research_api.db.models import (
    BillingAccount,
    BillingCreditEntry,
    BillingCreditPurchase,
    ResearchRun,
    StripeCustomerLink,
)


async def _bind_purchase_owner(session: AsyncSession, purchase: BillingCreditPurchase) -> None:
    """Bind immutable owner IDs before reading account rows protected by RLS."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :value, true)"),
        {"value": str(purchase.tenant_id)},
    )
    await session.execute(
        text("SELECT set_config('app.user_id', :value, true)"),
        {"value": str(purchase.user_id)},
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


async def apply_credit_checkout(
    session: AsyncSession,
    *,
    event_type: str,
    obj: dict[str, object],
    livemode: bool,
    expected_livemode: bool,
) -> str:
    """Grant exactly once for a paid, owner-matched Checkout Session."""
    if obj.get("mode") != "payment":
        return "reconciliation_required"
    session_id = obj.get("id")
    metadata = obj.get("metadata")
    if not isinstance(metadata, Mapping):
        return "reconciliation_required"
    purchase_id = metadata.get("purchase_id")
    try:
        parsed_id = uuid.UUID(str(purchase_id))
    except (ValueError, TypeError):
        return "reconciliation_required"
    purchase = await session.scalar(
        select(BillingCreditPurchase).where(BillingCreditPurchase.id == parsed_id)
    )
    if purchase is None:
        return "reconciliation_required"
    await _bind_purchase_owner(session, purchase)
    account = await session.scalar(
        select(BillingAccount).where(
            BillingAccount.id == purchase.billing_account_id,
            BillingAccount.tenant_id == purchase.tenant_id,
            BillingAccount.user_id == purchase.user_id,
        )
    )
    if account is None:
        return "reconciliation_required"
    await _lock_account(
        session, tenant_id=purchase.tenant_id, user_id=account.user_id, create=False
    )
    customer = await session.scalar(
        select(StripeCustomerLink.stripe_customer_id).where(
            StripeCustomerLink.tenant_id == purchase.tenant_id,
            StripeCustomerLink.user_id == account.user_id,
        )
    )
    if (
        purchase.stripe_checkout_session_id != session_id
        or obj.get("client_reference_id") != str(purchase.id)
        or obj.get("customer") != customer
        or metadata.get("tenant_id") != str(purchase.tenant_id)
        or metadata.get("user_id") != str(account.user_id)
        or obj.get("amount_total") != purchase.amount_minor
        or obj.get("currency") != purchase.currency.lower()
        or livemode != expected_livemode
        or obj.get("livemode") != livemode
    ):
        return "reconciliation_required"
    if purchase.state == "paid":
        return "processed"
    if purchase.state == "reconciliation_required":
        # A refund/dispute arrived before fulfillment. Preserve the hold;
        # never turn a later paid-session replay into spendable credits.
        return "processed"
    if purchase.state != "pending":
        return "reconciliation_required"
    if event_type == "checkout.session.expired":
        purchase.state = "failed"
        await session.flush()
        return "processed"
    if event_type == "checkout.session.async_payment_failed":
        purchase.state = "failed"
        await session.flush()
        return "processed"
    if obj.get("payment_status") != "paid":
        # Completion can precede delayed payment. Wait for async success.
        return "processed"
    payment_intent = obj.get("payment_intent")
    if not isinstance(payment_intent, str) or not payment_intent.startswith("pi_"):
        return "reconciliation_required"
    purchase.stripe_payment_intent_id = payment_intent
    purchase.state = "paid"
    session.add(
        BillingCreditEntry(
            tenant_id=purchase.tenant_id,
            billing_account_id=account.id,
            purchase_id=purchase.id,
            entry_type="grant",
            available_delta=purchase.unit_grant,
            reserved_delta=0,
            idempotency_key=f"credit-grant:{purchase.id}",
        )
    )
    await session.flush()
    return "processed"


async def apply_credit_reversal(
    session: AsyncSession,
    *,
    event_type: str,
    obj: dict[str, object],
    livemode: bool,
    expected_livemode: bool,
    settings: Settings | None = None,
) -> str:
    """Full refunds reverse only unspent lots; disputes freeze wallet spending."""
    intent = obj.get("payment_intent")
    if (not isinstance(intent, str) or not intent.startswith("pi_")) and settings is not None:
        charge_id = obj.get("charge")
        if isinstance(charge_id, str) and charge_id.startswith("ch_"):
            charge = await stripe_request(settings, "GET", f"/charges/{charge_id}")
            intent = charge.get("payment_intent")
    # Refund objects do not carry a livemode field; the signed Event does.
    if livemode != expected_livemode or ("livemode" in obj and obj["livemode"] != livemode):
        return "reconciliation_required"
    if not isinstance(intent, str) or not intent.startswith("pi_"):
        return "ignored"
    purchase = await session.scalar(
        select(BillingCreditPurchase).where(
            BillingCreditPurchase.stripe_payment_intent_id == intent
        )
    )
    if purchase is None:
        if settings is not None:
            # A refund can arrive before the paid Checkout event. Resolve the
            # PaymentIntent's server-owned purchase marker instead of losing
            # the only refund notification or blocking unrelated refunds.
            payment = await stripe_request(settings, "GET", f"/payment_intents/{intent}")
            metadata = payment.get("metadata")
            marker = metadata.get("purchase_id") if isinstance(metadata, dict) else None
            try:
                marker_id = uuid.UUID(str(marker))
            except (ValueError, TypeError):
                marker_id = None
            if marker_id is not None:
                pending = await session.scalar(
                    select(BillingCreditPurchase).where(BillingCreditPurchase.id == marker_id)
                )
                if pending is None:
                    return "reconciliation_required"
                await _bind_purchase_owner(session, pending)
                owner = await session.scalar(
                    select(BillingAccount).where(
                        BillingAccount.id == pending.billing_account_id,
                        BillingAccount.tenant_id == pending.tenant_id,
                        BillingAccount.user_id == pending.user_id,
                    )
                )
                if owner is None:
                    return "reconciliation_required"
                await _lock_account(
                    session,
                    tenant_id=pending.tenant_id,
                    user_id=owner.user_id,
                    create=False,
                )
                if pending.state == "pending":
                    pending.state = "reconciliation_required"
                    await session.flush()
                return "processed"
        return "ignored"
    await _bind_purchase_owner(session, purchase)
    account = await session.scalar(
        select(BillingAccount).where(
            BillingAccount.id == purchase.billing_account_id,
            BillingAccount.tenant_id == purchase.tenant_id,
            BillingAccount.user_id == purchase.user_id,
        )
    )
    if account is None:
        return "reconciliation_required"
    await _lock_account(
        session, tenant_id=purchase.tenant_id, user_id=account.user_id, create=False
    )
    if event_type == "charge.dispute.created":
        if obj.get("currency") != purchase.currency.lower():
            return "reconciliation_required"
        if purchase.state == "paid":
            purchase.state = "disputed"
        return "processed"
    if event_type == "charge.dispute.closed":
        if purchase.state != "disputed":
            return "reconciliation_required"
        if obj.get("status") == "won":
            purchase.state = "paid"
            return "processed"
        if obj.get("status") != "lost":
            return "reconciliation_required"
    if purchase.state == "refunded":
        return "processed"
    if purchase.state == "reconciliation_required":
        # A repeated refund notification must leave the wallet frozen without
        # repeatedly flagging the same already-recorded exception as new work.
        return "processed"
    if purchase.state not in ("paid", "disputed"):
        return "reconciliation_required"
    if (
        obj.get("amount") != purchase.amount_minor
        or obj.get("currency") != purchase.currency.lower()
    ):
        purchase.state = "reconciliation_required"
        return "processed"
    available = await session.scalar(
        select(func.coalesce(func.sum(BillingCreditEntry.available_delta), 0)).where(
            BillingCreditEntry.tenant_id == purchase.tenant_id,
            BillingCreditEntry.purchase_id == purchase.id,
        )
    )
    if int(available or 0) != purchase.unit_grant:
        purchase.state = "reconciliation_required"
        return "processed"
    session.add(
        BillingCreditEntry(
            tenant_id=purchase.tenant_id,
            billing_account_id=account.id,
            purchase_id=purchase.id,
            entry_type="reversal",
            available_delta=-purchase.unit_grant,
            reserved_delta=0,
            idempotency_key=f"credit-reversal:{purchase.id}",
        )
    )
    purchase.state = "refunded"
    await session.flush()
    return "processed"
