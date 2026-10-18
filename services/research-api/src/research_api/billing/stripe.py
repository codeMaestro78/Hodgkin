"""Small, bounded Stripe REST adapter; no Stripe SDK state is stored globally."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from research_api.billing.catalog import BILLING_CATALOG
from research_api.config import Settings

STRIPE_API = "https://api.stripe.com/v1"
STRIPE_TIMEOUT = httpx.Timeout(8.0, connect=3.0, pool=1.0)
STRIPE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class StripeUnavailable(RuntimeError):
    """Stripe is disabled, misconfigured, or did not return a safe response."""


def configured_prices(settings: Settings) -> dict[str, str]:
    prices = {
        "scholar": settings.STRIPE_PRICE_SCHOLAR_MONTHLY,
        "investigator": settings.STRIPE_PRICE_INVESTIGATOR_MONTHLY,
    }
    if not all(
        isinstance(price, str)
        and price.startswith("price_")
        and STRIPE_ID_PATTERN.fullmatch(price) is not None
        for price in prices.values()
    ):
        raise StripeUnavailable("monthly Stripe price IDs are not configured")
    return {key: price for key, price in prices.items() if price is not None}


def configured_portal(settings: Settings) -> str:
    value = settings.STRIPE_PORTAL_CONFIGURATION_ID
    if (
        not isinstance(value, str)
        or not value.startswith("bpc_")
        or STRIPE_ID_PATTERN.fullmatch(value) is None
    ):
        raise StripeUnavailable("Stripe portal configuration is not configured")
    return value


def validate_stripe_key_mode(settings: Settings) -> None:
    secret = settings.STRIPE_SECRET_KEY
    if secret is None:
        raise StripeUnavailable("Stripe secret key is not configured")
    key = secret.get_secret_value()
    expected_prefix = "sk_live_" if settings.STRIPE_LIVEMODE else "sk_test_"
    if not key.startswith(expected_prefix):
        raise StripeUnavailable("Stripe key mode does not match configured mode")
    if settings.STRIPE_LIVEMODE and not settings.BILLING_LIVE_LAUNCH_APPROVED:
        raise StripeUnavailable("live billing launch has not been approved")


def app_base_url(settings: Settings) -> str:
    raw = settings.BILLING_APP_BASE_URL
    if not raw:
        raise StripeUnavailable("billing return URL is not configured")
    parsed = urlsplit(raw)
    allowed_local = settings.APP_ENV in {"development", "test"} and parsed.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if (
        parsed.scheme != "https"
        and not (parsed.scheme == "http" and allowed_local)
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise StripeUnavailable("billing return URL is invalid")
    return raw.rstrip("/")


def stripe_idempotency_key(namespace: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"research-billing-v1:{namespace}:{digest}"


async def stripe_request(
    settings: Settings,
    method: str,
    path: str,
    *,
    form: Mapping[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    if not settings.BILLING_STRIPE_ENABLED or settings.STRIPE_SECRET_KEY is None:
        raise StripeUnavailable("Stripe billing is not enabled")
    validate_stripe_key_mode(settings)
    if not settings.STRIPE_API_VERSION:
        raise StripeUnavailable("a pinned Stripe API version is required")
    if not path.startswith("/") or ".." in path or "?" in path or "#" in path:
        raise StripeUnavailable("invalid Stripe resource path")
    headers = {
        "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY.get_secret_value()}",
        "Stripe-Version": settings.STRIPE_API_VERSION,
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=STRIPE_TIMEOUT, follow_redirects=False) as client:
            response = await client.request(
                method,
                f"{STRIPE_API}{path}",
                data=form,
                headers=headers,
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Do not propagate Stripe response bodies, authorization headers, or PII.
        raise StripeUnavailable("Stripe request failed") from exc
    if not isinstance(payload, dict):
        raise StripeUnavailable("Stripe returned an invalid response")
    return payload


async def validate_monthly_price(settings: Settings, *, plan_key: str, price_id: str) -> None:
    """Fail closed unless Stripe's configured Price matches the displayed offer."""
    plan = next(
        (item for key, item in BILLING_CATALOG.plans.items() if key == plan_key),
        None,
    )
    if plan is None or plan.key == "free":
        raise StripeUnavailable("unknown paid billing plan")
    payload = await stripe_request(settings, "GET", f"/prices/{price_id}")
    recurring = payload.get("recurring")
    expected_cents = int(plan.monthly_price_usd * 100)
    if (
        payload.get("id") != price_id
        or payload.get("active") is not True
        or payload.get("currency") != "usd"
        or payload.get("unit_amount") != expected_cents
        or not isinstance(recurring, dict)
        or recurring.get("interval") != "month"
        or recurring.get("interval_count") != 1
    ):
        raise StripeUnavailable("configured Stripe Price does not match the published offer")


def safe_session_url(payload: Mapping[str, object], *, portal: bool = False) -> str:
    value = payload.get("url")
    if not isinstance(value, str):
        raise StripeUnavailable("Stripe returned an unsafe hosted-session URL")
    expected_host = "billing.stripe.com" if portal else "checkout.stripe.com"
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise StripeUnavailable("Stripe returned an unsafe hosted-session URL")
    return value
