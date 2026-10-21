import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.auth import Caller
from research_api.billing.api import caller_dependency, router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[caller_dependency] = lambda: Caller(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
    )
    return TestClient(app)


def test_monthly_checkout_advertises_disabled_until_razorpay_subscriptions_exist():
    response = _client().get("/billing/checkout-availability")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "plans": []}


def test_monthly_checkout_is_retired():
    response = _client().post(
        "/billing/checkout",
        headers={"Idempotency-Key": "retired-route-request"},
        json={"planKey": "scholar", "interval": "monthly"},
    )

    assert response.status_code == 410


def test_subscription_management_is_retired():
    response = _client().post("/billing/portal")

    assert response.status_code == 410
