import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_api.billing.api import router
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

    from research_api.billing.api import _operator_actor

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

    from research_api.billing.api import _operator_actor

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
            BILLING_OPERATOR_TOKENS=SecretStr(json.dumps({str(actor): "unique-token"})),
        ),
    )
    session = AsyncMock()

    @asynccontextmanager
    async def tenant_session(_tenant_id):
        yield session

    adjust = AsyncMock(return_value=SimpleNamespace(id=entry))
    monkeypatch.setattr("research_api.billing.api.tenant_session", tenant_session)
    monkeypatch.setattr("research_api.billing.api.adjust_units", adjust)

    response = TestClient(app).post(
        "/billing/adjustments",
        headers={"x-billing-operator-token": "unique-token"},
        json={
            "tenant_id": str(tenant),
            "user_id": str(user),
            "period_id": str(period),
            "delta": 1,
            "reason": "support adjustment",
            "idempotency_key": "operator-test-adjustment",
        },
    )
    assert response.status_code == 201
    assert response.json() == {"entryId": str(entry), "status": "recorded"}
    assert adjust.await_args.kwargs["actor_id"] == actor
