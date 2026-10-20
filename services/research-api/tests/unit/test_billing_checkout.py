import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_api.auth import Caller
from research_api.billing.api import _begin_checkout_attempt, caller_dependency, router
from research_api.billing.stripe import StripeUnavailable
from research_api.config import Settings


def _test_settings(**overrides):
    values = {
        "APP_ENV": "test",
        "BILLING_STRIPE_ENABLED": True,
        "BILLING_ENFORCEMENT_ENABLED": True,
        "STRIPE_SECRET_KEY": SecretStr("sk_test_placeholder"),
        "STRIPE_WEBHOOK_SECRET": SecretStr("whsec_test_placeholder"),
        "STRIPE_API_VERSION": "2025-03-31.basil",
        "STRIPE_PRICE_SCHOLAR_MONTHLY": "price_scholar_test",
        "STRIPE_PRICE_INVESTIGATOR_MONTHLY": "price_investigator_test",
        "STRIPE_PORTAL_CONFIGURATION_ID": "bpc_test_configuration",
        "BILLING_APP_BASE_URL": "http://localhost:3000",
    }
    values.update(overrides)
    return Settings(**values)


def _client(tenant_id, user_id):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=tenant_id, user_id=user_id
    )
    return TestClient(app)


def test_checkout_uses_server_price_and_fixed_return_urls(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    settings = _test_settings()
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    session = AsyncMock()
    session.scalar.return_value = None

    @asynccontextmanager
    async def fake_tenant_session(_tenant):
        yield session

    attempt = SimpleNamespace(
        id=uuid.uuid4(), stripe_session_id=None, stripe_idempotency_key="safe-idem-key"
    )
    stripe_request = AsyncMock(
        return_value={"id": "cs_test_session", "url": "https://checkout.stripe.com/c/session"}
    )
    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)
    monkeypatch.setattr(
        "research_api.billing.api._begin_checkout_attempt",
        AsyncMock(return_value=attempt),
    )
    monkeypatch.setattr(
        "research_api.billing.api._stripe_customer_for",
        AsyncMock(return_value="cus_test"),
    )
    validate_price = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.validate_monthly_price", validate_price)
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)
    client = _client(tenant_id, user_id)

    response = client.post(
        "/billing/checkout",
        headers={"Idempotency-Key": "client-request-123"},
        json={"planKey": "scholar", "interval": "monthly"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "sessionId": "cs_test_session",
        "url": "https://checkout.stripe.com/c/session",
    }
    validate_price.assert_awaited_once_with(
        settings, plan_key="scholar", price_id="price_scholar_test"
    )
    form = stripe_request.await_args.kwargs["form"]
    assert form["line_items[0][price]"] == "price_scholar_test"
    assert form["customer"] == "cus_test"
    assert form["success_url"] == "http://localhost:3000/research?billing=success"
    assert "priceId" not in form
    assert stripe_request.await_args.kwargs["idempotency_key"] == "safe-idem-key"


def test_checkout_reuses_existing_stripe_session_instead_of_creating_another(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    settings = _test_settings()
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    session = AsyncMock()
    session.scalar.return_value = None

    @asynccontextmanager
    async def fake_tenant_session(_tenant):
        yield session

    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        stripe_session_id="cs_existing",
        stripe_idempotency_key="original-idempotency-key",
    )
    stripe_request = AsyncMock(
        return_value={
            "id": "cs_existing",
            "status": "open",
            "url": "https://checkout.stripe.com/c/session",
        }
    )
    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)
    monkeypatch.setattr(
        "research_api.billing.api._begin_checkout_attempt",
        AsyncMock(return_value=attempt),
    )
    monkeypatch.setattr(
        "research_api.billing.api._stripe_customer_for",
        AsyncMock(return_value="cus_test"),
    )
    monkeypatch.setattr(
        "research_api.billing.api.validate_monthly_price", AsyncMock()
    )
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)

    response = _client(tenant_id, user_id).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "new-browser-retry-key"},
        json={"planKey": "scholar", "interval": "monthly"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["sessionId"] == "cs_existing"
    stripe_request.assert_awaited_once_with(settings, "GET", "/checkout/sessions/cs_existing")


def test_checkout_completed_attempt_does_not_create_a_second_session(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    settings = _test_settings()
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    session = AsyncMock()
    session.scalar.return_value = None

    @asynccontextmanager
    async def fake_tenant_session(_tenant):
        yield session

    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        stripe_session_id="cs_completed",
        stripe_idempotency_key="original-idempotency-key",
    )
    stripe_request = AsyncMock(
        return_value={"id": "cs_completed", "status": "complete", "url": None}
    )
    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)
    monkeypatch.setattr(
        "research_api.billing.api._begin_checkout_attempt",
        AsyncMock(return_value=attempt),
    )
    monkeypatch.setattr(
        "research_api.billing.api._stripe_customer_for",
        AsyncMock(return_value="cus_test"),
    )
    monkeypatch.setattr(
        "research_api.billing.api.validate_monthly_price", AsyncMock()
    )
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)

    response = _client(tenant_id, user_id).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "new-browser-retry-key"},
        json={"planKey": "scholar", "interval": "monthly"},
    )

    assert response.status_code == 409
    assert "plan activation" in response.json()["detail"]
    stripe_request.assert_awaited_once_with(settings, "GET", "/checkout/sessions/cs_completed")


@pytest.mark.asyncio
async def test_checkout_retry_reuses_existing_open_attempt_for_same_plan(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        plan_key="scholar",
        state="open",
        expires_at=now + timedelta(hours=1),
        stripe_session_id="cs_existing",
        stripe_idempotency_key="original-stripe-idempotency-key",
    )
    session = AsyncMock()
    session.scalar.side_effect = [None, existing]

    @asynccontextmanager
    async def fake_tenant_session(_tenant):
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)

    attempt = await _begin_checkout_attempt(
        Caller(tenant_id=tenant_id, user_id=user_id),
        plan_key="scholar",
        request_key="new-browser-retry-key",
    )

    assert attempt is existing
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkout_retry_rejects_different_plan_while_attempt_is_open(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        plan_key="scholar",
        state="open",
        expires_at=now + timedelta(hours=1),
        stripe_session_id="cs_existing",
        stripe_idempotency_key="original-stripe-idempotency-key",
    )
    session = AsyncMock()
    session.scalar.side_effect = [None, existing]

    @asynccontextmanager
    async def fake_tenant_session(_tenant):
        yield session

    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)

    with pytest.raises(HTTPException) as exc_info:
        await _begin_checkout_attempt(
            Caller(tenant_id=tenant_id, user_id=user_id),
            plan_key="investigator",
            request_key="new-browser-retry-key",
        )

    assert exc_info.value.status_code == 409
    assert "already open" in exc_info.value.detail


def test_checkout_rejects_mispriced_or_wrong_interval_stripe_price(monkeypatch):
    settings = _test_settings()
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    stripe_request = AsyncMock()
    validate_price = AsyncMock(side_effect=StripeUnavailable("price mismatch"))
    monkeypatch.setattr("research_api.billing.api.validate_monthly_price", validate_price)
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)
    response = _client(uuid.uuid4(), uuid.uuid4()).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "client-request-123"},
        json={"planKey": "scholar", "interval": "monthly"},
    )

    assert response.status_code == 503
    assert "Stripe Price" not in response.text
    validate_price.assert_awaited_once()
    stripe_request.assert_not_awaited()


def test_checkout_is_closed_when_feature_or_enforcement_is_off(monkeypatch):
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _test_settings(BILLING_STRIPE_ENABLED=False),
    )
    stripe_request = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)
    client = _client(uuid.uuid4(), uuid.uuid4())

    response = client.post(
        "/billing/checkout",
        headers={"Idempotency-Key": "client-request-123"},
        json={"planKey": "investigator", "interval": "monthly"},
    )

    assert response.status_code == 503
    stripe_request.assert_not_awaited()


def test_live_checkout_requires_separate_launch_approval(monkeypatch):
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _test_settings(STRIPE_LIVEMODE=True),
    )
    stripe_request = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.stripe_request", stripe_request)
    response = _client(uuid.uuid4(), uuid.uuid4()).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "client-request-123"},
        json={"planKey": "scholar", "interval": "monthly"},
    )

    assert response.status_code == 503
    stripe_request.assert_not_awaited()


def test_checkout_does_not_accept_client_selected_prices_or_redirects(monkeypatch):
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: _test_settings())
    client = _client(uuid.uuid4(), uuid.uuid4())
    response = client.post(
        "/billing/checkout",
        headers={"Idempotency-Key": "client-request-123"},
        json={
            "planKey": "scholar",
            "interval": "monthly",
            "priceId": "price_attacker",
            "successUrl": "https://attacker.example",
        },
    )
    assert response.status_code == 422


def test_checkout_availability_never_exposes_keys_and_stays_disabled_without_enforcement(
    monkeypatch,
):
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _test_settings(BILLING_ENFORCEMENT_ENABLED=False),
    )
    response = _client(uuid.uuid4(), uuid.uuid4()).get("/billing/checkout-availability")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "plans": []}
