import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from research_api.billing.stripe import (
    StripeUnavailable,
    app_base_url,
    configured_prices,
    safe_session_url,
    stripe_idempotency_key,
    validate_monthly_price,
    validate_stripe_key_mode,
)
from research_api.billing.subscriptions import apply_subscription_event
from research_api.config import Settings


def test_stripe_price_mapping_requires_both_server_owned_monthly_prices():
    settings = Settings(
        APP_ENV="test",
        STRIPE_PRICE_SCHOLAR_MONTHLY="price_scholar_test",
        STRIPE_PRICE_INVESTIGATOR_MONTHLY="price_investigator_test",
    )
    assert configured_prices(settings) == {
        "scholar": "price_scholar_test",
        "investigator": "price_investigator_test",
    }
    with pytest.raises(StripeUnavailable):
        configured_prices(Settings(APP_ENV="test"))


def test_billing_base_url_and_stripe_hosted_urls_are_allowlisted():
    assert app_base_url(Settings(APP_ENV="test", BILLING_APP_BASE_URL="http://localhost:3000"))
    with pytest.raises(StripeUnavailable):
        app_base_url(Settings(APP_ENV="production", BILLING_APP_BASE_URL="http://bad.example"))
    with pytest.raises(StripeUnavailable):
        safe_session_url({"url": "https://attacker.example/checkout"})
    assert safe_session_url({"url": "https://checkout.stripe.com/c/session"}).startswith(
        "https://checkout.stripe.com/"
    )
    assert safe_session_url({"url": "https://billing.stripe.com/session"}, portal=True).startswith(
        "https://billing.stripe.com/"
    )


def test_stripe_idempotency_key_is_fixed_length_and_does_not_include_user_input():
    key = stripe_idempotency_key("checkout", "sensitive/user/input")
    assert key.startswith("research-billing-v1:checkout:")
    assert "sensitive" not in key
    assert len(key) < 200


def test_stripe_secret_key_mode_fails_closed_including_live_without_approval():
    with pytest.raises(StripeUnavailable):
        validate_stripe_key_mode(
            Settings(APP_ENV="test", STRIPE_SECRET_KEY="sk_live_wrong_mode")  # noqa: S106
        )
    with pytest.raises(StripeUnavailable):
        validate_stripe_key_mode(
            Settings(
                APP_ENV="test",
                STRIPE_LIVEMODE=True,
                STRIPE_SECRET_KEY="sk_live_unapproved",  # noqa: S106
            )
        )
    validate_stripe_key_mode(
        Settings(APP_ENV="test", STRIPE_SECRET_KEY="sk_test_safe")  # noqa: S106
    )


@pytest.mark.asyncio
async def test_monthly_price_validation_checks_server_catalog_against_stripe(monkeypatch):
    settings = Settings(APP_ENV="test", STRIPE_SECRET_KEY="sk_test_safe")  # noqa: S106
    request = AsyncMock(
        return_value={
            "id": "price_scholar_test",
            "active": True,
            "currency": "usd",
            "unit_amount": 599,
            "recurring": {"interval": "month", "interval_count": 1},
        }
    )
    monkeypatch.setattr("research_api.billing.stripe.stripe_request", request)

    await validate_monthly_price(settings, plan_key="scholar", price_id="price_scholar_test")

    request.assert_awaited_once_with(settings, "GET", "/prices/price_scholar_test")
    request.return_value = {
        "id": "price_scholar_test",
        "active": True,
        "currency": "usd",
        "unit_amount": 59900,
        "recurring": {"interval": "year", "interval_count": 1},
    }
    with pytest.raises(StripeUnavailable):
        await validate_monthly_price(settings, plan_key="scholar", price_id="price_scholar_test")


@pytest.mark.asyncio
async def test_active_monthly_subscription_snapshot_grants_catalog_period_once(monkeypatch):
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    customer = SimpleNamespace(tenant_id=tenant_id, user_id=user_id)
    session = AsyncMock()
    session.add = Mock()
    session.scalar.side_effect = [customer, None, None]
    session.get.return_value = None
    grant = AsyncMock(return_value=SimpleNamespace(state="active"))
    monkeypatch.setattr("research_api.billing.subscriptions.ensure_period_grant", grant)
    settings = Settings(
        APP_ENV="test",
        STRIPE_LIVEMODE=False,
        STRIPE_PRICE_SCHOLAR_MONTHLY="price_scholar_test",
        STRIPE_PRICE_INVESTIGATOR_MONTHLY="price_investigator_test",
    )
    now = int(datetime.now(UTC).timestamp())
    event_time = datetime.fromtimestamp(now, UTC)
    obj = {
        "id": "sub_valid",
        "customer": "cus_valid",
        "status": "active",
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_scholar_test",
                        "active": True,
                        "currency": "usd",
                        "unit_amount": 599,
                        "recurring": {"interval": "month", "interval_count": 1},
                    },
                    "current_period_start": now,
                    "current_period_end": now + 30 * 86400,
                }
            ]
        },
    }

    result = await apply_subscription_event(
        session,
        event_id="evt_valid",
        event_created_at=event_time,
        event_type="customer.subscription.created",
        livemode=False,
        obj=obj,
        settings=settings,
    )

    assert result == "processed"
    grant.assert_awaited_once()
    assert grant.await_args.kwargs["plan_key"] == "scholar"
    assert grant.await_args.kwargs["tenant_id"] == tenant_id
    assert grant.await_args.kwargs["user_id"] == user_id


@pytest.mark.asyncio
async def test_unknown_price_and_wrong_livemode_never_grant_units(monkeypatch):
    customer = SimpleNamespace(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    session = AsyncMock()
    session.scalar.return_value = customer
    session.get.return_value = None
    grant = AsyncMock()
    monkeypatch.setattr("research_api.billing.subscriptions.ensure_period_grant", grant)
    settings = Settings(
        APP_ENV="test",
        STRIPE_PRICE_SCHOLAR_MONTHLY="price_scholar_test",
        STRIPE_PRICE_INVESTIGATOR_MONTHLY="price_investigator_test",
    )
    timestamp = int(datetime.now(UTC).timestamp())
    obj = {
        "id": "sub_bad",
        "customer": "cus_valid",
        "status": "active",
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_unknown",
                        "active": True,
                        "currency": "usd",
                        "unit_amount": 599,
                        "recurring": {"interval": "month", "interval_count": 1},
                    },
                    "current_period_start": timestamp,
                    "current_period_end": timestamp + 30 * 86400,
                }
            ]
        },
    }

    unknown_price = await apply_subscription_event(
        session,
        event_id="evt_bad_price",
        event_created_at=datetime.fromtimestamp(timestamp, UTC),
        event_type="customer.subscription.created",
        livemode=False,
        obj=obj,
        settings=settings,
    )
    wrong_mode = await apply_subscription_event(
        session,
        event_id="evt_live",
        event_created_at=datetime.fromtimestamp(timestamp + 1, UTC),
        event_type="customer.subscription.created",
        livemode=True,
        obj=obj,
        settings=settings,
    )
    assert unknown_price == wrong_mode == "reconciliation_required"
    grant.assert_not_awaited()
