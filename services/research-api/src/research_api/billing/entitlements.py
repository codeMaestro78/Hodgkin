"""Read and validate the server-owned current billing-period projection."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.billing.catalog import APPROVED_CATALOGS, BillingCatalog
from research_api.billing.catalog import PlanKey as CatalogPlanKey
from research_api.db.models import BillingAccount, BillingPeriod, BillingUnitEntry
from research_api.schemas.generated.billing_entitlement import (
    BillingEntitlement,
    PlanKey,
    Status,
)


def project_entitlement(
    period: BillingPeriod | Any,
    *,
    consumed_units: int,
    reserved_units: int,
    approved_catalogs: Mapping[str, BillingCatalog] = APPROVED_CATALOGS,
) -> BillingEntitlement:
    """Build an active balance only from a matching approved catalog snapshot."""
    catalog = approved_catalogs.get(period.catalog_version)
    plan_key = cast(CatalogPlanKey, period.plan_key)
    plan = catalog.plans.get(plan_key) if catalog is not None else None
    starts_at = period.starts_at
    ends_at = period.ends_at
    values_are_valid = (
        starts_at.tzinfo is not None
        and ends_at.tzinfo is not None
        and starts_at < ends_at
        and period.allowance_units >= 0
        and consumed_units >= 0
        and reserved_units >= 0
    )
    if (
        catalog is None
        or catalog.status != "active"
        or plan is None
        or period.allowance_units != plan.monthly_allowance_units
        or not values_are_valid
    ):
        raise HTTPException(503, "billing entitlement temporarily unavailable")

    available_units = period.allowance_units - consumed_units - reserved_units
    if available_units < 0:
        raise HTTPException(503, "billing entitlement temporarily unavailable")
    return BillingEntitlement(
        status=Status.active,
        plan_key=PlanKey(period.plan_key),
        catalog_version=period.catalog_version,
        period_start=starts_at,
        period_end=ends_at,
        allowance_units=period.allowance_units,
        consumed_units=consumed_units,
        reserved_units=reserved_units,
        available_units=available_units,
    )


async def read_entitlement(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
    approved_catalogs: Mapping[str, BillingCatalog] = APPROVED_CATALOGS,
) -> BillingEntitlement:
    """Read an owner-scoped active period; missing grants remain unconfigured."""
    account_id = await session.scalar(
        select(BillingAccount.id).where(
            BillingAccount.tenant_id == tenant_id,
            BillingAccount.user_id == user_id,
            BillingAccount.account_type == "personal",
        )
    )
    if account_id is None:
        return BillingEntitlement(status=Status.not_configured)

    instant = now or datetime.now(UTC)
    periods = (
        await session.scalars(
            select(BillingPeriod)
            .where(
                BillingPeriod.tenant_id == tenant_id,
                BillingPeriod.billing_account_id == account_id,
                BillingPeriod.state == "active",
                BillingPeriod.starts_at <= instant,
                BillingPeriod.ends_at > instant,
            )
            .limit(2)
        )
    ).all()
    if not periods:
        return BillingEntitlement(status=Status.not_configured)
    if len(periods) != 1:
        raise HTTPException(503, "billing entitlement temporarily unavailable")

    period = periods[0]
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(BillingUnitEntry.consumed_delta), 0),
                func.coalesce(func.sum(BillingUnitEntry.reserved_delta), 0),
            ).where(
                BillingUnitEntry.tenant_id == tenant_id,
                BillingUnitEntry.billing_account_id == account_id,
                BillingUnitEntry.billing_period_id == period.id,
            )
        )
    ).one()
    return project_entitlement(
        period,
        consumed_units=int(totals[0]),
        reserved_units=int(totals[1]),
        approved_catalogs=approved_catalogs,
    )
