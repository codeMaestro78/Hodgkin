import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_api.auth import Caller
from research_api.billing.api import caller_dependency, router
from research_api.config import Settings

TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=TENANT_ID, user_id=USER_ID
    )
    return TestClient(app)


def _settings() -> Settings:
    return Settings(
        APP_ENV="test",
        BILLING_RAZORPAY_ENABLED=True,
        BILLING_ENFORCEMENT_ENABLED=True,
        BILLING_CREDIT_TOPUPS_ENABLED=True,
        BILLING_CREDIT_TERMS_APPROVED=True,
        BILLING_CREDIT_TERMS_VERSION="research-credit-terms-v1",
        BILLING_CREDIT_FULFILLMENT_ENABLED=True,
        BILLING_CREDIT_SPENDING_ENABLED=True,
        BILLING_CREDIT_MAX_WALLET_UNITS=100,
        RAZORPAY_KEY_ID="rzp_test_fixture123",
        RAZORPAY_KEY_SECRET=SecretStr("fixture-secret"),
        RAZORPAY_CREDIT_PACKS_JSON=(
            '[{"key":"starter","amountMinor":100,"currency":"INR","units":5,"expiryDays":null}]'
        ),
    )


def test_verify_missing_callback_fields_returns_400(monkeypatch):
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)

    response = _client().post("/billing/credit-checkout/verify", json={})

    assert response.status_code == 400


def test_pending_credit_purchases_are_listed_with_resume_state(monkeypatch):
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        package_key="starter",
        amount_minor=19900,
        currency="INR",
        unit_grant=5,
        created_at=None,
        provider_order_id="order_fixture123",
        provider_order_state="created",
    )
    purchases_session = AsyncMock()
    purchases_session.scalar.return_value = True
    result = Mock()
    result.all.return_value = [purchase]
    purchases_session.scalars.return_value = result

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield purchases_session

    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    response = _client().get("/billing/credit-purchases")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "purchases": [
            {
                "purchaseId": str(purchase.id),
                "packageKey": "starter",
                "amountMinor": 19900,
                "currency": "INR",
                "units": 5,
                "createdAt": None,
                "orderId": "order_fixture123",
                "orderState": "created",
                "canResume": True,
            }
        ]
    }


def test_resume_existing_credit_purchase_returns_same_order(monkeypatch):
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=USER_ID,
        payment_provider="razorpay",
        state="pending",
        provider_order_state="created",
        provider_order_id="order_fixture123",
        amount_minor=19900,
        currency="INR",
        package_key="starter",
        unit_grant=5,
    )
    purchase_session = AsyncMock()
    purchase_session.scalar.side_effect = [True, purchase]

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield purchase_session

    provider_create = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = _client().post(f"/billing/credit-purchases/{purchase.id}/resume")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "purchaseId": str(purchase.id),
        "orderId": "order_fixture123",
        "amount": 19900,
        "currency": "INR",
        "keyId": "rzp_test_fixture123",
    }
    provider_create.assert_not_awaited()


def test_credit_purchase_resume_does_not_disclose_another_users_purchase(monkeypatch):
    purchase_session = AsyncMock()
    purchase_session.scalar.side_effect = [True, None]

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield purchase_session

    provider_create = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = _client().post(f"/billing/credit-purchases/{uuid.uuid4()}/resume")

    assert response.status_code == 404
    assert response.json()["detail"] == "Credit purchase not found"
    provider_create.assert_not_awaited()


def test_resume_not_started_credit_purchase_creates_one_order_for_that_purchase(monkeypatch):
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=USER_ID,
        payment_provider="razorpay",
        state="pending",
        provider_order_state="not_started",
        provider_order_id=None,
        amount_minor=19900,
        currency="INR",
        package_key="starter",
        unit_grant=5,
    )
    read_session, claim_session, save_session = AsyncMock(), AsyncMock(), AsyncMock()
    read_session.scalar.side_effect = [True, purchase]
    claim_session.scalar.return_value = purchase.id
    save_session.scalar.return_value = "order_fixture123"
    sessions = iter((read_session, claim_session, save_session))

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield next(sessions)

    provider_create = AsyncMock(return_value={"id": "order_fixture123"})
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = _client().post(f"/billing/credit-purchases/{purchase.id}/resume")

    assert response.status_code == 200, response.text
    assert response.json()["orderId"] == "order_fixture123"
    provider_create.assert_awaited_once_with(
        _settings(), amount_minor=19900, currency="INR", receipt=purchase.id.hex
    )


def test_uncertain_credit_purchase_cannot_create_a_replacement_order(monkeypatch):
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=USER_ID,
        payment_provider="razorpay",
        state="pending",
        provider_order_state="uncertain",
        provider_order_id=None,
        amount_minor=19900,
        currency="INR",
        package_key="starter",
        unit_grant=5,
    )
    purchase_session = AsyncMock()
    purchase_session.scalar.side_effect = [True, purchase]

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield purchase_session

    provider_create = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = _client().post(f"/billing/credit-purchases/{purchase.id}/resume")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This credit checkout needs reconciliation; no new order was created"
    )
    provider_create.assert_not_awaited()


def test_configured_credit_checkout_has_no_plan_gate_and_uses_server_pack(monkeypatch):
    currency, amount_minor = "INR", 100
    purchase_id = uuid.uuid4()
    purchase = SimpleNamespace(
        id=purchase_id,
        payment_provider="razorpay",
        provider_order_id=None,
        provider_order_state="not_started",
    )
    sessions = [AsyncMock(), AsyncMock(), AsyncMock()]
    for session, value in zip(sessions, (True, purchase_id, "order_fixture123"), strict=True):
        session.scalar.return_value = value

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield sessions.pop(0)

    pack = SimpleNamespace(
        key="starter", amount_minor=amount_minor, currency=currency, units=5, expiry_days=None
    )
    provider_create = AsyncMock(return_value={"id": "order_fixture123"})
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr(
        "research_api.billing.api.configured_razorpay_credit_packs", lambda _: {"starter": pack}
    )
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    begin_purchase = AsyncMock(return_value=purchase)
    monkeypatch.setattr("research_api.billing.api._begin_credit_purchase", begin_purchase)
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = _client().post(
        "/billing/credit-checkout",
        headers={"Idempotency-Key": "request-key-123"},
        json={"packageKey": "starter"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "purchaseId": str(purchase_id),
        "orderId": "order_fixture123",
        "amount": amount_minor,
        "currency": currency,
        "keyId": "rzp_test_fixture123",
    }
    # The authenticated caller has no plan/entitlement context on this route;
    # package availability is global and the account owns the resulting wallet.
    begin_purchase.assert_awaited_once()
    assert begin_purchase.await_args.args[0] == Caller(tenant_id=TENANT_ID, user_id=USER_ID)
    provider_create.assert_awaited_once_with(
        _settings(), amount_minor=amount_minor, currency=currency, receipt=purchase_id.hex
    )


def test_new_credit_checkout_is_blocked_until_pending_order_is_resolved(monkeypatch):
    account = SimpleNamespace(id=uuid.uuid4())
    schema_session, purchase_session = AsyncMock(), AsyncMock()
    schema_session.scalar.return_value = True
    purchase_session.scalar.side_effect = [account, None, 0, 0, 0, 1]
    sessions = iter((schema_session, purchase_session))

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield next(sessions)

    pack = SimpleNamespace(
        key="starter", amount_minor=19900, currency="INR", units=5, expiry_days=None
    )
    provider_create = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr(
        "research_api.billing.api.configured_razorpay_credit_packs", lambda _: {"starter": pack}
    )
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.ensure_default_free_period", AsyncMock())
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = _client().post(
        "/billing/credit-checkout",
        headers={"Idempotency-Key": "another-credit-request-123"},
        json={"packageKey": "starter"},
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Finish an existing credit checkout before starting another"
    provider_create.assert_not_awaited()


def test_order_claim_conflict_does_not_dispatch_second_provider_order(monkeypatch):
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        payment_provider="razorpay",
        provider_order_id=None,
        provider_order_state="creating",
    )
    sessions = [AsyncMock(), AsyncMock()]
    sessions[0].scalar.return_value = True
    sessions[1].scalar.return_value = None

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield sessions.pop(0)

    pack = SimpleNamespace(
        key="starter", amount_minor=100, currency="INR", units=5, expiry_days=None
    )
    provider_create = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr(
        "research_api.billing.api.configured_razorpay_credit_packs", lambda _: {"starter": pack}
    )
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr(
        "research_api.billing.api._begin_credit_purchase", AsyncMock(return_value=purchase)
    )
    monkeypatch.setattr("research_api.billing.api.create_razorpay_order", provider_create)

    response = _client().post(
        "/billing/credit-checkout",
        headers={"Idempotency-Key": "request-key-123"},
        json={"packageKey": "starter"},
    )

    assert response.status_code == 409
    provider_create.assert_not_awaited()


def test_invalid_signature_is_rejected_before_database_or_provider_access(monkeypatch):
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr("research_api.billing.api.payment_signature_valid", lambda **_: False)
    database = AsyncMock()
    provider = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.tenant_session", database)
    monkeypatch.setattr("research_api.billing.api.fetch_razorpay_payment", provider)

    response = _client().post(
        "/billing/credit-checkout/verify",
        json={
            "razorpay_payment_id": "pay_fixture123",
            "razorpay_order_id": "order_fixture123",
            "razorpay_signature": "0" * 64,
        },
    )

    assert response.status_code == 400
    database.assert_not_called()
    provider.assert_not_awaited()


def test_invalid_webhook_signature_is_rejected_before_database_access(monkeypatch):
    settings = _settings().model_copy(
        update={"RAZORPAY_WEBHOOK_SECRET": SecretStr("webhook-fixture")}
    )
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    monkeypatch.setattr("research_api.billing.api.webhook_signature_valid", lambda **_: False)
    database = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.system_session", database)

    response = _client().post(
        "/billing/webhooks/razorpay",
        headers={"x-razorpay-event-id": "evt_fixture", "x-razorpay-signature": "0" * 64},
        content=b'{"event":"payment.captured"}',
    )

    assert response.status_code == 400
    database.assert_not_called()


def test_signed_captured_webhook_grants_exact_pack_once(monkeypatch):
    currency, amount_minor = "INR", 100
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        billing_account_id=uuid.uuid4(),
        state="pending",
        provider_order_state="created",
        provider_order_id="order_fixture123",
        provider_payment_id=None,
        amount_minor=amount_minor,
        currency=currency,
        unit_grant=5,
    )
    session = AsyncMock()
    session.scalar.side_effect = ["evt_fixture", purchase]
    session.add = Mock()

    @asynccontextmanager
    async def system_session():
        yield session

    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _settings().model_copy(
            update={"RAZORPAY_WEBHOOK_SECRET": SecretStr("webhook-fixture")}
        ),
    )
    monkeypatch.setattr("research_api.billing.api.system_session", system_session)
    monkeypatch.setattr("research_api.billing.api.webhook_signature_valid", lambda **_: True)

    response = _client().post(
        "/billing/webhooks/razorpay",
        headers={"x-razorpay-event-id": "evt_fixture", "x-razorpay-signature": "a" * 64},
        json={
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_fixture123",
                        "order_id": "order_fixture123",
                        "amount": amount_minor,
                        "currency": currency,
                        "status": "captured",
                    }
                }
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "received": True,
        "duplicate": False,
        "eventId": "evt_fixture",
    }
    assert purchase.state == "paid"
    assert purchase.provider_payment_id == "pay_fixture123"
    grant = session.add.call_args.args[0]
    assert grant.entry_type == "grant"
    assert grant.available_delta == 5
    assert grant.idempotency_key == f"credit-grant:{purchase.id}"


def test_captured_exact_order_is_credited_once_after_provider_confirmation(monkeypatch):
    purchase_id = uuid.uuid4()
    purchase = SimpleNamespace(
        id=purchase_id,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        billing_account_id=uuid.uuid4(),
        state="pending",
        provider_order_state="created",
        provider_order_id="order_fixture123",
        provider_payment_id=None,
        amount_minor=100,
        currency="INR",
        unit_grant=5,
    )
    session = AsyncMock()
    session.scalar.return_value = purchase
    session.add = Mock()

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield session

    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr("research_api.billing.api.payment_signature_valid", lambda **_: True)
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr(
        "research_api.billing.api.fetch_razorpay_payment",
        AsyncMock(
            return_value={
                "id": "pay_fixture123",
                "order_id": "order_fixture123",
                "amount": 100,
                "currency": "INR",
                "status": "captured",
            }
        ),
    )

    response = _client().post(
        "/billing/credit-checkout/verify",
        json={
            "razorpay_payment_id": "pay_fixture123",
            "razorpay_order_id": "order_fixture123",
            "razorpay_signature": "a" * 64,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "paid"}
    assert purchase.state == "paid"
    assert purchase.provider_payment_id == "pay_fixture123"
    grant = session.add.call_args.args[0]
    assert grant.entry_type == "grant"
    assert grant.available_delta == 5
    assert grant.idempotency_key == f"credit-grant:{purchase_id}"


def test_verified_payment_retry_replays_paid_without_refetch_or_second_grant(monkeypatch):
    purchase = SimpleNamespace(
        id=uuid.uuid4(),
        state="paid",
        provider_order_state="created",
        provider_order_id="order_fixture123",
        provider_payment_id="pay_fixture123",
    )
    session = AsyncMock()
    session.scalar.return_value = purchase

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield session

    provider_fetch = AsyncMock()
    monkeypatch.setattr("research_api.billing.api.get_settings", _settings)
    monkeypatch.setattr("research_api.billing.api.razorpay_credit_topups_available", lambda _: True)
    monkeypatch.setattr("research_api.billing.api.payment_signature_valid", lambda **_: True)
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.fetch_razorpay_payment", provider_fetch)

    response = _client().post(
        "/billing/credit-checkout/verify",
        json={
            "razorpay_payment_id": "pay_fixture123",
            "razorpay_order_id": "order_fixture123",
            "razorpay_signature": "a" * 64,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "paid"}
    provider_fetch.assert_not_awaited()
    session.add.assert_not_called()


def test_webhook_event_retry_does_not_grant_twice(monkeypatch):
    event = SimpleNamespace(processing_status="processed")
    session = AsyncMock()
    session.scalar.side_effect = [None, event]

    @asynccontextmanager
    async def system_session():
        yield session

    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: _settings().model_copy(
            update={"RAZORPAY_WEBHOOK_SECRET": SecretStr("webhook-fixture")}
        ),
    )
    monkeypatch.setattr("research_api.billing.api.system_session", system_session)
    monkeypatch.setattr("research_api.billing.api.webhook_signature_valid", lambda **_: True)

    response = _client().post(
        "/billing/webhooks/razorpay",
        headers={"x-razorpay-event-id": "evt_fixture", "x-razorpay-signature": "a" * 64},
        json={
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_fixture123",
                        "order_id": "order_fixture123",
                        "amount": 100,
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "duplicate": True}
    session.add.assert_not_called()
