import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from research_api.billing import catalog
from research_api.billing.entitlements import project_entitlement, read_entitlement


def _approved_catalog(version: str = "approved-catalog-v1"):
    draft = catalog.BILLING_CATALOG
    active = replace(
        draft,
        version=version,
        status="active",
        plans=MappingProxyType(
            {
                key: replace(
                    plan,
                    monthly_allowance_units=40 if key == "scholar" else 120,
                    monthly_price_usd=Decimal("0"),
                )
                for key, plan in draft.plans.items()
            }
        ),
    )
    return active


def test_entitlement_balance_is_derived_from_persisted_period_and_ledger():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    period = SimpleNamespace(
        plan_key="scholar",
        catalog_version="approved-catalog-v1",
        starts_at=start,
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        allowance_units=40,
    )

    result = project_entitlement(
        period,
        consumed_units=8,
        reserved_units=4,
        approved_catalogs={"approved-catalog-v1": _approved_catalog()},
    )

    assert result.model_dump(by_alias=True) == {
        "status": "active",
        "planKey": "scholar",
        "catalogVersion": "approved-catalog-v1",
        "periodStart": start,
        "periodEnd": datetime(2026, 11, 1, tzinfo=UTC),
        "allowanceUnits": 40,
        "consumedUnits": 8,
        "reservedUnits": 4,
        "availableUnits": 28,
    }


@pytest.mark.parametrize(
    ("consumed", "reserved"),
    [(-1, 0), (0, -1), (39, 2)],
)
def test_inconsistent_ledger_does_not_publish_a_balance(consumed, reserved):
    period = SimpleNamespace(
        plan_key="scholar",
        catalog_version="approved-catalog-v1",
        starts_at=datetime(2026, 10, 1, tzinfo=UTC),
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        allowance_units=40,
    )

    with pytest.raises(HTTPException) as error:
        project_entitlement(
            period,
            consumed_units=consumed,
            reserved_units=reserved,
            approved_catalogs={"approved-catalog-v1": _approved_catalog()},
        )
    assert error.value.status_code == 503


def test_unapproved_or_unknown_catalog_never_authorizes_period_projection():
    period = SimpleNamespace(
        plan_key="free",
        catalog_version="unknown-catalog-v0",
        starts_at=datetime(2026, 10, 1, tzinfo=UTC),
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        allowance_units=5,
    )
    with pytest.raises(HTTPException) as error:
        project_entitlement(
            period,
            consumed_units=0,
            reserved_units=0,
            approved_catalogs={catalog.BILLING_CATALOG.version: catalog.BILLING_CATALOG},
        )
    assert error.value.status_code == 503


async def test_missing_personal_billing_account_returns_not_configured():
    session = AsyncMock()
    session.scalar.return_value = None

    result = await read_entitlement(
        session,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        now=datetime.now(UTC),
        approved_catalogs={},
    )

    assert result.status == "not_configured"
    session.execute.assert_not_awaited()


async def test_current_active_period_aggregates_persisted_ledger_deltas():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    period = SimpleNamespace(
        id=uuid.uuid4(),
        plan_key="scholar",
        catalog_version="approved-catalog-v1",
        starts_at=start,
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        allowance_units=40,
    )
    session = AsyncMock()
    session.scalar.return_value = uuid.uuid4()
    session.scalars.return_value = SimpleNamespace(all=lambda: [period])
    session.execute.return_value = SimpleNamespace(one=lambda: (8, 4))

    result = await read_entitlement(
        session,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        now=datetime(2026, 10, 19, tzinfo=UTC),
        approved_catalogs={"approved-catalog-v1": _approved_catalog()},
    )

    assert result.available_units == 28
    session.scalar.assert_awaited_once()
    session.scalars.assert_awaited_once()
    session.execute.assert_awaited_once()


async def test_overlapping_active_periods_fail_closed():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    period = SimpleNamespace(
        id=uuid.uuid4(),
        plan_key="scholar",
        catalog_version="approved-catalog-v1",
        starts_at=start,
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        allowance_units=40,
    )
    session = AsyncMock()
    session.scalar.return_value = uuid.uuid4()
    session.scalars.return_value = SimpleNamespace(all=lambda: [period, period])

    with pytest.raises(HTTPException) as error:
        await read_entitlement(
            session,
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            now=datetime(2026, 10, 19, tzinfo=UTC),
            approved_catalogs={"approved-catalog-v1": _approved_catalog()},
        )

    assert error.value.status_code == 503
    session.execute.assert_not_awaited()
