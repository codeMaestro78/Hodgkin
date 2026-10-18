import hashlib
import hmac
import json
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_api.billing.api import _operator_actor, router
from research_api.config import Settings


def test_operator_adjustment_identity_comes_from_configured_token_not_request_body(monkeypatch):
    actor = uuid.uuid4()
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: Settings(
            APP_ENV="test",
            BILLING_OPERATOR_TOKENS=SecretStr(json.dumps({str(actor): "unique-test-token"})),
        ),
    )

    assert _operator_actor("unique-test-token") == actor


def test_invalid_or_ambiguous_operator_credentials_fail_closed(monkeypatch):
    first, second = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: Settings(
            APP_ENV="test",
            BILLING_OPERATOR_TOKENS=SecretStr(
                json.dumps({str(first): "shared", str(second): "shared"})
            ),
        ),
    )

    from fastapi import HTTPException

    try:
        _operator_actor("shared")
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("ambiguous operator token was accepted")


def test_adjustment_route_uses_server_authenticated_actor(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    actor, tenant, user, period, entry = (uuid.uuid4() for _ in range(5))
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: Settings(
            APP_ENV="test",
            BILLING_OPERATOR_TOKENS=SecretStr(json.dumps({str(actor): "operator-token"})),
        ),
    )
    session = AsyncMock()

    @asynccontextmanager
    async def fake_tenant_session(_tenant_id):
        yield session

    adjust = AsyncMock(return_value=SimpleNamespace(id=entry))
    monkeypatch.setattr("research_api.billing.api.tenant_session", fake_tenant_session)
    monkeypatch.setattr("research_api.billing.api.adjust_units", adjust)
    response = TestClient(app).post(
        "/billing/adjustments",
        json={
            "tenant_id": str(tenant),
            "user_id": str(user),
            "period_id": str(period),
            "delta": -1,
            "idempotency_key": "support-adjust-01",
            "reason": "Reverse duplicate settlement",
        },
        headers={"X-Billing-Operator-Token": "operator-token"},
    )

    assert response.status_code == 201, response.text
    assert response.json() == {"entryId": str(entry), "status": "recorded"}
    assert adjust.await_args.kwargs["actor_id"] == actor


def test_stripe_webhook_rejects_unsigned_events_without_database_access(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: Settings(APP_ENV="test", STRIPE_WEBHOOK_SECRET=SecretStr("whsec_test")),
    )
    db = AsyncMock()

    @asynccontextmanager
    async def forbidden_database():
        raise AssertionError("unsigned Stripe payload reached persistence")
        yield db

    monkeypatch.setattr("research_api.billing.api.system_session", forbidden_database)
    response = TestClient(app).post(
        "/billing/webhooks/stripe",
        content=b'{"id":"evt_unsafe","type":"invoice.paid"}',
        headers={"Stripe-Signature": "t=1,v1=bad"},
    )

    assert response.status_code == 400


def test_stripe_webhook_persists_only_signed_minimal_event_and_deduplicates(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    signing_key = "whsec_test_endpoint"
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: Settings(APP_ENV="test", STRIPE_WEBHOOK_SECRET=SecretStr(signing_key)),
    )
    session = AsyncMock()
    session.scalar.side_effect = ["evt_test_123", None]

    @asynccontextmanager
    async def fake_system_session():
        yield session

    monkeypatch.setattr("research_api.billing.api.system_session", fake_system_session)
    body = json.dumps(
        {
            "id": "evt_test_123",
            "type": "invoice.paid",
            "created": int(time.time()),
            "livemode": False,
            "data": {"object": {"id": "in_test_123", "customer_email": "not-stored@example.com"}},
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        signing_key.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()

    client = TestClient(app)
    headers = {"Stripe-Signature": f"t={timestamp},v1={digest}"}
    first = client.post("/billing/webhooks/stripe", content=body, headers=headers)
    replay = client.post("/billing/webhooks/stripe", content=body, headers=headers)

    assert first.status_code == replay.status_code == 202
    assert first.json() == {"received": True, "duplicate": False, "eventId": "evt_test_123"}
    assert replay.json() == {"received": True, "duplicate": True, "eventId": "evt_test_123"}
    assert session.scalar.await_count == 2
    insert_statement = session.scalar.await_args.args[0]
    compiled = str(insert_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "not-stored@example.com" not in compiled


def test_signed_malformed_event_envelopes_are_rejected_without_persistence(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    signing_key = "whsec_test_endpoint"
    monkeypatch.setattr(
        "research_api.billing.api.get_settings",
        lambda: Settings(APP_ENV="test", STRIPE_WEBHOOK_SECRET=SecretStr(signing_key)),
    )

    @asynccontextmanager
    async def forbidden_database():
        raise AssertionError("invalid Stripe event reached persistence")
        yield AsyncMock()

    monkeypatch.setattr("research_api.billing.api.system_session", forbidden_database)
    timestamp = str(int(time.time()))
    malformed = (
        b"[]",
        json.dumps(
            {
                "id": "evt_missing_mode",
                "type": "invoice.paid",
                "created": int(timestamp),
                "data": {"object": {"id": "in_test"}},
            }
        ).encode(),
        json.dumps(
            {
                "id": "evt_bad_time",
                "type": "invoice.paid",
                "created": 10**100,
                "livemode": False,
                "data": {"object": {"id": "in_test"}},
            }
        ).encode(),
    )
    client = TestClient(app)
    for body in malformed:
        digest = hmac.new(
            signing_key.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        response = client.post(
            "/billing/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
        )
        assert response.status_code == 400


def test_reconciliation_webhook_is_reprocessed_on_signed_stripe_retry(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    signing_key = "whsec_test_endpoint"
    settings = Settings(
        APP_ENV="test",
        BILLING_STRIPE_ENABLED=True,
        BILLING_ENFORCEMENT_ENABLED=True,
        STRIPE_SECRET_KEY=SecretStr("sk_test_key"),
        STRIPE_WEBHOOK_SECRET=SecretStr(signing_key),
        STRIPE_API_VERSION="2025-03-31.basil",
        STRIPE_PRICE_SCHOLAR_MONTHLY="price_scholar_test",
        STRIPE_PRICE_INVESTIGATOR_MONTHLY="price_investigator_test",
        STRIPE_PORTAL_CONFIGURATION_ID="bpc_test_configuration",
        BILLING_APP_BASE_URL="http://localhost:3000",
    )
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    session = AsyncMock()
    session.scalar.side_effect = [
        "evt_subscription_123",
        None,
        SimpleNamespace(processing_status="reconciliation_required"),
    ]
    apply_event = AsyncMock(side_effect=["reconciliation_required", "processed"])

    @asynccontextmanager
    async def fake_system_session():
        yield session

    monkeypatch.setattr("research_api.billing.api.system_session", fake_system_session)
    monkeypatch.setattr("research_api.billing.api.apply_subscription_event", apply_event)
    body = json.dumps(
        {
            "id": "evt_subscription_123",
            "type": "customer.subscription.updated",
            "api_version": "2025-03-31.basil",
            "created": int(time.time()),
            "livemode": False,
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_123",
                    "status": "active",
                }
            },
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        signing_key.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    client = TestClient(app)

    first = client.post(
        "/billing/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
    )
    retry = client.post(
        "/billing/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
    )

    assert first.status_code == 503
    assert retry.status_code == 202
    assert retry.json()["duplicate"] is True
    assert apply_event.await_count == 2


def test_relevant_event_with_wrong_api_version_is_not_applied(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    signing_key = "whsec_test_endpoint"
    settings = Settings(
        APP_ENV="test",
        BILLING_STRIPE_ENABLED=True,
        BILLING_ENFORCEMENT_ENABLED=True,
        STRIPE_SECRET_KEY=SecretStr("sk_test_key"),
        STRIPE_WEBHOOK_SECRET=SecretStr(signing_key),
        STRIPE_API_VERSION="2025-03-31.basil",
        STRIPE_PRICE_SCHOLAR_MONTHLY="price_scholar_test",
        STRIPE_PRICE_INVESTIGATOR_MONTHLY="price_investigator_test",
        STRIPE_PORTAL_CONFIGURATION_ID="bpc_test_configuration",
        BILLING_APP_BASE_URL="http://localhost:3000",
    )
    monkeypatch.setattr("research_api.billing.api.get_settings", lambda: settings)
    session = AsyncMock()
    session.scalar.side_effect = ["evt_wrong_api_version", None]
    apply_event = AsyncMock()

    @asynccontextmanager
    async def fake_system_session():
        yield session

    monkeypatch.setattr("research_api.billing.api.system_session", fake_system_session)
    monkeypatch.setattr("research_api.billing.api.apply_subscription_event", apply_event)
    body = json.dumps(
        {
            "id": "evt_wrong_api_version",
            "type": "customer.subscription.updated",
            "api_version": "2024-06-20",
            "created": int(time.time()),
            "livemode": False,
            "data": {"object": {"id": "sub_123", "customer": "cus_123", "status": "active"}},
        },
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        signing_key.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()

    response = TestClient(app).post(
        "/billing/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
    )

    assert response.status_code == 503
    apply_event.assert_not_awaited()
