import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_api.auth import Caller
from research_api.billing import api
from research_api.billing.api import caller_dependency, router
from research_api.billing.razorpay import RazorpayUnavailable
from research_api.config import Settings


def _settings() -> Settings:
    return Settings(
        APP_ENV="test",
        BILLING_RAZORPAY_ENABLED=True,
        BILLING_SUBSCRIPTIONS_ENABLED=True,
        BILLING_ENFORCEMENT_ENABLED=True,
        RAZORPAY_KEY_ID="rzp_test_fixture123",
        RAZORPAY_KEY_SECRET=SecretStr("fixture-secret"),
        RAZORPAY_WEBHOOK_SECRET=SecretStr("webhook-fixture-secret"),
        RAZORPAY_PLAN_SCHOLAR_MONTHLY="plan_scholar_monthly",
        RAZORPAY_PLAN_INVESTIGATOR_MONTHLY="plan_investigator_monthly",
        RAZORPAY_PLAN_SCHOLAR_YEARLY="plan_scholar_yearly",
        RAZORPAY_PLAN_INVESTIGATOR_YEARLY="plan_investigator_yearly",
    )


def _client(caller: Caller) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: caller
    return TestClient(app)


def _subscription(**overrides: object) -> SimpleNamespace:
    values = {
        "subscription_id": "sub_fixture123",
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "plan_key": "scholar",
        "billing_period": "monthly",
        "status": "created",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _tenant_session(session):
    @asynccontextmanager
    async def context(_tenant_id):
        yield session

    return context


def test_checkout_retry_reuses_provider_confirmed_created_subscription(monkeypatch):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=caller.tenant_id,
        user_id=caller.user_id,
        plan_key="scholar",
        billing_period="monthly",
        state="created",
        subscription_id="sub_fixture123",
    )
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[None, attempt])
    monkeypatch.setattr(api, "get_settings", _settings)
    monkeypatch.setattr(api, "tenant_session", _tenant_session(session))
    fetch = AsyncMock(
        return_value={
            "id": "sub_fixture123",
            "plan_id": "plan_scholar_monthly",
            "status": "created",
        }
    )
    create = AsyncMock()
    monkeypatch.setattr(api, "fetch_razorpay_subscription", fetch)
    monkeypatch.setattr(api, "create_razorpay_subscription", create)

    response = _client(caller).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "new-browser-attempt-key"},
        json={"planKey": "scholar", "billingPeriod": "monthly"},
    )

    assert response.status_code == 201
    assert response.json()["subscriptionId"] == "sub_fixture123"
    fetch.assert_awaited_once_with(_settings(), "sub_fixture123")
    create.assert_not_awaited()


def test_failed_cancel_reconciles_confirmed_provider_cancellation(monkeypatch):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    subscription = _subscription(tenant_id=caller.tenant_id, user_id=caller.user_id)
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=subscription)
    monkeypatch.setattr(api, "get_settings", _settings)
    monkeypatch.setattr(api, "tenant_session", _tenant_session(session))
    cancel = AsyncMock(side_effect=RazorpayUnavailable("cancel response was uncertain"))
    fetch = AsyncMock(return_value={"id": "sub_fixture123", "status": "cancelled"})
    monkeypatch.setattr(api, "cancel_razorpay_subscription", cancel)
    monkeypatch.setattr(api, "fetch_razorpay_subscription", fetch)

    response = _client(caller).post(
        "/billing/checkout/cancel", json={"subscriptionId": "sub_fixture123"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "cancelled"}
    fetch.assert_awaited_once_with(_settings(), "sub_fixture123")
    assert session.execute.await_count >= 3


def test_unconfirmed_cancel_preserves_open_attempt(monkeypatch):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    subscription = _subscription(tenant_id=caller.tenant_id, user_id=caller.user_id)
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=subscription)
    monkeypatch.setattr(api, "get_settings", _settings)
    monkeypatch.setattr(api, "tenant_session", _tenant_session(session))
    monkeypatch.setattr(
        api,
        "cancel_razorpay_subscription",
        AsyncMock(side_effect=RazorpayUnavailable("cancel response uncertain")),
    )
    monkeypatch.setattr(
        api,
        "fetch_razorpay_subscription",
        AsyncMock(return_value={"id": "sub_fixture123", "status": "pending"}),
    )

    response = _client(caller).post(
        "/billing/checkout/cancel", json={"subscriptionId": "sub_fixture123"}
    )

    assert response.status_code == 503
    assert "attempt remains open" in response.json()["detail"].lower()
    # Only the transaction-local owner context is written; neither local state is released.
    assert session.execute.await_count == 1


def test_checkout_does_not_reuse_subscription_when_provider_reports_non_created_state(
    monkeypatch,
):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=caller.tenant_id,
        user_id=caller.user_id,
        plan_key="scholar",
        billing_period="monthly",
        state="created",
        subscription_id="sub_fixture123",
    )
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[None, attempt])
    monkeypatch.setattr(api, "get_settings", _settings)
    monkeypatch.setattr(api, "tenant_session", _tenant_session(session))
    monkeypatch.setattr(
        api,
        "fetch_razorpay_subscription",
        AsyncMock(
            return_value={
                "id": "sub_fixture123",
                "plan_id": "plan_scholar_monthly",
                "status": "authenticated",
            }
        ),
    )
    create = AsyncMock()
    monkeypatch.setattr(api, "create_razorpay_subscription", create)

    response = _client(caller).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "another-browser-attempt"},
        json={"planKey": "scholar", "billingPeriod": "monthly"},
    )

    assert response.status_code == 409
    assert "already processing" in response.json()["detail"].lower()
    create.assert_not_awaited()


def test_confirmed_terminal_retry_requires_a_fresh_deliberate_checkout(monkeypatch):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=caller.tenant_id,
        user_id=caller.user_id,
        plan_key="scholar",
        billing_period="monthly",
        state="created",
        subscription_id="sub_fixture123",
    )
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[None, attempt])
    monkeypatch.setattr(api, "get_settings", _settings)
    monkeypatch.setattr(api, "tenant_session", _tenant_session(session))
    monkeypatch.setattr(
        api,
        "fetch_razorpay_subscription",
        AsyncMock(
            return_value={
                "id": "sub_fixture123",
                "plan_id": "plan_scholar_monthly",
                "status": "cancelled",
            }
        ),
    )
    create = AsyncMock()
    monkeypatch.setattr(api, "create_razorpay_subscription", create)

    response = _client(caller).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "retry-terminal-attempt"},
        json={"planKey": "scholar", "billingPeriod": "monthly"},
    )

    assert response.status_code == 409
    assert "start a new checkout" in response.json()["detail"].lower()
    create.assert_not_awaited()


def test_terminal_idempotency_key_cannot_create_a_second_subscription(monkeypatch):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    terminal_attempt = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=caller.tenant_id,
        user_id=caller.user_id,
        plan_key="scholar",
        billing_period="monthly",
        state="failed",
        subscription_id="sub_fixture123",
    )
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=terminal_attempt)
    monkeypatch.setattr(api, "get_settings", _settings)
    monkeypatch.setattr(api, "tenant_session", _tenant_session(session))
    fetch = AsyncMock()
    create = AsyncMock()
    monkeypatch.setattr(api, "fetch_razorpay_subscription", fetch)
    monkeypatch.setattr(api, "create_razorpay_subscription", create)

    response = _client(caller).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "same-terminal-key"},
        json={"planKey": "scholar", "billingPeriod": "monthly"},
    )

    assert response.status_code == 409
    fetch.assert_not_awaited()
    create.assert_not_awaited()


def test_plan_verification_failure_is_safely_classified_and_stops_before_subscription_create(
    monkeypatch,
):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[None, None, None, None])
    session.add = Mock()
    event = Mock()
    monkeypatch.setattr(api, "get_settings", _settings)
    monkeypatch.setattr(api, "tenant_session", _tenant_session(session))
    monkeypatch.setattr(api, "operation_event", event)
    monkeypatch.setattr(
        api,
        "fetch_razorpay_plan",
        AsyncMock(
            return_value={
                "id": "plan_scholar_monthly",
                "period": "monthly",
                "interval": 1,
                "item": {"amount": 59901, "currency": "INR"},
            }
        ),
    )
    create = AsyncMock()
    monkeypatch.setattr(api, "create_razorpay_subscription", create)

    response = _client(caller).post(
        "/billing/checkout",
        headers={"Idempotency-Key": "plan-metadata-mismatch"},
        json={"planKey": "scholar", "billingPeriod": "monthly"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "The configured Razorpay plan could not be verified"
    create.assert_not_awaited()
    event.assert_called_once()
    event_args = event.call_args.kwargs
    assert event.call_args.args == ("razorpay.plan.verify",)
    assert event_args["verificationFailure"] == "plan_terms_mismatch"
    assert event_args["amountMatches"] is False
    assert event_args["currencyMatches"] is True
