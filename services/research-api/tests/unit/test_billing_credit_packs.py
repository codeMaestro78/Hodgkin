import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_api.auth import Caller
from research_api.billing.api import caller_dependency, router
from research_api.billing.credit_packs import (
    CREDIT_TERMS_VERSION,
    configured_credit_packs,
    credit_topups_available,
)
from research_api.billing.stripe import StripeUnavailable, validate_credit_price
from research_api.config import Settings


def _settings(**overrides):
    values = {
        "APP_ENV": "test",
        "BILLING_CREDIT_PACKS_JSON": json.dumps(
            [
                {
                    "key": "starter",
                    "priceId": "price_starter_test",
                    "amountMinor": 500,
                    "currency": "usd",
                    "units": 10,
                    "expiryDays": None,
                }
            ]
        ),
        "BILLING_CREDIT_TOPUPS_ENABLED": True,
        "BILLING_CREDIT_TERMS_APPROVED": True,
        "BILLING_CREDIT_TERMS_VERSION": CREDIT_TERMS_VERSION,
        "BILLING_CREDIT_FULFILLMENT_ENABLED": True,
        "BILLING_CREDIT_SPENDING_ENABLED": True,
        "BILLING_CREDIT_MAX_WALLET_UNITS": 100,
        "BILLING_STRIPE_ENABLED": True,
        "BILLING_ENFORCEMENT_ENABLED": True,
        "STRIPE_SECRET_KEY": SecretStr("sk_test_placeholder"),
        "STRIPE_WEBHOOK_SECRET": SecretStr("whsec_placeholder"),
        "STRIPE_API_VERSION": "2025-03-31.basil",
        "STRIPE_LIVEMODE": False,
        "BILLING_APP_BASE_URL": "http://localhost:3000",
    }
    values.update(overrides)
    return Settings(**values)


def test_credit_pack_configuration_is_strict_and_server_owned():
    settings = _settings()
    assert configured_credit_packs(settings)["starter"].price_id == "price_starter_test"
    assert configured_credit_packs(_settings(BILLING_CREDIT_PACKS_JSON="not-json")) == {}
    assert (
        configured_credit_packs(
            _settings(
                BILLING_CREDIT_PACKS_JSON=json.dumps(
                    [{"key": "starter", "priceId": "price_client_supplied"}]
                )
            )
        )
        == {}
    )


def test_credit_pack_configuration_rejects_expiration_under_approved_policy():
    expiring = _settings(
        BILLING_CREDIT_PACKS_JSON=json.dumps(
            [
                {
                    "key": "starter",
                    "priceId": "price_starter_test",
                    "amountMinor": 500,
                    "currency": "usd",
                    "units": 10,
                    "expiryDays": 365,
                }
            ]
        )
    )

    assert configured_credit_packs(expiring) == {}


def test_credit_checkout_requires_all_test_mode_gates():
    assert not credit_topups_available(_settings(BILLING_CREDIT_SPENDING_ENABLED=False))
    assert not credit_topups_available(_settings(BILLING_CREDIT_FULFILLMENT_ENABLED=False))
    assert not credit_topups_available(_settings(BILLING_CREDIT_TERMS_APPROVED=False))
    assert not credit_topups_available(
        _settings(BILLING_CREDIT_TERMS_VERSION="unreviewed-credit-terms")
    )
    assert not credit_topups_available(_settings(BILLING_CREDIT_TOPUPS_ENABLED=False))
    assert not credit_topups_available(_settings(STRIPE_LIVEMODE=True))


def test_approved_terms_version_and_non_expiring_pack_are_required(monkeypatch):
    monkeypatch.setattr("research_api.billing.credit_packs.CREDIT_PURCHASE_RELEASE_READY", True)

    assert credit_topups_available(_settings())
    assert not credit_topups_available(
        _settings(BILLING_CREDIT_TERMS_VERSION="research-credit-terms-v0")
    )
    expiring_packs = json.dumps(
        [
            {
                "key": "starter",
                "priceId": "price_starter_test",
                "amountMinor": 500,
                "currency": "usd",
                "units": 10,
                "expiryDays": 30,
            }
        ]
    )
    assert not credit_topups_available(_settings(BILLING_CREDIT_PACKS_JSON=expiring_packs))


@pytest.mark.anyio
async def test_credit_price_validation_rejects_recurring_and_amount_mismatch(monkeypatch):
    settings = _settings()
    stripe_request = AsyncMock(
        return_value={
            "id": "price_starter_test",
            "active": True,
            "currency": "usd",
            "unit_amount": 500,
            "type": "one_time",
            "recurring": None,
        }
    )
    monkeypatch.setattr("research_api.billing.stripe.stripe_request", stripe_request)
    await validate_credit_price(
        settings,
        price_id="price_starter_test",
        amount_minor=500,
        currency="usd",
    )
    stripe_request.return_value["recurring"] = {"interval": "month"}
    with pytest.raises(StripeUnavailable):
        await validate_credit_price(
            settings,
            price_id="price_starter_test",
            amount_minor=500,
            currency="usd",
        )
    stripe_request.return_value["recurring"] = None
    with pytest.raises(StripeUnavailable):
        await validate_credit_price(
            settings,
            price_id="price_starter_test",
            amount_minor=501,
            currency="usd",
        )


def test_authenticated_package_listing_hides_stripe_price_and_is_off_by_default(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id="11111111-1111-4111-8111-111111111111",
        user_id="22222222-2222-4222-8222-222222222222",
    )
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _settings(BILLING_CREDIT_TOPUPS_ENABLED=False),
    )
    client = TestClient(app)

    response = client.get("/billing/credit-packs")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "currency": "usd", "packs": []}
    assert "priceId" not in response.text


def test_credit_pack_listing_requires_authentication():
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/billing/credit-packs").status_code == 401


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


def test_credit_checkout_is_disabled_by_default_and_does_not_call_stripe(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id="11111111-1111-4111-8111-111111111111",
        user_id="22222222-2222-4222-8222-222222222222",
    )
    settings = _settings(BILLING_CREDIT_TOPUPS_ENABLED=False)
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    stripe_request = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)

    response = TestClient(app).post(
        "/billing/credit-checkout",
        headers={"Idempotency-Key": "request-credit-123"},
        json={"packageKey": "starter"},
    )

    assert response.status_code == 503
    stripe_request.assert_not_awaited()


def test_credit_checkout_uses_server_price_and_stable_payment_idempotency(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    caller = Caller(tenant_id=tenant_id, user_id=user_id)
    settings = _settings()
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    monkeypatch.setattr("research_api.billing.api.credit_topups_available", lambda _: True)
    validate_price = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.validate_credit_price", validate_price)
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        stripe_checkout_session_id=None,
        stripe_idempotency_key="persisted-credit-idempotency-key",
    )
    begin_purchase = AsyncMock(return_value=purchase)
    monkeypatch.setattr("research_api.billing.api._begin_credit_purchase", begin_purchase)
    monkeypatch.setattr(
        "research_api.billing.api._stripe_customer_for", AsyncMock(return_value="cus_test")
    )
    stripe_request = AsyncMock(
        return_value={"id": "cs_test_credit", "url": "https://checkout.stripe.com/c/session"}
    )
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)

    @asynccontextmanager
    async def fake_tenant_session(_tenant):
        yield AsyncMock()

    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: caller
    client = TestClient(app)

    response = client.post(
        "/billing/credit-checkout",
        headers={"Idempotency-Key": "request-credit-123"},
        json={"packageKey": "starter"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "purchaseId": str(purchase.id),
        "sessionId": "cs_test_credit",
        "url": "https://checkout.stripe.com/c/session",
    }
    validate_price.assert_awaited_with(
        settings,
        price_id="price_starter_test",
        amount_minor=500,
        currency="usd",
    )
    first_form = stripe_request.await_args.kwargs["form"]
    assert stripe_request.await_args.args[:2] == (settings, "POST")
    assert first_form["mode"] == "payment"
    assert first_form["line_items[0][price]"] == "price_starter_test"
    assert first_form["customer"] == "cus_test"
    assert stripe_request.await_args.kwargs["idempotency_key"] == "persisted-credit-idempotency-key"
    assert "priceId" not in response.text

    # An ambiguous client/server retry reuses the persisted order and Stripe key.
    retry = client.post(
        "/billing/credit-checkout",
        headers={"Idempotency-Key": "request-credit-123"},
        json={"packageKey": "starter"},
    )
    assert retry.status_code == 200
    assert retry.json() == response.json()
    assert stripe_request.await_count == 2
    assert {call.kwargs["idempotency_key"] for call in stripe_request.await_args_list} == {
        "persisted-credit-idempotency-key"
    }
    assert begin_purchase.await_count == 2
    begin_purchase.assert_awaited_with(
        caller,
        pack_key="starter",
        request_key="request-credit-123",
        amount_minor=500,
        price_id="price_starter_test",
        units=10,
        currency="usd",
        terms_version=CREDIT_TERMS_VERSION,
        max_wallet_units=100,
    )
