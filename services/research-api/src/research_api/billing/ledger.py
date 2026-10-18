"""Transactional billing-period grants and unit reservation/settlement primitives.

These functions participate in the caller's existing database transaction. They
never commit, call providers, or decide how a run outcome should be charged.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from research_api.billing.catalog import (
    APPROVED_CATALOGS,
    BILLING_CATALOG,
    BillingCatalog,
    PlanTerms,
)
from research_api.billing.catalog import PlanKey as CatalogPlanKey
from research_api.db.models import (
    BillingAccount,
    BillingPeriod,
    BillingUnitEntry,
    ResearchRun,
    StripeSubscription,
)
from research_api.mode_policy import ResearchMode

SettlementOutcome = Literal["consume", "release"]
BillingPeriodState = Literal["active", "suspended", "ended"]


class BillingLedgerError(RuntimeError):
    """Base class for safe-to-map billing-domain failures."""


class BillingConfigurationUnavailable(BillingLedgerError):
    """No approved catalog or usable period exists for this operation."""


class BillingGrantConflict(BillingLedgerError):
    """A period key was reused with different terms or overlaps another grant."""


class BillingModeUnavailable(BillingLedgerError):
    """The approved plan does not permit the requested research mode."""


class BillingReservationConflict(BillingLedgerError):
    """A run or idempotency key already has a different reservation."""


class BillingReservationMissing(BillingLedgerError):
    """A terminal run has no matching reservation to settle."""


class BillingSettlementConflict(BillingLedgerError):
    """A run already has a different terminal settlement."""


class BillingAdjustmentConflict(BillingLedgerError):
    """An adjustment idempotency key was reused with different audit details."""


class BillingAdjustmentUnavailable(BillingLedgerError):
    """An adjustment would make a period balance invalid."""


class BillingUnitsExhausted(BillingLedgerError):
    def __init__(self, *, required_units: int, available_units: int, period_end: datetime):
        super().__init__("insufficient research units")
        self.required_units = required_units
        self.available_units = available_units
        self.period_end = period_end


def billing_http_status(error: BillingLedgerError) -> tuple[int, str, dict[str, object]]:
    if isinstance(error, BillingUnitsExhausted):
        return (
            402,
            "insufficient research units",
            {
                "requiredUnits": error.required_units,
                "availableUnits": error.available_units,
                "periodEnd": error.period_end.isoformat(),
            },
        )
    if isinstance(error, BillingModeUnavailable):
        return 403, "research mode is not available on this plan", {}
    if isinstance(error, BillingConfigurationUnavailable):
        return 503, "billing is temporarily unavailable", {}
    return 409, "billing admission conflicts with existing state", {}


def _approved_plan(
    catalogs: Mapping[str, BillingCatalog], catalog_version: str, plan_key: str
) -> tuple[BillingCatalog, PlanTerms]:
    catalog = catalogs.get(catalog_version)
    typed_plan_key = cast(CatalogPlanKey, plan_key)
    plan = catalog.plans.get(typed_plan_key) if catalog is not None else None
    if (
        catalog is None
        or catalog.version != catalog_version
        or catalog.status != "active"
        or plan is None
    ):
        raise BillingConfigurationUnavailable("approved billing catalog unavailable")
    return catalog, plan


def _aware_period(start: datetime, end: datetime) -> bool:
    return (
        start.tzinfo is not None
        and start.utcoffset() is not None
        and end.tzinfo is not None
        and end.utcoffset() is not None
        and start < end
    )


def _validate_idempotency_key(key: str) -> None:
    if not key or len(key) > 200 or key.strip() != key:
        raise ValueError("invalid billing idempotency key")


async def _lock_account(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, create: bool
) -> BillingAccount | None:
    # Row-level FOR UPDATE requires UPDATE table privilege in PostgreSQL. A
    # transaction-scoped advisory lock keeps the least-privilege SELECT/INSERT
    # grants while serializing every grant/reserve/settle operation for an owner.
    lock_key = f"billing-account-v1:{tenant_id}:{user_id}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))
    if create:
        await session.execute(
            insert(BillingAccount)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                user_id=user_id,
                account_type="personal",
            )
            .on_conflict_do_nothing(
                index_elements=[BillingAccount.tenant_id, BillingAccount.user_id]
            )
        )
    return await session.scalar(
        select(BillingAccount).where(
            BillingAccount.tenant_id == tenant_id,
            BillingAccount.user_id == user_id,
            BillingAccount.account_type == "personal",
        )
    )


async def ensure_period_grant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    plan_key: str,
    catalog_version: str,
    starts_at: datetime,
    ends_at: datetime,
    approved_catalogs: Mapping[str, BillingCatalog] = APPROVED_CATALOGS,
) -> BillingPeriod:
    """Create or replay an approved grant under the account advisory lock.

    The caller owns the transaction and must already have installed tenant/user
    RLS context. Existing matching periods replay; conflicting or overlapping
    active/pending grants are rejected. No external subscription call belongs
    inside this function.
    """
    if not _aware_period(starts_at, ends_at):
        raise ValueError("billing period bounds must be timezone-aware and ordered")
    _, plan = _approved_plan(approved_catalogs, catalog_version, plan_key)
    account = await _lock_account(session, tenant_id=tenant_id, user_id=user_id, create=True)
    if account is None:
        raise BillingConfigurationUnavailable("billing account unavailable")

    existing = await session.scalar(
        select(BillingPeriod).where(
            BillingPeriod.tenant_id == tenant_id,
            BillingPeriod.billing_account_id == account.id,
            BillingPeriod.starts_at == starts_at,
            BillingPeriod.plan_key == plan_key,
        )
    )
    allowance = plan.monthly_allowance_units
    if existing is not None:
        if (
            existing.plan_key != plan_key
            or existing.catalog_version != catalog_version
            or existing.allowance_units != allowance
            or existing.ends_at != ends_at
        ):
            raise BillingGrantConflict("period grant key conflicts with stored terms")
        return existing

    overlap = await session.scalar(
        select(BillingPeriod.id)
        .where(
            BillingPeriod.tenant_id == tenant_id,
            BillingPeriod.billing_account_id == account.id,
            BillingPeriod.state.in_(("pending", "active")),
            BillingPeriod.starts_at < ends_at,
            BillingPeriod.ends_at > starts_at,
        )
        .limit(1)
    )
    if overlap is not None:
        raise BillingGrantConflict("billing periods cannot overlap")

    period = BillingPeriod(
        tenant_id=tenant_id,
        billing_account_id=account.id,
        plan_key=plan_key,
        catalog_version=catalog_version,
        state="active",
        allowance_units=allowance,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    session.add(period)
    await session.flush()
    return period


async def transition_period_state(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    period: BillingPeriod,
    next_state: BillingPeriodState,
    effective_at: datetime,
) -> None:
    """Use the narrowly granted database function, never table UPDATE privilege."""
    transitioned = await session.scalar(
        text("""
            SELECT public.transition_billing_period_state(
                :tenant_id, :user_id, :period_id, :next_state, :effective_at
            )
        """),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "period_id": period.id,
            "next_state": next_state,
            "effective_at": effective_at,
        },
    )
    if transitioned is not True:
        raise BillingGrantConflict("billing period state transition is not allowed")
    set_committed_value(period, "state", next_state)


async def ensure_default_free_period(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
    approved_catalogs: Mapping[str, BillingCatalog] = APPROVED_CATALOGS,
) -> BillingPeriod:
    """Lazily grant the approved Free month when the owner has no current grant.

    Paid grants must be provisioned by the verified subscription lifecycle. The
    caller owns the transaction and has installed tenant/user RLS context.
    """
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("billing clock must be timezone-aware")
    account = await _lock_account(session, tenant_id=tenant_id, user_id=user_id, create=True)
    if account is None:
        raise BillingConfigurationUnavailable("billing account unavailable")
    current_periods = (
        await session.scalars(
            select(BillingPeriod)
            .where(
                BillingPeriod.tenant_id == tenant_id,
                BillingPeriod.billing_account_id == account.id,
                BillingPeriod.state == "active",
                BillingPeriod.starts_at <= instant,
                BillingPeriod.ends_at > instant,
            )
            .limit(2)
        )
    ).all()
    if len(current_periods) > 1:
        raise BillingConfigurationUnavailable("multiple active billing periods")
    if current_periods:
        current = current_periods[0]
        _approved_plan(approved_catalogs, current.catalog_version, current.plan_key)
        if current.plan_key == "free" or current.catalog_version not in APPROVED_CATALOGS:
            return current
        subscription = await session.scalar(
            select(StripeSubscription).where(
                StripeSubscription.tenant_id == tenant_id,
                StripeSubscription.user_id == user_id,
                StripeSubscription.status == "active",
                StripeSubscription.plan_key == current.plan_key,
                StripeSubscription.current_period_start == current.starts_at,
                StripeSubscription.current_period_end == current.ends_at,
            )
        )
        if subscription is not None:
            return current
        await transition_period_state(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            period=current,
            next_state="suspended",
            effective_at=instant,
        )

    expired_periods = (
        await session.scalars(
            select(BillingPeriod).where(
                BillingPeriod.tenant_id == tenant_id,
                BillingPeriod.billing_account_id == account.id,
                BillingPeriod.state == "active",
                BillingPeriod.ends_at <= instant,
            )
        )
    ).all()
    for expired in expired_periods:
        await transition_period_state(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            period=expired,
            next_state="ended",
            effective_at=instant,
        )

    catalog, _ = _approved_plan(approved_catalogs, BILLING_CATALOG.version, "free")
    starts = datetime(instant.year, instant.month, 1, tzinfo=UTC)
    if instant.month == 12:
        ends = datetime(instant.year + 1, 1, 1, tzinfo=UTC)
    else:
        ends = datetime(instant.year, instant.month + 1, 1, tzinfo=UTC)
    existing_free = await session.scalar(
        select(BillingPeriod).where(
            BillingPeriod.tenant_id == tenant_id,
            BillingPeriod.billing_account_id == account.id,
            BillingPeriod.plan_key == "free",
            BillingPeriod.starts_at == starts,
        )
    )
    if existing_free is not None:
        if existing_free.state != "active":
            await transition_period_state(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                period=existing_free,
                next_state="active",
                effective_at=instant,
            )
        return existing_free
    return await ensure_period_grant(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        plan_key="free",
        catalog_version=catalog.version,
        starts_at=starts,
        ends_at=ends,
        approved_catalogs=approved_catalogs,
    )


async def _current_period(
    session: AsyncSession, *, tenant_id: uuid.UUID, account_id: uuid.UUID, now: datetime
) -> BillingPeriod:
    periods = (
        await session.scalars(
            select(BillingPeriod)
            .where(
                BillingPeriod.tenant_id == tenant_id,
                BillingPeriod.billing_account_id == account_id,
                BillingPeriod.state == "active",
                BillingPeriod.starts_at <= now,
                BillingPeriod.ends_at > now,
            )
            .limit(2)
        )
    ).all()
    if len(periods) != 1:
        raise BillingConfigurationUnavailable("current billing period unavailable")
    return periods[0]


async def _unit_totals(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    period_id: uuid.UUID,
) -> tuple[int, int]:
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(BillingUnitEntry.consumed_delta), 0),
                func.coalesce(func.sum(BillingUnitEntry.reserved_delta), 0),
            ).where(
                BillingUnitEntry.tenant_id == tenant_id,
                BillingUnitEntry.billing_account_id == account_id,
                BillingUnitEntry.billing_period_id == period_id,
            )
        )
    ).one()
    consumed, reserved = int(row[0]), int(row[1])
    if consumed < 0 or reserved < 0:
        raise BillingConfigurationUnavailable("unit ledger is inconsistent")
    return consumed, reserved


async def reserve_units(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    mode: ResearchMode,
    idempotency_key: str,
    now: datetime | None = None,
    approved_catalogs: Mapping[str, BillingCatalog] = APPROVED_CATALOGS,
) -> BillingUnitEntry:
    """Reserve the approved mode price while serializing on the owner account.

    Invoke inside the same transaction as the newly accepted run/job/outbox
    intent. Callers must not settle `uncertain` outcomes; leaving the reservation
    untouched keeps those units unavailable until recovery resolves the run.
    """
    _validate_idempotency_key(idempotency_key)
    account = await _lock_account(session, tenant_id=tenant_id, user_id=user_id, create=True)
    if account is None:
        raise BillingConfigurationUnavailable("billing account unavailable")

    run = (
        await session.execute(
            select(ResearchRun.user_id, ResearchRun.mode).where(
                ResearchRun.tenant_id == tenant_id,
                ResearchRun.user_id == user_id,
                ResearchRun.id == run_id,
            )
        )
    ).one_or_none()
    if run is None or run.mode != mode:
        raise BillingReservationConflict("run owner or mode does not match reservation")

    by_key = await session.scalar(
        select(BillingUnitEntry).where(
            BillingUnitEntry.tenant_id == tenant_id,
            BillingUnitEntry.billing_account_id == account.id,
            BillingUnitEntry.idempotency_key == idempotency_key,
        )
    )
    by_run = await session.scalar(
        select(BillingUnitEntry).where(
            BillingUnitEntry.tenant_id == tenant_id,
            BillingUnitEntry.billing_account_id == account.id,
            BillingUnitEntry.run_id == run_id,
            BillingUnitEntry.entry_type == "reservation",
        )
    )
    if by_key is not None or by_run is not None:
        prior = by_key or by_run
        assert prior is not None
        if (
            prior.run_id == run_id
            and prior.entry_type == "reservation"
            and prior.reserved_delta > 0
            and prior.idempotency_key == idempotency_key
            and (by_key is None or by_key.id == prior.id)
            and (by_run is None or by_run.id == prior.id)
        ):
            return prior
        raise BillingReservationConflict("reservation replay conflicts with stored request")

    await ensure_default_free_period(
        session, tenant_id=tenant_id, user_id=user_id, now=now, approved_catalogs=approved_catalogs
    )
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("billing clock must be timezone-aware")
    period = await _current_period(session, tenant_id=tenant_id, account_id=account.id, now=instant)
    catalog, plan = _approved_plan(approved_catalogs, period.catalog_version, period.plan_key)
    if mode not in plan.allowed_modes:
        raise BillingModeUnavailable("research mode is not included in this plan")
    required_units = catalog.mode_unit_prices.get(mode)
    if required_units is None or required_units <= 0:
        raise BillingConfigurationUnavailable("mode unit price unavailable")

    consumed, reserved = await _unit_totals(
        session,
        tenant_id=tenant_id,
        account_id=account.id,
        period_id=period.id,
    )
    available = period.allowance_units - consumed - reserved
    if available < required_units:
        raise BillingUnitsExhausted(
            required_units=required_units,
            available_units=max(available, 0),
            period_end=period.ends_at,
        )

    entry = BillingUnitEntry(
        tenant_id=tenant_id,
        billing_account_id=account.id,
        billing_period_id=period.id,
        run_id=run_id,
        entry_type="reservation",
        consumed_delta=0,
        reserved_delta=required_units,
        idempotency_key=idempotency_key,
    )
    session.add(entry)
    await session.flush()
    return entry


async def settle_units(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    outcome: SettlementOutcome,
    idempotency_key: str,
) -> BillingUnitEntry:
    """Append one terminal consume/release delta; uncertainty remains reserved."""
    _validate_idempotency_key(idempotency_key)
    if outcome not in {"consume", "release"}:
        raise ValueError("unsupported billing settlement outcome")
    account = await _lock_account(session, tenant_id=tenant_id, user_id=user_id, create=False)
    if account is None:
        raise BillingReservationMissing("run reservation unavailable")

    run = (
        await session.execute(
            select(ResearchRun.status).where(
                ResearchRun.tenant_id == tenant_id,
                ResearchRun.user_id == user_id,
                ResearchRun.id == run_id,
            )
        )
    ).one_or_none()
    if run is None or run.status not in {"completed", "failed", "cancelled"}:
        raise BillingReservationMissing("only an owned terminal run can be settled")

    existing_settlement = await session.scalar(
        select(BillingUnitEntry).where(
            BillingUnitEntry.tenant_id == tenant_id,
            BillingUnitEntry.billing_account_id == account.id,
            BillingUnitEntry.run_id == run_id,
            BillingUnitEntry.entry_type.in_(("consumption", "release")),
        )
    )
    if existing_settlement is not None:
        expected_type = "consumption" if outcome == "consume" else "release"
        if (
            existing_settlement.entry_type == expected_type
            and existing_settlement.idempotency_key == idempotency_key
        ):
            return existing_settlement
        raise BillingSettlementConflict("run already has a different settlement")

    key_entry = await session.scalar(
        select(BillingUnitEntry).where(
            BillingUnitEntry.tenant_id == tenant_id,
            BillingUnitEntry.billing_account_id == account.id,
            BillingUnitEntry.idempotency_key == idempotency_key,
        )
    )
    if key_entry is not None:
        expected_type = "consumption" if outcome == "consume" else "release"
        if key_entry.run_id == run_id and key_entry.entry_type == expected_type:
            return key_entry
        raise BillingSettlementConflict("settlement key conflicts with stored ledger entry")

    reservation = await session.scalar(
        select(BillingUnitEntry).where(
            BillingUnitEntry.tenant_id == tenant_id,
            BillingUnitEntry.billing_account_id == account.id,
            BillingUnitEntry.run_id == run_id,
            BillingUnitEntry.entry_type == "reservation",
        )
    )
    if reservation is None or reservation.reserved_delta <= 0:
        raise BillingReservationMissing("run reservation unavailable")

    entry = BillingUnitEntry(
        tenant_id=tenant_id,
        billing_account_id=account.id,
        billing_period_id=reservation.billing_period_id,
        run_id=run_id,
        entry_type="consumption" if outcome == "consume" else "release",
        consumed_delta=reservation.reserved_delta if outcome == "consume" else 0,
        reserved_delta=-reservation.reserved_delta,
        idempotency_key=idempotency_key,
    )
    session.add(entry)
    await session.flush()
    return entry


async def adjust_units(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    period_id: uuid.UUID,
    delta: int,
    idempotency_key: str,
    actor_id: uuid.UUID,
    reason: str,
) -> BillingUnitEntry:
    """Append an audited correction; authorization must be checked by the caller.

    Negative deltas restore previously consumed units. Positive deltas consume
    available units. The function cannot grant units, change a reservation, or
    bypass the period allowance. Operator identity and reason are immutable
    ledger data; this is an internal primitive, not an authorization boundary.
    """
    _validate_idempotency_key(idempotency_key)
    if not isinstance(actor_id, uuid.UUID) or actor_id.int == 0:
        raise ValueError("adjustment actor must be a non-zero UUID")
    if not isinstance(reason, str):
        raise ValueError("adjustment reason must be text")
    normalized_reason = reason.strip()
    if delta == 0:
        raise ValueError("adjustment delta cannot be zero")
    if not normalized_reason or len(normalized_reason) > 500:
        raise ValueError("adjustment reason must contain 1 to 500 characters")

    account = await _lock_account(session, tenant_id=tenant_id, user_id=user_id, create=False)
    if account is None:
        raise BillingConfigurationUnavailable("billing account unavailable")

    existing = await session.scalar(
        select(BillingUnitEntry).where(
            BillingUnitEntry.tenant_id == tenant_id,
            BillingUnitEntry.billing_account_id == account.id,
            BillingUnitEntry.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.entry_type == "adjustment"
            and existing.billing_period_id == period_id
            and existing.consumed_delta == delta
            and existing.actor_id == actor_id
            and existing.reason == normalized_reason
        ):
            return existing
        raise BillingAdjustmentConflict("adjustment key conflicts with stored audit record")

    period = await session.scalar(
        select(BillingPeriod).where(
            BillingPeriod.tenant_id == tenant_id,
            BillingPeriod.billing_account_id == account.id,
            BillingPeriod.id == period_id,
        )
    )
    if period is None:
        raise BillingConfigurationUnavailable("billing period unavailable")

    consumed, reserved = await _unit_totals(
        session,
        tenant_id=tenant_id,
        account_id=account.id,
        period_id=period.id,
    )
    updated_consumed = consumed + delta
    if updated_consumed < 0 or updated_consumed + reserved > period.allowance_units:
        raise BillingAdjustmentUnavailable("adjustment would violate period unit bounds")

    entry = BillingUnitEntry(
        tenant_id=tenant_id,
        billing_account_id=account.id,
        billing_period_id=period.id,
        entry_type="adjustment",
        consumed_delta=delta,
        reserved_delta=0,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        reason=normalized_reason,
    )
    session.add(entry)
    await session.flush()
    return entry
