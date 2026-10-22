import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from research_api.billing.api import _monthly_period_bounds
from research_api.billing.razorpay import (
    RazorpayUnavailable,
    create_subscription,
    subscription_signature_valid,
)
from research_api.billing.subscriptions import (
    razorpay_subscriptions_available,
    subscription_plans,
)
from research_api.config import Settings


def _enabled_settings() -> Settings:
    return Settings(
        APP_ENV="test",
        BILLING_RAZORPAY_ENABLED=True,
        BILLING_SUBSCRIPTIONS_ENABLED=True,
        BILLING_ENFORCEMENT_ENABLED=True,
        RAZORPAY_KEY_ID="rzp_test_fixture123",
        RAZORPAY_KEY_SECRET=SecretStr("test-key-secret"),
        RAZORPAY_WEBHOOK_SECRET=SecretStr("test-webhook-secret"),
        RAZORPAY_PLAN_SCHOLAR_MONTHLY="plan_scholar_monthly",
        RAZORPAY_PLAN_INVESTIGATOR_MONTHLY="plan_investigator_monthly",
        RAZORPAY_PLAN_SCHOLAR_YEARLY="plan_scholar_yearly",
        RAZORPAY_PLAN_INVESTIGATOR_YEARLY="plan_investigator_yearly",
    )


def test_subscription_checkout_signature_uses_payment_id_then_subscription_id():
    secret = "razorpay-test-secret"  # noqa: S105
    message = "pay_fixture123|sub_fixture123"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    assert subscription_signature_valid(
        subscription_id="sub_fixture123",
        payment_id="pay_fixture123",
        signature=signature,
        secret=SecretStr(secret),
    )
    assert not subscription_signature_valid(
        subscription_id="sub_other123",
        payment_id="pay_fixture123",
        signature=signature,
        secret=SecretStr(secret),
    )


async def test_create_subscription_uses_preselected_plan_and_bounded_cycles(monkeypatch):
    request = AsyncMock(
        return_value={
            "id": "sub_fixture123",
            "plan_id": "plan_scholar_monthly",
            "total_count": 120,
            "quantity": 1,
            "status": "created",
        }
    )
    monkeypatch.setattr("research_api.billing.razorpay.razorpay_request", request)
    settings = _enabled_settings()

    result = await create_subscription(
        settings,
        plan_id="plan_scholar_monthly",
        total_count=120,
        notes={"checkout_attempt": "attempt-uuid"},
    )

    assert result["id"] == "sub_fixture123"
    request.assert_awaited_once_with(
        settings,
        "POST",
        "/subscriptions",
        payload={
            "plan_id": "plan_scholar_monthly",
            "total_count": 120,
            "quantity": 1,
            "customer_notify": True,
            "notes": {"checkout_attempt": "attempt-uuid"},
        },
    )


async def test_create_subscription_rejects_provider_plan_mismatch(monkeypatch):
    request = AsyncMock(
        return_value={
            "id": "sub_fixture123",
            "plan_id": "plan_wrong123",
            "total_count": 120,
            "quantity": 1,
            "status": "created",
        }
    )
    monkeypatch.setattr("research_api.billing.razorpay.razorpay_request", request)

    with pytest.raises(RazorpayUnavailable, match="unexpected subscription terms"):
        await create_subscription(
            _enabled_settings(),
            plan_id="plan_scholar_monthly",
            total_count=120,
            notes={},
        )


def test_subscription_plan_configuration_is_exact_and_disabled_by_default():
    settings = _enabled_settings()
    plans = subscription_plans(settings)
    assert plans[("scholar", "monthly")].amount_minor == 59900
    assert plans[("investigator", "monthly")].amount_minor == 129900
    assert plans[("scholar", "yearly")].amount_minor == 599900
    assert plans[("investigator", "yearly")].amount_minor == 1299900
    assert all(plan.currency == "INR" for plan in plans.values())
    assert not razorpay_subscriptions_available(Settings(APP_ENV="test"))
    assert razorpay_subscriptions_available(settings)
    assert not razorpay_subscriptions_available(
        settings.model_copy(update={"RAZORPAY_LIVEMODE": True})
    )


def test_annual_cycle_produces_twelve_nonoverlapping_monthly_allowance_periods():
    start = datetime(2028, 2, 29, tzinfo=UTC)
    end = datetime(2029, 2, 28, tzinfo=UTC)
    periods = _monthly_period_bounds("yearly", start, end)

    assert periods is not None
    assert len(periods) == 12
    assert periods[0][0] == start
    assert periods[-1][1] == end
    assert all(left[1] == right[0] for left, right in zip(periods, periods[1:], strict=False))
    assert _monthly_period_bounds("yearly", start, datetime(2029, 2, 27, tzinfo=UTC)) is None


def test_monthly_cycle_keeps_provider_period_boundaries():
    start = datetime(2026, 10, 21, tzinfo=UTC)
    end = datetime(2026, 11, 21, tzinfo=UTC)
    assert _monthly_period_bounds("monthly", start, end) == [(start, end)]


def test_annual_periods_are_rejected_when_provider_cycle_is_not_exactly_one_year():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert _monthly_period_bounds("yearly", start, datetime(2026, 12, 31, tzinfo=UTC)) is None
