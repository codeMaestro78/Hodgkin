import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.auth import Caller
from research_api.billing.api import caller_dependency, read_caller_entitlement, router
from research_api.config import Settings
from research_api.schemas.generated.billing_entitlement import BillingEntitlement, Status


def test_entitlement_read_is_authenticated_and_does_not_invent_a_balance(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        user_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
    )
    monkeypatch.setattr(
        "research_api.billing.api.read_caller_entitlement",
        AsyncMock(return_value=BillingEntitlement(status=Status.not_configured)),
    )

    response = TestClient(app).get("/billing/entitlement")

    assert response.status_code == 200
    assert response.json() == {"status": "not_configured"}


def test_entitlement_rejects_calls_without_the_existing_service_auth_boundary():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/billing/entitlement")

    assert response.status_code == 401


def test_entitlement_api_serializes_catalog_allowed_modes(monkeypatch):
    from research_api.billing.catalog import BILLING_CATALOG
    from research_api.billing.entitlements import project_entitlement

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        user_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
    )
    period = SimpleNamespace(
        catalog_version=BILLING_CATALOG.version,
        plan_key="scholar",
        starts_at=datetime(2026, 10, 1, tzinfo=UTC),
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        allowance_units=20,
    )
    projected = project_entitlement(period, consumed_units=8, reserved_units=4)
    monkeypatch.setattr(
        "research_api.billing.api.read_caller_entitlement",
        AsyncMock(return_value=projected),
    )

    response = TestClient(app).get("/billing/entitlement")

    assert response.status_code == 200
    assert response.json() == {
        "status": "active",
        "planKey": "scholar",
        "allowedModes": ["focused", "balanced"],
        "catalogVersion": BILLING_CATALOG.version,
        "periodStart": "2026-10-01T00:00:00Z",
        "periodEnd": "2026-11-01T00:00:00Z",
        "allowanceUnits": 20,
        "consumedUnits": 8,
        "reservedUnits": 4,
        "availableUnits": 8,
    }


async def test_entitlement_read_binds_authenticated_identity_to_rls(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    caller = Caller(tenant_id=tenant_id, user_id=user_id)
    session = AsyncMock()
    projected = BillingEntitlement(status=Status.not_configured)
    read_projection = AsyncMock(return_value=projected)

    @asynccontextmanager
    async def fake_tenant_session(received_tenant_id):
        assert received_tenant_id == str(tenant_id)
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)
    monkeypatch.setattr("research_api.billing.api.read_entitlement", read_projection)

    result = await read_caller_entitlement(caller)

    assert result == projected
    session.execute.assert_awaited_once()
    assert session.execute.await_args.args[0].text == "SELECT set_config('app.user_id', :id, true)"
    assert session.execute.await_args.args[1] == {"id": str(user_id)}
    read_projection.assert_awaited_once_with(session, tenant_id=tenant_id, user_id=user_id)


async def test_configured_internal_user_gets_unmetered_all_mode_entitlement(monkeypatch):
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    caller = Caller(tenant_id=tenant_id, user_id=user_id)
    session = AsyncMock()

    @asynccontextmanager
    async def fake_tenant_session(_tenant_id):
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: Settings(
            _env_file=None,
            BILLING_INTERNAL_UNMETERED_USER_IDS={user_id},
        ),
    )
    monkeypatch.setattr(
        "research_api.billing.api.read_entitlement",
        AsyncMock(return_value=BillingEntitlement(status=Status.not_configured)),
    )

    result = await read_caller_entitlement(caller)

    assert result.status == Status.active
    assert result.internal_access is True
    assert [mode.value for mode in result.allowed_modes] == ["focused", "balanced", "deep"]
    assert result.available_units is None


def test_catalog_exposes_inr_v3_proposal_and_preserves_prior_catalog_terms():
    from research_api.billing.catalog import (
        APPROVED_CATALOGS,
        BILLING_CATALOG,
        require_approved_catalog,
    )

    assert BILLING_CATALOG.status == "active"
    assert BILLING_CATALOG.version == "research-units-v3-2026-10-22"
    assert BILLING_CATALOG.monthly_allowances == {
        "free": 5,
        "scholar": 20,
        "investigator": 40,
    }
    assert BILLING_CATALOG.plans["scholar"].currency == "INR"
    assert BILLING_CATALOG.plans["scholar"].monthly_price == Decimal("599")
    assert BILLING_CATALOG.plans["scholar"].annual_price == Decimal("5999")
    assert BILLING_CATALOG.plans["scholar"].allowed_modes == ("focused", "balanced")
    assert BILLING_CATALOG.plans["investigator"].currency == "INR"
    assert BILLING_CATALOG.plans["investigator"].monthly_price == Decimal("1299")
    assert BILLING_CATALOG.plans["investigator"].annual_price == Decimal("12999")
    assert BILLING_CATALOG.plans["investigator"].allowed_modes == (
        "focused",
        "balanced",
        "deep",
    )
    assert "research-units-v1-2026-10-19" in APPROVED_CATALOGS
    assert APPROVED_CATALOGS["research-units-v2-2026-10-19"].plans[
        "scholar"
    ].monthly_price == Decimal("5.99")
    assert APPROVED_CATALOGS["research-units-v1-2026-10-19"].monthly_allowances == {
        "free": 5,
        "scholar": 40,
        "investigator": 120,
    }
    assert require_approved_catalog(BILLING_CATALOG) is BILLING_CATALOG


def test_entitlement_exposes_modes_from_its_approved_catalog_snapshot():
    from research_api.billing.catalog import BILLING_CATALOG
    from research_api.billing.entitlements import project_entitlement

    period = SimpleNamespace(
        catalog_version=BILLING_CATALOG.version,
        plan_key="scholar",
        starts_at=datetime(2026, 10, 1, tzinfo=UTC),
        ends_at=datetime(2026, 11, 1, tzinfo=UTC),
        allowance_units=20,
    )
    entitlement = project_entitlement(period, consumed_units=0, reserved_units=0)
    assert [mode.value for mode in entitlement.allowed_modes] == ["focused", "balanced"]
