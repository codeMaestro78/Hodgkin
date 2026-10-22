"""Fail-closed Razorpay subscription catalog and recurring terms."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from research_api.billing.catalog import BILLING_CATALOG
from research_api.config import Settings

BillingPeriodKey = Literal["monthly", "yearly"]
PaidPlanKey = Literal["scholar", "investigator"]


@dataclass(frozen=True, slots=True)
class RazorpaySubscriptionPlan:
    key: PaidPlanKey
    period: BillingPeriodKey
    provider_plan_id: str
    amount_minor: int
    currency: str = "INR"


def _configured_id(settings: Settings, key: PaidPlanKey, period: BillingPeriodKey) -> str | None:
    name = f"RAZORPAY_PLAN_{key.upper()}_{period.upper()}"
    value = getattr(settings, name)
    return value if isinstance(value, str) and value.startswith("plan_") else None


def subscription_plans(
    settings: Settings,
) -> dict[tuple[PaidPlanKey, BillingPeriodKey], RazorpaySubscriptionPlan]:
    result: dict[tuple[PaidPlanKey, BillingPeriodKey], RazorpaySubscriptionPlan] = {}
    for key in ("scholar", "investigator"):
        terms = BILLING_CATALOG.plans[key]
        for period in ("monthly", "yearly"):
            provider_id = _configured_id(settings, key, period)
            price = terms.monthly_price if period == "monthly" else terms.annual_price
            if provider_id is None or price is None or terms.currency != "INR":
                continue
            result[(key, period)] = RazorpaySubscriptionPlan(
                key=key,
                period=period,
                provider_plan_id=provider_id,
                amount_minor=int(price * Decimal(100)),
            )
    return result


def razorpay_subscriptions_available(settings: Settings) -> bool:
    """Availability requires explicit test/live provider and recurring-billing gates."""
    if not (
        settings.BILLING_RAZORPAY_ENABLED
        and settings.BILLING_SUBSCRIPTIONS_ENABLED
        and settings.BILLING_ENFORCEMENT_ENABLED
        and settings.RAZORPAY_KEY_ID
        and settings.RAZORPAY_KEY_SECRET
        and settings.RAZORPAY_WEBHOOK_SECRET
    ):
        return False
    if settings.RAZORPAY_LIVEMODE and not settings.BILLING_LIVE_LAUNCH_APPROVED:
        return False
    if settings.RAZORPAY_KEY_ID.startswith("rzp_test_") and settings.RAZORPAY_LIVEMODE:
        return False
    if settings.RAZORPAY_KEY_ID.startswith("rzp_live_") != settings.RAZORPAY_LIVEMODE:
        return False
    return len(subscription_plans(settings)) == 4
