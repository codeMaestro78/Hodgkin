"""Apply signed Stripe subscription snapshots to the authoritative unit ledger."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.billing.catalog import BILLING_CATALOG
from research_api.billing.ledger import ensure_period_grant, transition_period_state
from research_api.billing.stripe import STRIPE_ID_PATTERN, configured_prices
from research_api.config import Settings
from research_api.db.models import (
    BillingAccount,
    BillingPeriod,
    StripeCheckoutAttempt,
    StripeCustomerLink,
    StripeSubscription,
)


def _unix_time(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _subscription_item(obj: Mapping[str, object]) -> Mapping[str, object] | None:
    items = obj.get("items")
    rows = items.get("data") if isinstance(items, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    return rows[0]


def _active_snapshot(
    obj: Mapping[str, object], settings: Settings
) -> tuple[str, str, datetime, datetime] | None:
    item = _subscription_item(obj)
    price_value = item.get("price") if item else None
    price = price_value if isinstance(price_value, Mapping) else None
    recurring_value = price.get("recurring") if price else None
    recurring = recurring_value if isinstance(recurring_value, Mapping) else None
    price_id = price.get("id") if price else None
    if (
        price is None
        or not isinstance(price_id, str)
        or recurring is None
        or recurring.get("interval") != "month"
        or recurring.get("interval_count") != 1
    ):
        return None
    plan_key = next(
        (
            plan
            for plan, configured in configured_prices(settings).items()
            if configured == price_id
        ),
        None,
    )
    plan = next(
        (item for key, item in BILLING_CATALOG.plans.items() if key == plan_key),
        None,
    )
    starts = _unix_time(item.get("current_period_start")) if item else None
    ends = _unix_time(item.get("current_period_end")) if item else None
    if (
        plan is None
        or plan.key == "free"
        or price.get("currency") != "usd"
        or price.get("unit_amount") != int(plan.monthly_price_usd * 100)
        or starts is None
        or ends is None
        or starts >= ends
    ):
        return None
    return plan.key, price_id, starts, ends


async def apply_subscription_event(
    session: AsyncSession,
    *,
    event_id: str,
    event_created_at: datetime,
    event_type: str,
    livemode: bool,
    obj: Mapping[str, object],
    settings: Settings,
) -> str:
    """Apply one subscription event within the caller's inbox transaction.

    Only active, exactly configured monthly Prices grant units. Unknown owner,
    Price, interval, or ambiguous same-second snapshots are held for operator
    reconciliation; no raw Stripe object is persisted.
    """
    expected_customer = obj.get("customer")
    subscription_id = obj.get("id")
    status = obj.get("status")
    if (
        livemode != settings.STRIPE_LIVEMODE
        or not isinstance(expected_customer, str)
        or not expected_customer.startswith("cus_")
        or STRIPE_ID_PATTERN.fullmatch(expected_customer) is None
        or not isinstance(subscription_id, str)
        or not subscription_id.startswith("sub_")
        or STRIPE_ID_PATTERN.fullmatch(subscription_id) is None
        or not isinstance(status, str)
    ):
        return "reconciliation_required"

    lock_key = f"stripe-subscription-v1:{subscription_id}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))

    link = await session.scalar(
        select(StripeCustomerLink).where(StripeCustomerLink.stripe_customer_id == expected_customer)
    )
    if link is None:
        return "reconciliation_required"
    existing = await session.get(StripeSubscription, subscription_id)
    if existing is not None and (
        existing.tenant_id != link.tenant_id
        or existing.user_id != link.user_id
        or existing.stripe_customer_id != expected_customer
    ):
        return "reconciliation_required"

    if existing is not None and event_created_at < existing.last_event_created:
        return "stale"

    plan_key: str | None = None
    price_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    if event_type != "customer.subscription.deleted" and status == "active":
        snapshot = _active_snapshot(obj, settings)
        if snapshot is None:
            return "reconciliation_required"
        plan_key, price_id, period_start, period_end = snapshot
        if period_end <= datetime.now(UTC):
            return "reconciliation_required"

    if existing is not None and event_created_at == existing.last_event_created:
        if (
            existing.status == status
            and existing.plan_key == plan_key
            and existing.price_id == price_id
            and existing.current_period_start == period_start
            and existing.current_period_end == period_end
        ):
            # Re-run idempotent grant/suspension work. A previous event may have
            # been recorded as needing reconciliation before its ledger effect.
            pass
        else:
            return "reconciliation_required"

    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": str(link.tenant_id)},
    )
    await session.execute(
        text("SELECT set_config('app.user_id', :user, true)"),
        {"user": str(link.user_id)},
    )
    account = await session.scalar(
        select(BillingAccount).where(
            BillingAccount.tenant_id == link.tenant_id,
            BillingAccount.user_id == link.user_id,
        )
    )
    if account is None:
        # Account creation is serialized by ensure_period_grant for active plans.
        if status != "active" or plan_key is None:
            return "processed"

    if status == "active" and plan_key is not None and period_start and period_end:
        if account is not None:
            overlapping_periods = (
                await session.scalars(
                    select(BillingPeriod).where(
                        BillingPeriod.tenant_id == link.tenant_id,
                        BillingPeriod.billing_account_id == account.id,
                        BillingPeriod.state.in_(("pending", "active", "suspended")),
                        BillingPeriod.starts_at < period_end,
                        BillingPeriod.ends_at > period_start,
                    )
                )
            ).all()
            paid_overlaps = [period for period in overlapping_periods if period.plan_key != "free"]
            if paid_overlaps:
                exact_current = [
                    period
                    for period in paid_overlaps
                    if period.plan_key == plan_key
                    and period.catalog_version == BILLING_CATALOG.version
                    and period.starts_at == period_start
                    and period.ends_at == period_end
                    and period.state in {"pending", "active", "suspended"}
                ]
                if len(paid_overlaps) != 1 or len(exact_current) != 1:
                    # Plan changes, overlapping periods, and mismatched replay
                    # terms require an explicit proration/credit decision.
                    return "reconciliation_required"
            for prior_period in overlapping_periods:
                if prior_period.plan_key != "free":
                    continue
                overlap_transition: Literal["active", "suspended", "ended"] = "suspended"
                if prior_period.state != overlap_transition:
                    await transition_period_state(
                        session,
                        tenant_id=link.tenant_id,
                        user_id=link.user_id,
                        period=prior_period,
                        next_state=overlap_transition,
                        effective_at=datetime.now(UTC),
                    )
        period = await ensure_period_grant(
            session,
            tenant_id=link.tenant_id,
            user_id=link.user_id,
            plan_key=plan_key,
            catalog_version=BILLING_CATALOG.version,
            starts_at=period_start,
            ends_at=period_end,
        )
        if period.state != "active":
            await transition_period_state(
                session,
                tenant_id=link.tenant_id,
                user_id=link.user_id,
                period=period,
                next_state="active",
                effective_at=datetime.now(UTC),
            )
    elif account is not None:
        status_transition: Literal["active", "suspended", "ended"] = (
            "ended" if status == "canceled" or event_type.endswith(".deleted") else "suspended"
        )
        paid_periods = (
            await session.scalars(
                select(BillingPeriod).where(
                    BillingPeriod.tenant_id == link.tenant_id,
                    BillingPeriod.billing_account_id == account.id,
                    BillingPeriod.plan_key != "free",
                    BillingPeriod.state.in_(("active", "suspended")),
                )
            )
        ).all()
        for period in paid_periods:
            if period.state != status_transition:
                await transition_period_state(
                    session,
                    tenant_id=link.tenant_id,
                    user_id=link.user_id,
                    period=period,
                    next_state=status_transition,
                    effective_at=datetime.now(UTC),
                )

    row = existing or StripeSubscription(
        stripe_subscription_id=subscription_id,
        stripe_customer_id=expected_customer,
        tenant_id=link.tenant_id,
        user_id=link.user_id,
        status=status,
        last_event_created=event_created_at,
        last_event_id=event_id,
    )
    row.status = status
    row.plan_key = plan_key
    row.price_id = price_id
    row.current_period_start = period_start
    row.current_period_end = period_end
    row.last_event_created = event_created_at
    row.last_event_id = event_id
    session.add(row)
    return "processed"


async def apply_checkout_event(
    session: AsyncSession,
    *,
    event_type: str,
    obj: Mapping[str, object],
) -> str:
    """Close the persisted one-open-checkout guard from a signed Stripe event."""
    session_id = obj.get("id")
    customer_id = obj.get("customer")
    metadata = obj.get("metadata")
    attempt_id = metadata.get("checkout_attempt_id") if isinstance(metadata, dict) else None
    if (
        not isinstance(session_id, str)
        or not session_id.startswith("cs_")
        or STRIPE_ID_PATTERN.fullmatch(session_id) is None
        or not isinstance(customer_id, str)
        or not customer_id.startswith("cus_")
        or STRIPE_ID_PATTERN.fullmatch(customer_id) is None
        or not isinstance(attempt_id, str)
    ):
        return "reconciliation_required"
    try:
        parsed_attempt_id = uuid.UUID(attempt_id)
    except ValueError:
        return "reconciliation_required"
    attempt = await session.get(StripeCheckoutAttempt, parsed_attempt_id)
    if attempt is None or (
        attempt.stripe_session_id not in {None, session_id} or obj.get("mode") != "subscription"
    ):
        return "reconciliation_required"
    mapping = await session.scalar(
        select(StripeCustomerLink).where(
            StripeCustomerLink.stripe_customer_id == customer_id,
            StripeCustomerLink.tenant_id == attempt.tenant_id,
            StripeCustomerLink.user_id == attempt.user_id,
        )
    )
    if mapping is None:
        return "reconciliation_required"
    attempt.stripe_session_id = session_id
    attempt.state = "expired" if event_type == "checkout.session.expired" else "completed"
    return "processed"
