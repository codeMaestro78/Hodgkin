"""Validated server-owned one-time research-credit pack configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from research_api.config import Settings

_PACKAGE_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_STRIPE_PRICE_ID = re.compile(r"^price_[A-Za-z0-9_]+$")
# This version identifies the exact locally approved product-policy contract.
# Customer-facing legal terms and fulfillment are still release gates.
CREDIT_TERMS_VERSION = "research-credit-terms-v1"
# The code path is enabled only for Stripe test mode. Live sales require a
# separate explicit release after finance/legal and production recovery review.
CREDIT_PURCHASE_RELEASE_READY = True


@dataclass(frozen=True)
class CreditPack:
    key: str
    price_id: str
    amount_minor: int
    currency: str
    units: int
    expiry_days: int | None


def configured_credit_packs(settings: Settings) -> dict[str, CreditPack]:
    """Parse a strict allowlist; invalid or absent configuration disables sales."""
    try:
        raw = json.loads(settings.BILLING_CREDIT_PACKS_JSON)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, list) or not 1 <= len(raw) <= 10:
        return {}

    packs: dict[str, CreditPack] = {}
    for item in raw:
        if not isinstance(item, dict) or set(item) != {
            "key",
            "priceId",
            "amountMinor",
            "currency",
            "units",
            "expiryDays",
        }:
            return {}
        key = item["key"]
        price_id = item["priceId"]
        amount = item["amountMinor"]
        currency = item["currency"]
        units = item["units"]
        expiry = item["expiryDays"]
        if (
            not isinstance(key, str)
            or _PACKAGE_KEY.fullmatch(key) is None
            or key in packs
            or not isinstance(price_id, str)
            or _STRIPE_PRICE_ID.fullmatch(price_id) is None
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or not 1 <= amount <= 2_147_483_647
            or not isinstance(currency, str)
            or currency != "usd"
            or isinstance(units, bool)
            or not isinstance(units, int)
            or not 1 <= units <= 1_000_000
            # Product policy: purchased units do not expire. Do not accept an
            # expiring package even when checkout is otherwise disabled.
            or expiry is not None
        ):
            return {}
        packs[key] = CreditPack(
            key=key,
            price_id=price_id,
            amount_minor=amount,
            currency=currency,
            units=units,
            expiry_days=expiry,
        )
    return packs


def credit_topups_available(settings: Settings) -> bool:
    """Fail closed until code and operator gates both authorize taking payment."""
    return bool(
        CREDIT_PURCHASE_RELEASE_READY
        and settings.BILLING_CREDIT_TOPUPS_ENABLED
        and settings.BILLING_CREDIT_TERMS_APPROVED
        and settings.BILLING_CREDIT_TERMS_VERSION == CREDIT_TERMS_VERSION
        and settings.BILLING_CREDIT_FULFILLMENT_ENABLED
        and settings.BILLING_CREDIT_SPENDING_ENABLED
        and settings.BILLING_CREDIT_MAX_WALLET_UNITS > 0
        and settings.BILLING_STRIPE_ENABLED
        and settings.BILLING_ENFORCEMENT_ENABLED
        and settings.STRIPE_WEBHOOK_SECRET
        and settings.STRIPE_API_VERSION
        and settings.STRIPE_SECRET_KEY
        and not settings.STRIPE_LIVEMODE
        and configured_credit_packs(settings)
    )
