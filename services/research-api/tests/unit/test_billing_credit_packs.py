import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_api.auth import Caller
from research_api.billing.api import caller_dependency, router
from research_api.billing.credit_packs import (
    CREDIT_TERMS_VERSION,
    configured_razorpay_credit_packs,
    razorpay_credit_topups_available,
)
from research_api.config import Settings


def _settings(**overrides) -> Settings:
    values = {
        "APP_ENV": "test",
        "BILLING_RAZORPAY_ENABLED": True,
        "BILLING_ENFORCEMENT_ENABLED": True,
        "BILLING_CREDIT_TOPUPS_ENABLED": True,
        "BILLING_CREDIT_TERMS_APPROVED": True,
        "BILLING_CREDIT_TERMS_VERSION": CREDIT_TERMS_VERSION,
        "BILLING_CREDIT_FULFILLMENT_ENABLED": True,
        "BILLING_CREDIT_SPENDING_ENABLED": True,
        "BILLING_CREDIT_MAX_WALLET_UNITS": 100,
        "RAZORPAY_KEY_ID": "rzp_test_fixture123",
        "RAZORPAY_KEY_SECRET": SecretStr("fixture-secret"),
        "RAZORPAY_WEBHOOK_SECRET": SecretStr("webhook-fixture-secret"),
        "RAZORPAY_CREDIT_PACKS_JSON": json.dumps(
            [
                {
                    "key": "starter",
                    "amountMinor": 500,
                    "currency": "INR",
                    "units": 10,
                    "expiryDays": None,
                }
            ]
        ),
    }
    values.update(overrides)
    return Settings(**values)


def test_razorpay_pack_catalog_is_strict_and_non_expiring():
    pack = configured_razorpay_credit_packs(_settings())["starter"]
    assert (pack.amount_minor, pack.currency, pack.units, pack.expiry_days) == (
        500,
        "INR",
        10,
        None,
    )
    assert configured_razorpay_credit_packs(_settings(RAZORPAY_CREDIT_PACKS_JSON="not-json")) == {}
    expiring = json.dumps(
        [{"key": "starter", "amountMinor": 500, "currency": "INR", "units": 10, "expiryDays": 30}]
    )
    assert configured_razorpay_credit_packs(_settings(RAZORPAY_CREDIT_PACKS_JSON=expiring)) == {}


def test_proposed_inr_topup_offers_have_fixed_prices_and_unit_grants():
    offers = [
        {
            "key": "starter",
            "amountMinor": 19900,
            "currency": "INR",
            "units": 5,
            "expiryDays": None,
        },
        {
            "key": "standard",
            "amountMinor": 49900,
            "currency": "INR",
            "units": 15,
            "expiryDays": None,
        },
        {
            "key": "value",
            "amountMinor": 89900,
            "currency": "INR",
            "units": 30,
            "expiryDays": None,
        },
    ]

    packs = configured_razorpay_credit_packs(
        _settings(RAZORPAY_CREDIT_PACKS_JSON=json.dumps(offers))
    )

    assert [(pack.amount_minor, pack.units) for pack in packs.values()] == [
        (19900, 5),
        (49900, 15),
        (89900, 30),
    ]
    assert all(pack.currency == "INR" and pack.expiry_days is None for pack in packs.values())


def test_razorpay_pack_catalog_rejects_usd_and_mixed_currencies():
    usd = json.dumps(
        [{"key": "starter", "amountMinor": 199, "currency": "USD", "units": 5, "expiryDays": None}]
    )
    assert configured_razorpay_credit_packs(_settings(RAZORPAY_CREDIT_PACKS_JSON=usd)) == {}

    mixed = json.dumps(
        [
            {
                "key": "starter",
                "amountMinor": 199,
                "currency": "USD",
                "units": 5,
                "expiryDays": None,
            },
            {
                "key": "domestic",
                "amountMinor": 19900,
                "currency": "INR",
                "units": 5,
                "expiryDays": None,
            },
        ]
    )
    assert configured_razorpay_credit_packs(_settings(RAZORPAY_CREDIT_PACKS_JSON=mixed)) == {}


def test_credit_purchase_availability_fails_closed_for_each_policy_gate():
    assert razorpay_credit_topups_available(_settings())
    assert not razorpay_credit_topups_available(_settings(BILLING_RAZORPAY_ENABLED=False))
    assert not razorpay_credit_topups_available(_settings(BILLING_ENFORCEMENT_ENABLED=False))
    assert not razorpay_credit_topups_available(_settings(BILLING_CREDIT_TERMS_APPROVED=False))
    assert not razorpay_credit_topups_available(_settings(BILLING_CREDIT_SPENDING_ENABLED=False))
    assert not razorpay_credit_topups_available(_settings(RAZORPAY_WEBHOOK_SECRET=None))


def test_usd_credit_packs_remain_unavailable():
    usd_packs = json.dumps(
        [{"key": "starter", "amountMinor": 199, "currency": "USD", "units": 5, "expiryDays": None}]
    )
    assert not razorpay_credit_topups_available(_settings(RAZORPAY_CREDIT_PACKS_JSON=usd_packs))
    assert not razorpay_credit_topups_available(_settings(RAZORPAY_CREDIT_PACKS_JSON=usd_packs))


def test_authenticated_package_listing_hides_secrets_and_is_off_by_default(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
    )
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _settings(BILLING_RAZORPAY_ENABLED=False),
    )

    response = TestClient(app).get("/billing/credit-packs")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "currency": "INR", "packs": []}
    assert "fixture-secret" not in response.text
    assert "keyId" not in response.text


def test_authenticated_package_listing_reports_inr_currency(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
    )
    inr_settings = _settings(
        RAZORPAY_CREDIT_PACKS_JSON=json.dumps(
            [
                {
                    "key": "starter",
                    "amountMinor": 19900,
                    "currency": "INR",
                    "units": 5,
                    "expiryDays": None,
                }
            ]
        ),
    )
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: inr_settings)
    monkeypatch.setattr(
        "research_api.billing.api._razorpay_schema_ready", AsyncMock(return_value=True)
    )
    session = AsyncMock()

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)

    response = TestClient(app).get("/billing/credit-packs")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "currency": "INR",
        "packs": [{"key": "starter", "amountMinor": 19900, "units": 5, "expiryDays": None}],
    }


def test_credit_pack_diagnostics_explain_closed_gates_without_secret_values(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
    )
    settings = _settings(
        BILLING_CREDIT_SPENDING_ENABLED=False,
        BILLING_CREDIT_TOPUPS_ENABLED=False,
    )
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)

    @asynccontextmanager
    async def ready_schema_session(_tenant):
        session = AsyncMock()
        session.scalar.return_value = True
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", ready_schema_session)
    response = TestClient(app).get("/billing/credit-packs/diagnostics")

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ready"] is False
    assert result["mode"] == "test"
    blocked = {check["id"] for check in result["checks"] if not check["ready"]}
    assert blocked == {"topups_enabled", "spending_enabled"}
    assert "fixture-secret" not in response.text
    assert "webhook-fixture-secret" not in response.text


def test_credit_pack_diagnostics_do_not_call_inconsistent_live_key_ready(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
    )
    settings = _settings(RAZORPAY_KEY_ID="rzp_test_fixture123", RAZORPAY_LIVEMODE=True)
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)

    @asynccontextmanager
    async def ready_schema_session(_tenant):
        session = AsyncMock()
        session.scalar.return_value = True
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", ready_schema_session)
    response = TestClient(app).get("/billing/credit-packs/diagnostics")

    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "test"
    assert next(check for check in result["checks"] if check["id"] == "key_mode")["ready"] is False


def test_credit_pack_listing_requires_authentication():
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/billing/credit-packs").status_code == 401


def test_credit_checkout_is_disabled_by_default_and_does_not_call_razorpay(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
    )
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _settings(BILLING_CREDIT_TOPUPS_ENABLED=False),
    )
    provider_create = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = TestClient(app).post(
        "/billing/credit-checkout",
        headers={"Idempotency-Key": "request-credit-123"},
        json={"packageKey": "starter"},
    )

    assert response.status_code == 503
    provider_create.assert_not_awaited()


def test_credit_balance_is_unavailable_before_wallet_migration(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
    )

    @asynccontextmanager
    async def pre_migration_session(_tenant):
        session = AsyncMock()
        session.scalar.return_value = False
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", pre_migration_session)
    response = TestClient(app).get("/billing/credit-balance")

    assert response.status_code == 200
    assert response.json() == {"enabled": False}
