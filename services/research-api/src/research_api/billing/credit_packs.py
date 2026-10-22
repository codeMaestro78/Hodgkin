"""Validated server-owned one-time research-credit pack configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from research_api.billing.razorpay import SUPPORTED_CURRENCY_CODES
from research_api.config import Settings

_PACKAGE_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
# This version identifies the exact locally approved product-policy contract.
# Customer-facing legal terms and fulfillment are still release gates.
CREDIT_TERMS_VERSION = "research-credit-terms-v1"
# Purchases remain fail-closed until the operator enables every policy gate.
CREDIT_PURCHASE_RELEASE_READY = True


@dataclass(frozen=True)
class RazorpayCreditPack:
    key: str
    amount_minor: int
    currency: str
    units: int
    expiry_days: int | None


def configured_razorpay_credit_packs(settings: Settings) -> dict[str, RazorpayCreditPack]:
    """Read a server-only single-currency catalog; clients never set prices."""
    try:
        raw = json.loads(settings.RAZORPAY_CREDIT_PACKS_JSON)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, list) or not 1 <= len(raw) <= 10:
        return {}
    packs: dict[str, RazorpayCreditPack] = {}
    catalog_currency: str | None = None
    for item in raw:
        if not isinstance(item, dict) or set(item) != {
            "key",
            "amountMinor",
            "currency",
            "units",
            "expiryDays",
        }:
            return {}
        key, amount, currency, units, expiry = (
            item["key"],
            item["amountMinor"],
            item["currency"],
            item["units"],
            item["expiryDays"],
        )
        if (
            not isinstance(key, str)
            or _PACKAGE_KEY.fullmatch(key) is None
            or key in packs
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or not 100 <= amount <= 2_147_483_647
            or currency not in SUPPORTED_CURRENCY_CODES
            or isinstance(units, bool)
            or not isinstance(units, int)
            or not 1 <= units <= 1_000_000
            or expiry is not None
        ):
            return {}
        if catalog_currency is not None and currency != catalog_currency:
            return {}
        catalog_currency = currency
        packs[key] = RazorpayCreditPack(key, amount, currency, units, expiry)
    return packs


def razorpay_credit_topups_available(settings: Settings) -> bool:
    """Require all existing wallet policy gates and explicit Razorpay opt-in."""
    from research_api.billing.razorpay import RazorpayUnavailable, configured_key_id

    try:
        configured_key_id(settings)
    except RazorpayUnavailable:
        return False
    packs = configured_razorpay_credit_packs(settings)
    return bool(
        settings.BILLING_RAZORPAY_ENABLED
        and settings.BILLING_ENFORCEMENT_ENABLED
        and settings.BILLING_CREDIT_TOPUPS_ENABLED
        and settings.BILLING_CREDIT_TERMS_APPROVED
        and settings.BILLING_CREDIT_TERMS_VERSION == CREDIT_TERMS_VERSION
        and settings.BILLING_CREDIT_FULFILLMENT_ENABLED
        and settings.BILLING_CREDIT_SPENDING_ENABLED
        and settings.BILLING_CREDIT_MAX_WALLET_UNITS > 0
        and settings.RAZORPAY_WEBHOOK_SECRET is not None
        and packs
        and all(pack.currency == "INR" for pack in packs.values())
    )
