"""Billing read, operator and public signed-webhook endpoints."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from research_api.auth import Caller, authenticated_caller
from research_api.billing.credit_packs import configured_credit_packs, credit_topups_available
from research_api.billing.credits import (
    apply_credit_checkout,
    apply_credit_reversal,
    credit_balance,
    wallet_frozen,
)
from research_api.billing.entitlements import read_entitlement
from research_api.billing.ledger import (
    BillingAdjustmentConflict,
    BillingAdjustmentUnavailable,
    BillingConfigurationUnavailable,
    adjust_units,
    ensure_default_free_period,
)
from research_api.billing.lifecycle import stripe_signature_valid
from research_api.billing.stripe import (
    STRIPE_ID_PATTERN,
    StripeUnavailable,
    app_base_url,
    configured_portal,
    configured_prices,
    safe_session_url,
    stripe_idempotency_key,
    stripe_request,
    validate_credit_price,
    validate_monthly_price,
)
from research_api.billing.subscriptions import apply_checkout_event, apply_subscription_event
from research_api.config import Settings, get_settings
from research_api.db.models import (
    BillingAccount,
    BillingCreditEntry,
    BillingCreditPurchase,
    StripeCheckoutAttempt,
    StripeCustomerLink,
    StripeSubscription,
    StripeWebhookEvent,
)
from research_api.db.session import system_session, tenant_session
from research_api.schemas.generated.billing_entitlement import BillingEntitlement

router = APIRouter(prefix="/billing", tags=["billing"])


async def caller_dependency(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> Caller:
    return await authenticated_caller(
        get_settings(), x_internal_service_auth, authorization=authorization
    )


CallerDep = Annotated[Caller, Depends(caller_dependency)]


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    plan_key: Literal["scholar", "investigator"] = Field(alias="planKey")
    interval: Literal["monthly"] = "monthly"


class CreditCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    package_key: str = Field(alias="packageKey", min_length=1, max_length=64)


@router.get("/checkout-availability")
async def checkout_availability() -> dict[str, object]:
    """Expose only purchase availability and plan keys; never expose Stripe secrets."""
    settings = get_settings()
    if (
        not settings.BILLING_STRIPE_ENABLED
        or not settings.BILLING_ENFORCEMENT_ENABLED
        or (settings.STRIPE_LIVEMODE and not settings.BILLING_LIVE_LAUNCH_APPROVED)
        or settings.STRIPE_WEBHOOK_SECRET is None
        or not settings.STRIPE_API_VERSION
    ):
        return {"enabled": False, "plans": []}
    try:
        plans = sorted(configured_prices(settings))
        configured_portal(settings)
        app_base_url(settings)
    except StripeUnavailable:
        return {"enabled": False, "plans": []}
    return {"enabled": bool(settings.STRIPE_SECRET_KEY), "plans": plans}


@router.get("/credit-packs")
async def list_credit_packs(caller: CallerDep) -> dict[str, object]:
    """List authenticated, server-configured packs without exposing Stripe Price IDs."""
    settings = get_settings()
    enabled = credit_topups_available(settings)
    if enabled:
        async with tenant_session(str(caller.tenant_id)) as session:
            enabled = bool(
                await session.scalar(
                    text("SELECT to_regclass('public.billing_credit_purchases') IS NOT NULL")
                )
            )
    packs = configured_credit_packs(settings) if enabled else {}
    return {
        "enabled": enabled,
        "currency": "usd",
        "packs": [
            {
                "key": item.key,
                "amountMinor": item.amount_minor,
                "units": item.units,
                "expiryDays": item.expiry_days,
            }
            for item in packs.values()
        ],
    }


@router.get("/credit-balance")
async def read_credit_balance(caller: CallerDep) -> dict[str, object]:
    """Owner-scoped purchased balance; never conflated with monthly entitlement."""
    async with tenant_session(str(caller.tenant_id)) as session:
        schema_ready = await session.scalar(
            text("SELECT to_regclass('public.billing_credit_entries') IS NOT NULL")
        )
        if not schema_ready:
            return {"enabled": False}
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        account_id = await session.scalar(
            select(BillingAccount.id).where(
                BillingAccount.tenant_id == caller.tenant_id,
                BillingAccount.user_id == caller.user_id,
            )
        )
        if account_id is None:
            return {
                "enabled": True,
                "availableUnits": 0,
                "reservedUnits": 0,
                "frozen": False,
            }
        available, reserved = await credit_balance(
            session, tenant_id=caller.tenant_id, account_id=account_id
        )
        frozen = await wallet_frozen(session, tenant_id=caller.tenant_id, account_id=account_id)
        return {
            "enabled": True,
            "availableUnits": available,
            "reservedUnits": reserved,
            "frozen": frozen,
        }


@router.get("/credit-purchases/{session_id}")
async def read_credit_purchase(session_id: str, caller: CallerDep) -> dict[str, str]:
    """Check the owner-scoped fulfillment state; the redirect is never authoritative."""
    if not session_id.startswith("cs_") or STRIPE_ID_PATTERN.fullmatch(session_id) is None:
        raise HTTPException(404, "Credit purchase not found")
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        purchase = await session.scalar(
            select(BillingCreditPurchase)
            .join(BillingAccount, BillingAccount.id == BillingCreditPurchase.billing_account_id)
            .where(
                BillingCreditPurchase.tenant_id == caller.tenant_id,
                BillingCreditPurchase.stripe_checkout_session_id == session_id,
                BillingAccount.user_id == caller.user_id,
            )
        )
        if purchase is None:
            raise HTTPException(404, "Credit purchase not found")
        return {"status": purchase.state}


async def _stripe_customer_for(caller: Caller, settings: Settings) -> str:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        existing = await session.scalar(
            select(StripeCustomerLink).where(
                StripeCustomerLink.tenant_id == caller.tenant_id,
                StripeCustomerLink.user_id == caller.user_id,
            )
        )
    if existing is not None:
        return existing.stripe_customer_id

    customer = await stripe_request(
        settings,
        "POST",
        "/customers",
        form={
            "metadata[tenant_id]": str(caller.tenant_id),
            "metadata[user_id]": str(caller.user_id),
        },
        idempotency_key=stripe_idempotency_key("customer", f"{caller.tenant_id}:{caller.user_id}"),
    )
    customer_id = customer.get("id")
    if (
        not isinstance(customer_id, str)
        or not customer_id.startswith("cus_")
        or STRIPE_ID_PATTERN.fullmatch(customer_id) is None
    ):
        raise StripeUnavailable("Stripe returned an invalid Customer")
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        await session.execute(
            insert(StripeCustomerLink)
            .values(
                stripe_customer_id=customer_id,
                tenant_id=caller.tenant_id,
                user_id=caller.user_id,
            )
            .on_conflict_do_nothing(
                index_elements=[StripeCustomerLink.tenant_id, StripeCustomerLink.user_id]
            )
        )
        saved = await session.scalar(
            select(StripeCustomerLink).where(
                StripeCustomerLink.tenant_id == caller.tenant_id,
                StripeCustomerLink.user_id == caller.user_id,
            )
        )
        if saved is None:
            raise StripeUnavailable("Stripe Customer mapping could not be persisted")
        return saved.stripe_customer_id


async def _begin_credit_purchase(
    caller: Caller,
    *,
    pack_key: str,
    request_key: str,
    amount_minor: int,
    price_id: str,
    units: int,
    currency: str,
    terms_version: str,
    max_wallet_units: int,
) -> BillingCreditPurchase:
    """Persist immutable purchase terms before Stripe; retries reuse the same order."""
    key_hash = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
    stable_key = stripe_idempotency_key(
        "credit-checkout", f"{caller.tenant_id}:{caller.user_id}:{request_key}"
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        await ensure_default_free_period(
            session, tenant_id=caller.tenant_id, user_id=caller.user_id
        )
        account = await session.scalar(
            select(BillingAccount).where(
                BillingAccount.tenant_id == caller.tenant_id,
                BillingAccount.user_id == caller.user_id,
            )
        )
        if account is None:
            raise HTTPException(503, "Credit checkout is temporarily unavailable")
        lock_name = f"billing-credit-checkout-v1:{caller.tenant_id}:{account.id}"
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(lock_name, 0)))
        )
        purchase = await session.scalar(
            select(BillingCreditPurchase).where(
                BillingCreditPurchase.tenant_id == caller.tenant_id,
                BillingCreditPurchase.billing_account_id == account.id,
                BillingCreditPurchase.request_key_hash == key_hash,
            )
        )
        if purchase is None:
            if units > max_wallet_units:
                raise HTTPException(422, "This pack exceeds the configured wallet limit")
            recent_count = await session.scalar(
                select(func.count(BillingCreditPurchase.id)).where(
                    BillingCreditPurchase.tenant_id == caller.tenant_id,
                    BillingCreditPurchase.billing_account_id == account.id,
                    BillingCreditPurchase.created_at >= datetime.now(UTC) - timedelta(days=1),
                )
            )
            if int(recent_count or 0) >= 5:
                raise HTTPException(429, "Daily research-credit purchase limit reached")
            wallet_balance = await session.scalar(
                select(
                    func.coalesce(
                        func.sum(
                            # Available plus reserved equals the unspent wallet balance.
                            # Both deltas are append-only; the ledger remains the authority.
                            func.coalesce(BillingCreditEntry.available_delta, 0)
                            + func.coalesce(BillingCreditEntry.reserved_delta, 0)
                        ),
                        0,
                    )
                ).where(
                    BillingCreditEntry.tenant_id == caller.tenant_id,
                    BillingCreditEntry.billing_account_id == account.id,
                )
            )
            pending_units = await session.scalar(
                select(func.coalesce(func.sum(BillingCreditPurchase.unit_grant), 0)).where(
                    BillingCreditPurchase.tenant_id == caller.tenant_id,
                    BillingCreditPurchase.billing_account_id == account.id,
                    BillingCreditPurchase.state == "pending",
                )
            )
            pending_count = await session.scalar(
                select(func.count(BillingCreditPurchase.id)).where(
                    BillingCreditPurchase.tenant_id == caller.tenant_id,
                    BillingCreditPurchase.billing_account_id == account.id,
                    BillingCreditPurchase.state == "pending",
                )
            )
            if int(pending_count or 0) >= 2:
                raise HTTPException(
                    429, "Finish an existing credit checkout before starting another"
                )
            if int(wallet_balance or 0) + int(pending_units or 0) + units > max_wallet_units:
                raise HTTPException(
                    409,
                    "The configured research-credit wallet limit would be exceeded",
                )
            purchase_id = uuid.uuid4()
            await session.execute(
                insert(BillingCreditPurchase)
                .values(
                    id=purchase_id,
                    tenant_id=caller.tenant_id,
                    billing_account_id=account.id,
                    user_id=caller.user_id,
                    package_key=pack_key,
                    stripe_price_id=price_id,
                    request_key_hash=key_hash,
                    stripe_idempotency_key=stable_key,
                    terms_version=terms_version,
                    amount_minor=amount_minor,
                    currency=currency.upper(),
                    unit_grant=units,
                    state="pending",
                )
                .on_conflict_do_nothing(constraint="uq_billing_credit_purchase_request_key")
            )
            purchase = await session.scalar(
                select(BillingCreditPurchase).where(
                    BillingCreditPurchase.tenant_id == caller.tenant_id,
                    BillingCreditPurchase.billing_account_id == account.id,
                    BillingCreditPurchase.request_key_hash == key_hash,
                )
            )
        if purchase is None:
            raise HTTPException(503, "Credit checkout is temporarily unavailable")
        if (
            purchase.user_id != caller.user_id
            or purchase.billing_account_id != account.id
            or purchase.package_key != pack_key
            or purchase.stripe_price_id != price_id
            or purchase.amount_minor != amount_minor
            or purchase.currency != currency.upper()
            or purchase.unit_grant != units
            or purchase.terms_version != terms_version
        ):
            raise HTTPException(409, "Checkout idempotency key was used for different terms")
        if purchase.state != "pending":
            raise HTTPException(409, "This credit purchase is no longer payable")
        if purchase.stripe_idempotency_key != stable_key:
            raise HTTPException(409, "Credit checkout idempotency record is inconsistent")
        return purchase


@router.post("/credit-checkout")
async def create_credit_checkout_session(
    payload: CreditCheckoutRequest,
    caller: CallerDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> dict[str, str]:
    """Create a one-time Checkout Session from an immutable server-side pack."""
    settings = get_settings()
    if not credit_topups_available(settings):
        raise HTTPException(503, "Research-credit purchases are not available")
    async with tenant_session(str(caller.tenant_id)) as session:
        schema_ready = await session.scalar(
            text("SELECT to_regclass('public.billing_credit_purchases') IS NOT NULL")
        )
    if not schema_ready:
        raise HTTPException(503, "Research-credit purchases are not available")
    if idempotency_key.strip() != idempotency_key or any(
        ord(character) < 32 for character in idempotency_key
    ):
        raise HTTPException(422, "Invalid checkout idempotency key")
    packs = configured_credit_packs(settings)
    pack = packs.get(payload.package_key)
    if pack is None:
        raise HTTPException(422, "Unknown research-credit package")
    try:
        await validate_credit_price(
            settings,
            price_id=pack.price_id,
            amount_minor=pack.amount_minor,
            currency=pack.currency,
        )
        base_url = app_base_url(settings)
        purchase = await _begin_credit_purchase(
            caller,
            pack_key=pack.key,
            request_key=idempotency_key,
            amount_minor=pack.amount_minor,
            price_id=pack.price_id,
            units=pack.units,
            currency=pack.currency,
            terms_version=settings.BILLING_CREDIT_TERMS_VERSION or "",
            max_wallet_units=settings.BILLING_CREDIT_MAX_WALLET_UNITS,
        )
        customer_id = await _stripe_customer_for(caller, settings)
        if purchase.stripe_checkout_session_id:
            result = await stripe_request(
                settings,
                "GET",
                f"/checkout/sessions/{purchase.stripe_checkout_session_id}",
            )
            if result.get("status") == "complete":
                raise HTTPException(
                    409,
                    "Payment was received; credit delivery is being verified",
                )
            if result.get("status") != "open":
                raise HTTPException(
                    409,
                    "This Checkout Session is no longer open; start a new request",
                )
        else:
            result = await stripe_request(
                settings,
                "POST",
                "/checkout/sessions",
                form={
                    "mode": "payment",
                    "customer": customer_id,
                    "client_reference_id": str(purchase.id),
                    "line_items[0][price]": pack.price_id,
                    "line_items[0][quantity]": "1",
                    "success_url": (
                        f"{base_url}/research?credits=success&session_id={{CHECKOUT_SESSION_ID}}"
                    ),
                    "cancel_url": f"{base_url}/pricing?credits=cancelled",
                    "metadata[purchase_id]": str(purchase.id),
                    "metadata[tenant_id]": str(caller.tenant_id),
                    "metadata[user_id]": str(caller.user_id),
                    "payment_intent_data[metadata][purchase_id]": str(purchase.id),
                },
                idempotency_key=purchase.stripe_idempotency_key,
            )
        session_id = result.get("id")
        if (
            not isinstance(session_id, str)
            or not session_id.startswith("cs_")
            or STRIPE_ID_PATTERN.fullmatch(session_id) is None
        ):
            raise StripeUnavailable("Stripe returned an invalid Checkout Session")
        if purchase.stripe_checkout_session_id is None:
            async with tenant_session(str(caller.tenant_id)) as session:
                await session.execute(
                    text("SELECT set_config('app.user_id', :id, true)"),
                    {"id": str(caller.user_id)},
                )
                await session.execute(
                    update(BillingCreditPurchase)
                    .where(
                        BillingCreditPurchase.id == purchase.id,
                        BillingCreditPurchase.state == "pending",
                        BillingCreditPurchase.stripe_checkout_session_id.is_(None),
                    )
                    .values(stripe_checkout_session_id=session_id)
                )
        return {
            "purchaseId": str(purchase.id),
            "sessionId": session_id,
            "url": safe_session_url(result),
        }
    except StripeUnavailable as exc:
        raise HTTPException(503, "Research-credit checkout is temporarily unavailable") from exc


async def _begin_checkout_attempt(
    caller: Caller, *, plan_key: str, request_key: str
) -> StripeCheckoutAttempt:
    now = datetime.now(UTC)
    key_hash = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
    stable_key = stripe_idempotency_key(
        "checkout", f"{caller.tenant_id}:{caller.user_id}:{request_key}"
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        lock_name = f"stripe-checkout-v1:{caller.tenant_id}:{caller.user_id}"
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(lock_name, 0)))
        )
        same_key = await session.scalar(
            select(StripeCheckoutAttempt).where(
                StripeCheckoutAttempt.tenant_id == caller.tenant_id,
                StripeCheckoutAttempt.user_id == caller.user_id,
                StripeCheckoutAttempt.request_key_hash == key_hash,
            )
        )
        if same_key is not None:
            if same_key.plan_key != plan_key:
                raise HTTPException(409, "Checkout idempotency key was used for another plan")
            if same_key.state == "completed":
                raise HTTPException(409, "Checkout has already completed")
            if same_key.state == "open" and same_key.expires_at > now:
                return same_key
            same_key.state = "open"
            same_key.stripe_session_id = None
            same_key.stripe_idempotency_key = stable_key
            same_key.created_at = now
            same_key.expires_at = now + timedelta(hours=20)
            await session.flush()
            return same_key

        open_attempt = await session.scalar(
            select(StripeCheckoutAttempt)
            .where(
                StripeCheckoutAttempt.tenant_id == caller.tenant_id,
                StripeCheckoutAttempt.user_id == caller.user_id,
                StripeCheckoutAttempt.state == "open",
            )
            .limit(1)
        )
        if open_attempt is not None:
            if open_attempt.expires_at > now:
                if open_attempt.plan_key != plan_key:
                    raise HTTPException(
                        409,
                        "A checkout for a different plan is already open for this account",
                    )
                # A browser retry gets a fresh request idempotency key. Reuse the
                # persisted attempt and its Stripe idempotency key so it resumes
                # the same hosted session instead of dead-ending with a 409 or
                # creating a duplicate subscription session.
                return open_attempt
            open_attempt.state = "expired"
        attempt = StripeCheckoutAttempt(
            tenant_id=caller.tenant_id,
            user_id=caller.user_id,
            request_key_hash=key_hash,
            stripe_idempotency_key=stable_key,
            plan_key=plan_key,
            state="open",
            created_at=now,
            expires_at=now + timedelta(hours=20),
        )
        session.add(attempt)
        await session.flush()
        return attempt


@router.post("/checkout")
async def create_checkout_session(
    payload: CheckoutRequest,
    caller: CallerDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> dict[str, str]:
    """Create a monthly hosted Checkout Session for a server-selected Price."""
    settings = get_settings()
    try:
        if (
            not settings.BILLING_STRIPE_ENABLED
            or not settings.BILLING_ENFORCEMENT_ENABLED
            or (settings.STRIPE_LIVEMODE and not settings.BILLING_LIVE_LAUNCH_APPROVED)
            or settings.STRIPE_WEBHOOK_SECRET is None
            or not settings.STRIPE_API_VERSION
        ):
            raise StripeUnavailable("Stripe billing is not enabled")
        prices = configured_prices(settings)
        configured_portal(settings)
        price_id = prices[payload.plan_key]
        await validate_monthly_price(settings, plan_key=payload.plan_key, price_id=price_id)
        base_url = app_base_url(settings)
        async with tenant_session(str(caller.tenant_id)) as session:
            await session.execute(
                text("SELECT set_config('app.user_id', :id, true)"),
                {"id": str(caller.user_id)},
            )
            paid = await session.scalar(
                select(StripeSubscription.stripe_subscription_id)
                .where(
                    StripeSubscription.tenant_id == caller.tenant_id,
                    StripeSubscription.user_id == caller.user_id,
                    StripeSubscription.status.not_in(("canceled", "incomplete_expired")),
                )
                .limit(1)
            )
        if paid is not None:
            raise HTTPException(
                409,
                "An active paid plan already exists; use subscription management",
            )
        attempt = await _begin_checkout_attempt(
            caller, plan_key=payload.plan_key, request_key=idempotency_key
        )
        customer_id = await _stripe_customer_for(caller, settings)
        if attempt.stripe_session_id:
            result = await stripe_request(
                settings,
                "GET",
                f"/checkout/sessions/{attempt.stripe_session_id}",
            )
            session_status = result.get("status")
            if session_status == "complete":
                raise HTTPException(
                    409,
                    "Checkout has completed; wait for your plan activation before trying again",
                )
            if session_status == "expired":
                async with tenant_session(str(caller.tenant_id)) as session:
                    await session.execute(
                        text("SELECT set_config('app.user_id', :id, true)"),
                        {"id": str(caller.user_id)},
                    )
                    await session.execute(
                        update(StripeCheckoutAttempt)
                        .where(
                            StripeCheckoutAttempt.id == attempt.id,
                            StripeCheckoutAttempt.state == "open",
                        )
                        .values(state="expired")
                    )
                raise HTTPException(
                    409,
                    "The previous checkout expired. Choose the plan again to start a new checkout",
                )
            if session_status != "open":
                raise StripeUnavailable("Stripe returned an invalid Checkout Session status")
        else:
            result = await stripe_request(
                settings,
                "POST",
                "/checkout/sessions",
                form={
                    "mode": "subscription",
                    "customer": customer_id,
                    "client_reference_id": str(caller.user_id),
                    "line_items[0][price]": price_id,
                    "line_items[0][quantity]": "1",
                    "success_url": f"{base_url}/research?billing=success",
                    "cancel_url": f"{base_url}/pricing?billing=cancelled",
                    "metadata[checkout_attempt_id]": str(attempt.id),
                    "subscription_data[metadata][tenant_id]": str(caller.tenant_id),
                    "subscription_data[metadata][user_id]": str(caller.user_id),
                },
                idempotency_key=attempt.stripe_idempotency_key,
            )
        session_id = result.get("id")
        if (
            not isinstance(session_id, str)
            or not session_id.startswith("cs_")
            or STRIPE_ID_PATTERN.fullmatch(session_id) is None
        ):
            raise StripeUnavailable("Stripe returned an invalid Checkout Session")
        async with tenant_session(str(caller.tenant_id)) as session:
            await session.execute(
                text("SELECT set_config('app.user_id', :id, true)"),
                {"id": str(caller.user_id)},
            )
            await session.execute(
                update(StripeCheckoutAttempt)
                .where(
                    StripeCheckoutAttempt.id == attempt.id,
                    StripeCheckoutAttempt.state == "open",
                )
                .values(stripe_session_id=session_id)
            )
        return {"sessionId": session_id, "url": safe_session_url(result)}
    except StripeUnavailable as exc:
        raise HTTPException(503, "Subscription checkout is temporarily unavailable") from exc


@router.post("/portal")
async def create_portal_session(caller: CallerDep) -> dict[str, str]:
    """Create an authenticated Stripe-hosted subscription management session."""
    settings = get_settings()
    try:
        base_url = app_base_url(settings)
        async with tenant_session(str(caller.tenant_id)) as session:
            await session.execute(
                text("SELECT set_config('app.user_id', :id, true)"),
                {"id": str(caller.user_id)},
            )
            customer_id = await session.scalar(
                select(StripeCustomerLink.stripe_customer_id).where(
                    StripeCustomerLink.tenant_id == caller.tenant_id,
                    StripeCustomerLink.user_id == caller.user_id,
                )
            )
        if customer_id is None:
            raise HTTPException(404, "No subscription is associated with this account")
        result = await stripe_request(
            settings,
            "POST",
            "/billing_portal/sessions",
            form={
                "customer": customer_id,
                "configuration": configured_portal(settings),
                "return_url": f"{base_url}/research",
            },
        )
        return {"url": safe_session_url(result, portal=True)}
    except StripeUnavailable as exc:
        raise HTTPException(503, "Subscription management is temporarily unavailable") from exc


async def read_caller_entitlement(caller: Caller) -> BillingEntitlement:
    """Bind the authenticated owner to RLS before reading their projection."""
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        if get_settings().BILLING_ENFORCEMENT_ENABLED:
            await ensure_default_free_period(
                session, tenant_id=caller.tenant_id, user_id=caller.user_id
            )
        return await read_entitlement(session, tenant_id=caller.tenant_id, user_id=caller.user_id)


@router.get(
    "/entitlement",
    response_model=BillingEntitlement,
    response_model_exclude_none=True,
)
async def get_entitlement(caller: CallerDep) -> BillingEntitlement:
    """Read the caller's period projection without trusting request-supplied plan data."""
    return await read_caller_entitlement(caller)


class BillingAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    period_id: uuid.UUID
    delta: int = Field(ge=-120, le=120)
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("tenant_id", "user_id", "period_id", mode="before")
    @classmethod
    def parse_json_uuids(cls, value: object) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        if isinstance(value, str):
            try:
                return uuid.UUID(value)
            except ValueError as exc:
                raise ValueError("must be a valid UUID") from exc
        raise ValueError("must be a UUID string")


def _operator_actor(token: str | None) -> uuid.UUID:
    settings = get_settings()
    configured = settings.BILLING_OPERATOR_TOKENS
    if token is None or configured is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "billing operator access unavailable"
        )
    try:
        credentials = json.loads(configured.get_secret_value())
        if not isinstance(credentials, dict) or not credentials:
            raise ValueError
        matches = [
            (actor, candidate)
            for actor, candidate in credentials.items()
            if isinstance(actor, str) and isinstance(candidate, str)
        ]
        valid = [actor for actor, candidate in matches if compare_digest(token, candidate)]
        if len(valid) != 1:
            raise ValueError
        return uuid.UUID(valid[0])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "billing operator access unavailable"
        ) from exc


@router.post("/adjustments", status_code=status.HTTP_201_CREATED)
async def create_billing_adjustment(
    payload: BillingAdjustmentRequest,
    x_billing_operator_token: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Append a bounded adjustment using a server-configured operator identity."""
    actor_id = _operator_actor(x_billing_operator_token)
    async with tenant_session(str(payload.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(payload.user_id)},
        )
        try:
            entry = await adjust_units(
                session,
                tenant_id=payload.tenant_id,
                user_id=payload.user_id,
                period_id=payload.period_id,
                delta=payload.delta,
                idempotency_key=payload.idempotency_key,
                actor_id=actor_id,
                reason=payload.reason,
            )
        except BillingAdjustmentConflict as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "adjustment key conflicts with prior audit entry"
            ) from exc
        except BillingAdjustmentUnavailable as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "adjustment exceeds period balance bounds",
            ) from exc
        except BillingConfigurationUnavailable as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "billing account or period unavailable"
            ) from exc
        return {"entryId": str(entry.id), "status": "recorded"}


MAX_STRIPE_EVENT_BYTES = 1_000_000


@router.post(
    "/webhooks/stripe",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
async def receive_stripe_webhook(request: Request) -> dict[str, object] | JSONResponse:
    """Verify raw Stripe bytes and durably deduplicate the minimal event envelope.

    Subscription projection is committed in the same transaction as the event
    inbox record. Signed but unresolvable snapshots are retained for reconciliation.
    """
    settings = get_settings()
    if settings.STRIPE_WEBHOOK_SECRET is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe webhook is not configured")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_STRIPE_EVENT_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Stripe event is too large"
            )
    signature = request.headers.get("stripe-signature", "")
    secret = settings.STRIPE_WEBHOOK_SECRET.get_secret_value()
    if not stripe_signature_valid(
        bytes(body),
        signature,
        secret,
        now_seconds=int(datetime.now(UTC).timestamp()),
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Stripe signature")
    try:
        event = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Stripe event") from exc
    if not isinstance(event, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Stripe event envelope")
    data = event.get("data")
    data_object = data.get("object") if isinstance(data, dict) else None
    event_id, event_type = event.get("id"), event.get("type")
    if (
        not isinstance(event_id, str)
        or not event_id.startswith("evt_")
        or len(event_id) > 255
        or not isinstance(event_type, str)
        or not 1 <= len(event_type) <= 160
        or not isinstance(data_object, dict)
        or type(event.get("livemode")) is not bool
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Stripe event envelope")
    created = event.get("created")
    if not isinstance(created, int) or isinstance(created, bool) or created < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Stripe event timestamp")
    try:
        event_created_at = datetime.fromtimestamp(created, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Stripe event timestamp") from exc
    obj_id = data_object.get("id")
    if obj_id is not None and (not isinstance(obj_id, str) or len(obj_id) > 255):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Stripe object identifier")
    subscription_events = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    }
    relevant = event_type in subscription_events or event_type in {
        "checkout.session.completed",
        "checkout.session.expired",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
        "refund.created",
        "refund.updated",
        "charge.dispute.created",
        "charge.dispute.closed",
    }
    needs_reconciliation = False
    duplicate_event = False
    async with system_session() as session:
        inserted = await session.scalar(
            insert(StripeWebhookEvent)
            .values(
                event_id=event_id,
                event_type=event_type,
                event_created_at=event_created_at,
                object_id=obj_id,
                livemode=event["livemode"],
                processing_status="received" if relevant else "ignored",
            )
            .on_conflict_do_nothing(index_elements=[StripeWebhookEvent.event_id])
            .returning(StripeWebhookEvent.event_id)
        )
        duplicate_event = inserted is None
        prior_status = None
        if duplicate_event and relevant:
            prior = await session.scalar(
                select(StripeWebhookEvent)
                .where(StripeWebhookEvent.event_id == event_id)
                .with_for_update()
            )
            prior_status = prior.processing_status if prior is not None else None
        should_process = relevant and (
            inserted is not None or prior_status in {"received", "reconciliation_required"}
        )
        if should_process:
            credit_schema_ready = False
            if event_type not in subscription_events and (
                event_type
                in {
                    "refund.created",
                    "refund.updated",
                    "charge.dispute.created",
                    "charge.dispute.closed",
                }
                or data_object.get("mode") == "payment"
            ):
                credit_schema_ready = bool(
                    await session.scalar(
                        text("SELECT to_regclass('public.billing_credit_purchases') IS NOT NULL")
                    )
                )
            if event.get("api_version") != settings.STRIPE_API_VERSION:
                processing_status = "reconciliation_required"
            elif not settings.BILLING_STRIPE_ENABLED:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Stripe subscription processing is not enabled",
                )
            else:
                try:
                    await session.execute(
                        text("SELECT set_config('app.billing_system', 'on', true)")
                    )
                    if event_type in subscription_events:
                        processing_status = await apply_subscription_event(
                            session,
                            event_id=event_id,
                            event_created_at=event_created_at,
                            event_type=event_type,
                            livemode=event["livemode"],
                            obj=data_object,
                            settings=settings,
                        )
                    elif (
                        event_type.startswith("checkout.session.")
                        and data_object.get("mode") == "payment"
                    ):
                        if (
                            not credit_schema_ready
                            or not settings.BILLING_CREDIT_FULFILLMENT_ENABLED
                        ):
                            raise HTTPException(503, "Research-credit fulfillment is unavailable")
                        processing_status = await apply_credit_checkout(
                            session,
                            event_type=event_type,
                            obj=data_object,
                            livemode=event["livemode"],
                            expected_livemode=settings.STRIPE_LIVEMODE,
                        )
                    elif event_type in {"refund.created", "refund.updated"}:
                        if not credit_schema_ready or data_object.get("status") != "succeeded":
                            processing_status = "processed"
                        else:
                            processing_status = await apply_credit_reversal(
                                session,
                                event_type=event_type,
                                obj=data_object,
                                livemode=event["livemode"],
                                expected_livemode=settings.STRIPE_LIVEMODE,
                                settings=settings,
                            )
                    elif event_type in {"charge.dispute.created", "charge.dispute.closed"}:
                        if credit_schema_ready:
                            processing_status = await apply_credit_reversal(
                                session,
                                event_type=event_type,
                                obj=data_object,
                                livemode=event["livemode"],
                                expected_livemode=settings.STRIPE_LIVEMODE,
                                settings=settings,
                            )
                        else:
                            processing_status = "ignored"
                    elif event_type in {
                        "checkout.session.async_payment_succeeded",
                        "checkout.session.async_payment_failed",
                    }:
                        processing_status = "ignored"
                    else:
                        processing_status = await apply_checkout_event(
                            session, event_type=event_type, obj=data_object
                        )
                except StripeUnavailable as exc:
                    raise HTTPException(
                        status.HTTP_503_SERVICE_UNAVAILABLE,
                        "Stripe subscription processing is not configured",
                    ) from exc
            await session.execute(
                update(StripeWebhookEvent)
                .where(StripeWebhookEvent.event_id == event_id)
                .values(processing_status=processing_status)
            )
            needs_reconciliation = processing_status == "reconciliation_required"
    if needs_reconciliation:
        # Preserve the inbox row, but ask Stripe to retry after an operator fixes
        # owner/Price/configuration ambiguity. The next delivery reuses this body.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"received": True, "reconciliationRequired": True},
        )
    return {"received": True, "duplicate": duplicate_event, "eventId": event_id}
