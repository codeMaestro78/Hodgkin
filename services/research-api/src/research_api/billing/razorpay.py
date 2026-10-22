"""Razorpay Standard Checkout REST and signature helpers.

Only server-side code imports this module. Key secrets must never be projected to
the web client; the public key id may be returned as part of checkout options.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import SecretStr

from research_api.config import Settings

RAZORPAY_API = "https://api.razorpay.com/v1"
RAZORPAY_TIMEOUT = httpx.Timeout(8.0, connect=3.0, pool=1.0)
_RAZORPAY_ID = re.compile(r"^[A-Za-z0-9_]{8,64}$")
_SHA256_HEX = re.compile(r"^[a-fA-F0-9]{64}$")
SUPPORTED_CURRENCY_CODES = frozenset({"INR"})


class RazorpayUnavailable(RuntimeError):
    """Razorpay is not configured or did not return a valid response."""


def payment_signature_valid(
    *, order_id: str, payment_id: str, signature: str, secret: SecretStr | None
) -> bool:
    """Validate the Standard Checkout signature using the persisted order id."""
    if (
        secret is None
        or not _RAZORPAY_ID.fullmatch(order_id)
        or not _RAZORPAY_ID.fullmatch(payment_id)
        or not _SHA256_HEX.fullmatch(signature)
    ):
        return False
    expected = hmac.new(
        secret.get_secret_value().encode("utf-8"),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def subscription_signature_valid(
    *, subscription_id: str, payment_id: str, signature: str, secret: SecretStr | None
) -> bool:
    """Verify subscription Checkout using the persisted subscription identifier."""
    if (
        secret is None
        or not subscription_id.startswith("sub_")
        or not _RAZORPAY_ID.fullmatch(subscription_id)
        or not payment_id.startswith("pay_")
        or not _RAZORPAY_ID.fullmatch(payment_id)
        or not _SHA256_HEX.fullmatch(signature)
    ):
        return False
    expected = hmac.new(
        secret.get_secret_value().encode("utf-8"),
        f"{payment_id}|{subscription_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def webhook_signature_valid(*, body: bytes, signature: str, secret: SecretStr | None) -> bool:
    """Verify the exact raw webhook bytes using the separate webhook secret."""
    if secret is None or not _SHA256_HEX.fullmatch(signature):
        return False
    expected = hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def configured_key_id(settings: Settings) -> str:
    key_id = settings.RAZORPAY_KEY_ID
    secret = settings.RAZORPAY_KEY_SECRET
    if not key_id or not key_id.startswith(("rzp_test_", "rzp_live_")) or secret is None:
        raise RazorpayUnavailable("Razorpay is not configured")
    if key_id.startswith("rzp_live_") and not settings.BILLING_LIVE_LAUNCH_APPROVED:
        raise RazorpayUnavailable("Live Razorpay checkout has not been approved")
    if key_id.startswith("rzp_test_") and settings.RAZORPAY_LIVEMODE:
        raise RazorpayUnavailable("Razorpay key mode does not match configuration")
    if key_id.startswith("rzp_live_") and not settings.RAZORPAY_LIVEMODE:
        raise RazorpayUnavailable("Razorpay key mode does not match configuration")
    return key_id


async def razorpay_request(
    settings: Settings,
    method: str,
    path: str,
    *,
    payload: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Call a fixed Razorpay API path and reject redirects or malformed payloads."""
    configured_key_id(settings)
    secret = settings.RAZORPAY_KEY_SECRET
    if secret is None or not path.startswith("/") or ".." in path:
        raise RazorpayUnavailable("Razorpay request is not configured")
    try:
        async with httpx.AsyncClient(timeout=RAZORPAY_TIMEOUT, follow_redirects=False) as client:
            response = await client.request(
                method,
                f"{RAZORPAY_API}{path}",
                auth=(settings.RAZORPAY_KEY_ID or "", secret.get_secret_value()),
                json=dict(payload) if payload is not None else None,
            )
    except httpx.HTTPError as exc:
        raise RazorpayUnavailable("Razorpay request failed") from exc
    if response.is_redirect or response.status_code >= 400:
        raise RazorpayUnavailable("Razorpay rejected the request")
    try:
        result = response.json()
    except ValueError as exc:
        raise RazorpayUnavailable("Razorpay returned an invalid response") from exc
    if not isinstance(result, dict):
        raise RazorpayUnavailable("Razorpay returned an invalid response")
    return result


async def create_order(
    settings: Settings, *, amount_minor: int, currency: str, receipt: str
) -> dict[str, Any]:
    if isinstance(amount_minor, bool) or amount_minor < 100:
        raise ValueError("Razorpay order amount must be at least 100 minor currency units")
    if currency not in SUPPORTED_CURRENCY_CODES or not receipt or len(receipt) > 40:
        raise ValueError("Invalid Razorpay order terms")
    result = await razorpay_request(
        settings,
        "POST",
        "/orders",
        payload={"amount": amount_minor, "currency": currency, "receipt": receipt},
    )
    if (
        not isinstance(result.get("id"), str)
        or not _RAZORPAY_ID.fullmatch(result["id"])
        or result.get("amount") != amount_minor
        or result.get("currency") != currency
    ):
        raise RazorpayUnavailable("Razorpay returned an order with unexpected terms")
    return result


async def fetch_payment(settings: Settings, payment_id: str) -> dict[str, Any]:
    if not _RAZORPAY_ID.fullmatch(payment_id):
        raise RazorpayUnavailable("Invalid Razorpay payment id")
    return await razorpay_request(settings, "GET", f"/payments/{payment_id}")


async def fetch_plan(settings: Settings, plan_id: str) -> dict[str, Any]:
    if not plan_id.startswith("plan_") or not _RAZORPAY_ID.fullmatch(plan_id):
        raise RazorpayUnavailable("Invalid Razorpay plan id")
    return await razorpay_request(settings, "GET", f"/plans/{plan_id}")


async def create_subscription(
    settings: Settings, *, plan_id: str, total_count: int, notes: Mapping[str, str]
) -> dict[str, Any]:
    """Create one subscription against a preconfigured, server-selected plan."""
    if not plan_id.startswith("plan_") or not _RAZORPAY_ID.fullmatch(plan_id):
        raise ValueError("Invalid Razorpay plan id")
    if total_count not in {10, 120}:
        raise ValueError("Razorpay subscription cycle count is invalid")
    result = await razorpay_request(
        settings,
        "POST",
        "/subscriptions",
        payload={
            "plan_id": plan_id,
            "total_count": total_count,
            "quantity": 1,
            "customer_notify": True,
            "notes": dict(notes),
        },
    )
    subscription_id = result.get("id")
    if (
        not isinstance(subscription_id, str)
        or not subscription_id.startswith("sub_")
        or not _RAZORPAY_ID.fullmatch(subscription_id)
        or result.get("plan_id") != plan_id
        or result.get("total_count") != total_count
        or result.get("quantity") != 1
        or result.get("status") not in {"created", "authenticated", "active"}
    ):
        raise RazorpayUnavailable("Razorpay returned unexpected subscription terms")
    return result


async def fetch_subscription(settings: Settings, subscription_id: str) -> dict[str, Any]:
    if not subscription_id.startswith("sub_") or not _RAZORPAY_ID.fullmatch(subscription_id):
        raise RazorpayUnavailable("Invalid Razorpay subscription id")
    return await razorpay_request(settings, "GET", f"/subscriptions/{subscription_id}")


async def cancel_subscription(
    settings: Settings, *, subscription_id: str, cancel_at_cycle_end: bool = True
) -> dict[str, Any]:
    if not subscription_id.startswith("sub_") or not _RAZORPAY_ID.fullmatch(subscription_id):
        raise RazorpayUnavailable("Invalid Razorpay subscription id")
    return await razorpay_request(
        settings,
        "POST",
        f"/subscriptions/{subscription_id}/cancel",
        payload={"cancel_at_cycle_end": cancel_at_cycle_end},
    )
