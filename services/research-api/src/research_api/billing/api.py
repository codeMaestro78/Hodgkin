"""Billing read, operator and public signed-webhook endpoints."""

import calendar
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from time import monotonic
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from research_api.auth import Caller, authenticated_caller
from research_api.billing.catalog import BILLING_CATALOG
from research_api.billing.credit_packs import (
    configured_razorpay_credit_packs,
    razorpay_credit_topups_available,
)
from research_api.billing.credits import credit_balance, wallet_frozen
from research_api.billing.entitlements import read_entitlement
from research_api.billing.ledger import (
    BillingAdjustmentConflict,
    BillingAdjustmentUnavailable,
    BillingConfigurationUnavailable,
    adjust_units,
    ensure_default_free_period,
    transition_period_state,
)
from research_api.billing.razorpay import (
    SUPPORTED_CURRENCY_CODES,
    RazorpayUnavailable,
    configured_key_id,
    payment_signature_valid,
    subscription_signature_valid,
    webhook_signature_valid,
)
from research_api.billing.razorpay import (
    cancel_subscription as cancel_razorpay_subscription,
)
from research_api.billing.razorpay import (
    create_order as create_razorpay_order,
)
from research_api.billing.razorpay import (
    create_subscription as create_razorpay_subscription,
)
from research_api.billing.razorpay import (
    fetch_payment as fetch_razorpay_payment,
)
from research_api.billing.razorpay import (
    fetch_plan as fetch_razorpay_plan,
)
from research_api.billing.razorpay import (
    fetch_subscription as fetch_razorpay_subscription,
)
from research_api.billing.subscriptions import (
    RazorpaySubscriptionPlan,
    razorpay_subscriptions_available,
    subscription_plans,
)
from research_api.config import get_settings
from research_api.db.models import (
    BillingAccount,
    BillingCreditEntry,
    BillingCreditPurchase,
    BillingPeriod,
    RazorpaySubscription,
    RazorpaySubscriptionCheckoutAttempt,
    RazorpaySubscriptionPayment,
    RazorpayWebhookEvent,
)
from research_api.db.session import system_session, tenant_session
from research_api.schemas.generated.billing_entitlement import (
    AllowedMode,
    BillingEntitlement,
)
from research_api.schemas.generated.billing_entitlement import (
    Status as EntitlementStatus,
)
from research_api.telemetry import operation_event

router = APIRouter(prefix="/billing", tags=["billing"])


async def caller_dependency(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> Caller:
    return await authenticated_caller(
        get_settings(), x_internal_service_auth, authorization=authorization
    )


CallerDep = Annotated[Caller, Depends(caller_dependency)]


async def _razorpay_schema_ready(session: Any) -> bool:
    return bool(
        await session.scalar(
            text("""
                SELECT to_regclass('public.billing_credit_purchases') IS NOT NULL
                   AND EXISTS (
                       SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public'
                         AND table_name = 'billing_credit_purchases'
                         AND column_name = 'payment_provider'
                   )
            """)
        )
    )


class CreditCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    package_key: str = Field(alias="packageKey", min_length=1, max_length=64)


class RazorpayPaymentVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_order_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=128)


class SubscriptionCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    plan_key: Literal["scholar", "investigator"] = Field(alias="planKey")
    billing_period: Literal["monthly", "yearly"] = Field(alias="billingPeriod")


class RazorpaySubscriptionVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_subscription_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=128)


class CancelPendingSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    subscription_id: str = Field(alias="subscriptionId", min_length=8, max_length=64)


async def _subscription_schema_ready(session: Any) -> bool:
    return bool(
        await session.scalar(
            text("""
            SELECT to_regclass('public.razorpay_subscriptions') IS NOT NULL
               AND to_regclass('public.razorpay_subscription_checkout_attempts') IS NOT NULL
               AND to_regclass('public.razorpay_subscription_payments') IS NOT NULL
        """)
        )
    )


@router.get("/checkout-availability")
async def checkout_availability() -> dict[str, object]:
    """Expose only fully configured recurring plans; never expose provider secrets."""
    settings = get_settings()
    enabled = razorpay_subscriptions_available(settings)
    if enabled:
        async with system_session() as session:
            enabled = await _subscription_schema_ready(session)
    plans = subscription_plans(settings) if enabled else {}
    return {
        "enabled": enabled,
        "plans": sorted({key for key, _period in plans}),
        "billingPeriods": sorted({period for _key, period in plans}),
    }


def _checkout_response(
    *, plan: RazorpaySubscriptionPlan, subscription_id: str, key_id: str
) -> dict[str, object]:
    return {
        "subscriptionId": subscription_id,
        "keyId": key_id,
        "amountMinor": plan.amount_minor,
        "currency": plan.currency,
        "planKey": plan.key,
        "billingPeriod": plan.period,
        "name": "HogsKin",
        "description": f"{plan.key.title()} research plan ({plan.period})",
    }


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
async def create_subscription_checkout(
    payload: SubscriptionCheckoutRequest,
    caller: CallerDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    """Create one owner-bound Razorpay subscription; uncertain calls are not replayed."""
    settings = get_settings()
    if not razorpay_subscriptions_available(settings):
        raise HTTPException(503, "Paid subscriptions are not available")
    if (
        not idempotency_key
        or not 8 <= len(idempotency_key) <= 200
        or any(ord(char) < 32 for char in idempotency_key)
    ):
        raise HTTPException(400, "A valid Idempotency-Key is required")
    plan_key = payload.plan_key
    billing_period = payload.billing_period
    plan = subscription_plans(settings).get((plan_key, billing_period))
    if plan is None:
        raise HTTPException(422, "The selected plan is unavailable")
    request_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    now = datetime.now(UTC)
    attempt_id: uuid.UUID
    open_subscription_id: str | None = None
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:owner, 0))"),
            {"owner": f"razorpay-subscription:{caller.tenant_id}:{caller.user_id}"},
        )
        prior = await session.scalar(
            select(RazorpaySubscriptionCheckoutAttempt).where(
                RazorpaySubscriptionCheckoutAttempt.tenant_id == caller.tenant_id,
                RazorpaySubscriptionCheckoutAttempt.user_id == caller.user_id,
                RazorpaySubscriptionCheckoutAttempt.request_key_hash == request_hash,
            )
        )
        open_attempt: RazorpaySubscriptionCheckoutAttempt | None
        if prior is not None:
            if prior.plan_key != plan_key or prior.billing_period != billing_period:
                raise HTTPException(
                    409, "Idempotency key was already used for different plan terms"
                )
            if prior.state not in {"creating", "created", "uncertain"}:
                raise HTTPException(
                    409,
                    "This checkout attempt is already terminal. Start a new checkout deliberately.",
                )
            open_attempt = prior
        else:
            open_attempt = await session.scalar(
                select(RazorpaySubscriptionCheckoutAttempt)
                .where(
                    RazorpaySubscriptionCheckoutAttempt.tenant_id == caller.tenant_id,
                    RazorpaySubscriptionCheckoutAttempt.user_id == caller.user_id,
                    RazorpaySubscriptionCheckoutAttempt.state.in_(
                        ("creating", "created", "uncertain")
                    ),
                )
                .limit(1)
            )
        if open_attempt is not None:
            if open_attempt.plan_key != plan_key or open_attempt.billing_period != billing_period:
                raise HTTPException(
                    409,
                    "A different plan checkout is already open. Resume or resolve it "
                    "before changing plans.",
                )
            if open_attempt.state == "creating":
                raise HTTPException(
                    409, "Your checkout is still being created. Check its status before retrying."
                )
            if not open_attempt.subscription_id:
                raise HTTPException(
                    503,
                    "Checkout creation is uncertain and has no provider ID to verify. "
                    "Contact support before retrying.",
                )
            attempt_id = open_attempt.id
            open_subscription_id = open_attempt.subscription_id
        else:
            existing = await session.scalar(
                select(RazorpaySubscription.subscription_id)
                .where(
                    RazorpaySubscription.tenant_id == caller.tenant_id,
                    RazorpaySubscription.user_id == caller.user_id,
                    RazorpaySubscription.status.in_(
                        ("created", "authenticated", "active", "pending", "halted", "paused")
                    ),
                )
                .limit(1)
            )
            if existing is not None:
                raise HTTPException(
                    409, "An existing subscription must be managed before changing plans"
                )
            account_id = await session.scalar(
                select(BillingAccount.id).where(
                    BillingAccount.tenant_id == caller.tenant_id,
                    BillingAccount.user_id == caller.user_id,
                )
            )
            if account_id is not None:
                paid_period = await session.scalar(
                    select(BillingPeriod.id)
                    .where(
                        BillingPeriod.tenant_id == caller.tenant_id,
                        BillingPeriod.billing_account_id == account_id,
                        BillingPeriod.plan_key.in_(("scholar", "investigator")),
                        BillingPeriod.state == "active",
                        BillingPeriod.starts_at <= now,
                        BillingPeriod.ends_at > now,
                    )
                    .limit(1)
                )
                if paid_period is not None:
                    raise HTTPException(
                        409,
                        "Your current paid period must end before starting another subscription",
                    )
            attempt = RazorpaySubscriptionCheckoutAttempt(
                tenant_id=caller.tenant_id,
                user_id=caller.user_id,
                request_key_hash=request_hash,
                provider_idempotency_key=f"hogskin-subscription-{uuid.uuid4()}",
                plan_key=plan_key,
                billing_period=billing_period,
                state="creating",
                expires_at=now + timedelta(minutes=15),
            )
            session.add(attempt)
            await session.flush()
            attempt_id = attempt.id

    if open_subscription_id is not None:
        reconcile_started = monotonic()
        try:
            provider_subscription = await fetch_razorpay_subscription(
                settings, open_subscription_id
            )
        except RazorpayUnavailable as exc:
            operation_event(
                "razorpay.subscription.reconcile",
                started=reconcile_started,
                outcome="uncertain",
                error=exc,
                providerStatus=exc.status_code,
                providerCode=exc.provider_code,
                providerRequestId=exc.provider_request_id,
            )
            raise HTTPException(
                503,
                "The existing checkout could not be verified. It is preserved; retry "
                "status check before creating another.",
            ) from exc
        provider_status = provider_subscription.get("status")
        if (
            provider_subscription.get("id") != open_subscription_id
            or provider_subscription.get("plan_id") != plan.provider_plan_id
            or provider_status
            not in {
                "created",
                "authenticated",
                "active",
                "pending",
                "halted",
                "paused",
                "cancelled",
                "completed",
                "expired",
            }
        ):
            operation_event(
                "razorpay.subscription.reconcile",
                started=reconcile_started,
                outcome="reconciliation_required",
                error=RazorpayUnavailable("provider subscription terms/status mismatch"),
                providerStatus=(provider_status if isinstance(provider_status, str) else None),
            )
            raise HTTPException(
                503, "The existing checkout needs reconciliation; no replacement was created."
            )
        terminal_status = provider_status in {"cancelled", "completed", "expired"}
        async with tenant_session(str(caller.tenant_id)) as session:
            await session.execute(
                text("SELECT set_config('app.user_id', :id, true)"),
                {"id": str(caller.user_id)},
            )
            await session.execute(
                update(RazorpaySubscription)
                .where(
                    RazorpaySubscription.subscription_id == open_subscription_id,
                    RazorpaySubscription.tenant_id == caller.tenant_id,
                    RazorpaySubscription.user_id == caller.user_id,
                )
                .values(status=provider_status)
            )
            await session.execute(
                update(RazorpaySubscriptionCheckoutAttempt)
                .where(
                    RazorpaySubscriptionCheckoutAttempt.id == attempt_id,
                    RazorpaySubscriptionCheckoutAttempt.tenant_id == caller.tenant_id,
                    RazorpaySubscriptionCheckoutAttempt.user_id == caller.user_id,
                )
                .values(state="failed" if terminal_status else "created")
            )
        operation_event(
            "razorpay.subscription.reconcile",
            started=reconcile_started,
            outcome="succeeded" if provider_status == "created" else "reconciled",
            providerStatus=provider_status,
            resumed=provider_status == "created",
        )
        if provider_status == "created":
            return _checkout_response(
                plan=plan,
                subscription_id=open_subscription_id,
                key_id=configured_key_id(settings),
            )
        if not terminal_status:
            raise HTTPException(
                409,
                "This subscription is already processing. Check its status; another "
                "checkout was not created.",
            )
        # Require a fresh, explicit checkout action after status reconciliation. This
        # also ensures concurrent retries cannot both create a replacement subscription.
        raise HTTPException(
            409,
            "The previous checkout is confirmed terminal. Start a new checkout to continue.",
        )

    plan_verify_started = monotonic()
    verification_failure = "provider_lookup"
    plan_matches: dict[str, bool] = {}
    try:
        provider_plan = await fetch_razorpay_plan(settings, plan.provider_plan_id)
        item = provider_plan.get("item")
        plan_matches = {
            "idMatches": provider_plan.get("id") == plan.provider_plan_id,
            "periodMatches": provider_plan.get("period") == plan.period,
            "intervalMatches": provider_plan.get("interval") == 1,
            "amountMatches": isinstance(item, dict) and item.get("amount") == plan.amount_minor,
            "currencyMatches": isinstance(item, dict) and item.get("currency") == plan.currency,
        }
        if not all(plan_matches.values()):
            verification_failure = "plan_terms_mismatch"
            raise RazorpayUnavailable("Configured Razorpay plan terms do not match the application")
    except RazorpayUnavailable as exc:
        operation_event(
            "razorpay.plan.verify",
            started=plan_verify_started,
            outcome="rejected"
            if exc.status_code or verification_failure == "plan_terms_mismatch"
            else "uncertain",
            error=exc,
            providerStatus=exc.status_code,
            providerCode=exc.provider_code,
            providerRequestId=exc.provider_request_id,
            verificationFailure=verification_failure,
            **plan_matches,
        )
        async with tenant_session(str(caller.tenant_id)) as session:
            await session.execute(
                text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
            )
            await session.execute(
                update(RazorpaySubscriptionCheckoutAttempt)
                .where(RazorpaySubscriptionCheckoutAttempt.id == attempt_id)
                .values(state="failed")
            )
        raise HTTPException(503, "The configured Razorpay plan could not be verified") from exc

    try:
        provider_subscription = await create_razorpay_subscription(
            settings,
            plan_id=plan.provider_plan_id,
            total_count=120 if billing_period == "monthly" else 10,
            notes={"checkout_attempt": str(attempt_id)},
        )
    except (RazorpayUnavailable, ValueError) as exc:
        async with tenant_session(str(caller.tenant_id)) as session:
            await session.execute(
                text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
            )
            await session.execute(
                update(RazorpaySubscriptionCheckoutAttempt)
                .where(RazorpaySubscriptionCheckoutAttempt.id == attempt_id)
                .values(state="uncertain")
            )
        raise HTTPException(
            503, "Razorpay subscription status is uncertain; contact support before retrying"
        ) from exc

    subscription_id = str(provider_subscription["id"])
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        session.add(
            RazorpaySubscription(
                subscription_id=subscription_id,
                tenant_id=caller.tenant_id,
                user_id=caller.user_id,
                plan_key=plan_key,
                billing_period=billing_period,
                catalog_version=BILLING_CATALOG.version,
                provider_plan_id=plan.provider_plan_id,
                status=str(provider_subscription["status"]),
            )
        )
        await session.execute(
            update(RazorpaySubscriptionCheckoutAttempt)
            .where(RazorpaySubscriptionCheckoutAttempt.id == attempt_id)
            .values(state="created", subscription_id=subscription_id)
        )
    return _checkout_response(
        plan=plan, subscription_id=subscription_id, key_id=configured_key_id(settings)
    )


@router.post("/verify-subscription")
async def verify_subscription_checkout(
    payload: RazorpaySubscriptionVerification, caller: CallerDep
) -> dict[str, str]:
    """Verify Checkout callback identity; entitlements wait for captured-charge webhook."""
    settings = get_settings()
    if not razorpay_subscriptions_available(settings):
        raise HTTPException(503, "Paid subscriptions are not available")
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        subscription = await session.scalar(
            select(RazorpaySubscription).where(
                RazorpaySubscription.subscription_id == payload.razorpay_subscription_id,
                RazorpaySubscription.tenant_id == caller.tenant_id,
                RazorpaySubscription.user_id == caller.user_id,
            )
        )
        if subscription is None:
            raise HTTPException(404, "Subscription checkout was not found")
        if not subscription_signature_valid(
            subscription_id=subscription.subscription_id,
            payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
            secret=settings.RAZORPAY_KEY_SECRET,
        ):
            raise HTTPException(400, "Razorpay payment signature is invalid")
    try:
        remote = await fetch_razorpay_subscription(settings, subscription.subscription_id)
    except RazorpayUnavailable as exc:
        raise HTTPException(503, "Subscription verification is temporarily unavailable") from exc
    expected_cycles = 120 if subscription.billing_period == "monthly" else 10
    if (
        remote.get("id") != subscription.subscription_id
        or remote.get("plan_id") != subscription.provider_plan_id
        or remote.get("total_count") != expected_cycles
        or remote.get("quantity") != 1
    ):
        raise HTTPException(409, "Razorpay subscription terms do not match this checkout")
    remote_status = remote.get("status")
    if remote_status not in {
        "created",
        "authenticated",
        "active",
        "pending",
        "halted",
        "paused",
        "cancelled",
        "completed",
        "expired",
    }:
        raise HTTPException(503, "Razorpay returned an unsupported subscription status")
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        await session.execute(
            update(RazorpaySubscription)
            .where(RazorpaySubscription.subscription_id == subscription.subscription_id)
            .values(status=remote_status)
        )
        await session.execute(
            update(RazorpaySubscriptionCheckoutAttempt)
            .where(
                RazorpaySubscriptionCheckoutAttempt.subscription_id == subscription.subscription_id
            )
            .values(state="completed")
        )
    return {"status": "verified", "entitlementStatus": "pending_webhook"}


@router.post("/checkout/cancel")
async def cancel_pending_subscription_checkout(
    payload: CancelPendingSubscriptionRequest, caller: CallerDep
) -> dict[str, str]:
    """Cancel an abandoned pre-activation checkout so the owner may retry safely."""
    settings = get_settings()
    if not razorpay_subscriptions_available(settings):
        raise HTTPException(503, "Paid subscriptions are not available")
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        subscription = await session.scalar(
            select(RazorpaySubscription)
            .where(
                RazorpaySubscription.subscription_id == payload.subscription_id,
                RazorpaySubscription.tenant_id == caller.tenant_id,
                RazorpaySubscription.user_id == caller.user_id,
            )
            .with_for_update()
        )
        if subscription is None:
            raise HTTPException(404, "Subscription checkout was not found")
        if subscription.status not in {"created", "authenticated", "pending"}:
            raise HTTPException(
                409, "This subscription cannot be cancelled as an abandoned checkout"
            )
    cancel_started = monotonic()
    try:
        result = await cancel_razorpay_subscription(
            settings,
            subscription_id=payload.subscription_id,
            cancel_at_cycle_end=False,
        )
    except RazorpayUnavailable as exc:
        operation_event(
            "razorpay.subscription.cancel",
            started=cancel_started,
            outcome="uncertain",
            error=exc,
            providerStatus=exc.status_code,
            providerCode=exc.provider_code,
            providerRequestId=exc.provider_request_id,
        )
        reconcile_started = monotonic()
        try:
            result = await fetch_razorpay_subscription(settings, payload.subscription_id)
        except RazorpayUnavailable as status_exc:
            operation_event(
                "razorpay.subscription.cancel_reconcile",
                started=reconcile_started,
                outcome="uncertain",
                error=status_exc,
                providerStatus=status_exc.status_code,
                providerCode=status_exc.provider_code,
                providerRequestId=status_exc.provider_request_id,
            )
            raise HTTPException(
                503,
                "Cancellation could not be confirmed. The checkout is preserved for a "
                "safe status check.",
            ) from status_exc
    if result.get("id") != payload.subscription_id:
        operation_event(
            "razorpay.subscription.cancel_reconcile",
            started=monotonic(),
            outcome="reconciliation_required",
            providerStatus=result.get("status"),
        )
        raise HTTPException(503, "Razorpay returned a different subscription during cancellation")
    if result.get("status") not in {"cancelled", "completed", "expired"}:
        operation_event(
            "razorpay.subscription.cancel_reconcile",
            started=monotonic(),
            outcome="uncertain",
            providerStatus=result.get("status"),
        )
        raise HTTPException(
            503, "Razorpay has not confirmed a terminal checkout state; the attempt remains open."
        )
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        await session.execute(
            update(RazorpaySubscription)
            .where(RazorpaySubscription.subscription_id == payload.subscription_id)
            .values(status=result["status"])
        )
        await session.execute(
            update(RazorpaySubscriptionCheckoutAttempt)
            .where(RazorpaySubscriptionCheckoutAttempt.subscription_id == payload.subscription_id)
            .values(state="failed")
        )
    return {"status": result["status"]}


@router.get("/subscription")
async def get_caller_subscription(caller: CallerDep) -> dict[str, object]:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        subscription = await session.scalar(
            select(RazorpaySubscription)
            .where(
                RazorpaySubscription.tenant_id == caller.tenant_id,
                RazorpaySubscription.user_id == caller.user_id,
            )
            .order_by(RazorpaySubscription.created_at.desc())
            .limit(1)
        )
        if subscription is None:
            return {"subscription": None}
        return {
            "subscription": {
                "id": subscription.subscription_id,
                "planKey": subscription.plan_key,
                "billingPeriod": subscription.billing_period,
                "status": subscription.status,
                "currentPeriodStart": subscription.current_period_start,
                "currentPeriodEnd": subscription.current_period_end,
                "cancelAtCycleEnd": subscription.cancel_at_cycle_end,
            }
        }


@router.post("/subscription/reconcile")
async def reconcile_caller_subscription(caller: CallerDep) -> dict[str, str]:
    """Revalidate a signed-webhook charge with Razorpay, then safely grant its period."""
    started = monotonic()
    settings = get_settings()
    if not razorpay_subscriptions_available(settings):
        raise HTTPException(503, "Paid subscriptions are not available")

    async with system_session() as session:
        await session.execute(text("SELECT set_config('app.billing_system', 'on', true)"))
        subscription = await session.scalar(
            select(RazorpaySubscription)
            .where(
                RazorpaySubscription.tenant_id == caller.tenant_id,
                RazorpaySubscription.user_id == caller.user_id,
                RazorpaySubscription.status == "reconciliation_required",
            )
            .order_by(RazorpaySubscription.created_at.desc())
            .limit(1)
        )
        if subscription is None:
            raise HTTPException(404, "No subscription needs payment reconciliation")
        payment = await session.scalar(
            select(RazorpaySubscriptionPayment)
            .where(
                RazorpaySubscriptionPayment.subscription_id == subscription.subscription_id,
                RazorpaySubscriptionPayment.status == "reconciliation_required",
            )
            .order_by(RazorpaySubscriptionPayment.received_at.desc())
            .limit(1)
        )
        payment_id = payment.payment_id if payment is not None else None
        if payment_id is None and subscription.last_event_id:
            # Older webhook deployments recorded payment_id on the signed event
            # inbox but did not create the payment reconciliation row.
            event_receipt = await session.scalar(
                select(RazorpayWebhookEvent).where(
                    RazorpayWebhookEvent.event_id == subscription.last_event_id,
                    RazorpayWebhookEvent.event_type.in_(
                        ("subscription.charged", "subscription.activated")
                    ),
                    RazorpayWebhookEvent.processing_status == "reconciliation_required",
                )
            )
            if event_receipt is not None and event_receipt.payment_id:
                payment_id = event_receipt.payment_id
        if payment_id is None:
            raise HTTPException(
                409,
                "No captured payment is safely linked to this subscription. Contact support.",
            )
        subscription_id = subscription.subscription_id
        expected_plan_id = subscription.provider_plan_id
        plan_key = subscription.plan_key
        billing_period = subscription.billing_period

    try:
        provider_subscription = await fetch_razorpay_subscription(settings, subscription_id)
        provider_payment = await fetch_razorpay_payment(settings, payment_id)
    except RazorpayUnavailable as exc:
        operation_event(
            "razorpay.subscription.reconcile",
            started=started,
            outcome="uncertain",
            providerStatus=exc.status_code,
            providerCode=exc.provider_code,
            providerRequestId=exc.provider_request_id,
            verificationFailure="provider_lookup",
        )
        raise HTTPException(
            503, "Payment status could not be confirmed. Try again shortly."
        ) from exc

    expected_cycles = 120 if billing_period == "monthly" else 10
    cycle_start = _provider_timestamp(provider_subscription.get("current_start"))
    cycle_end = _provider_timestamp(provider_subscription.get("current_end"))
    terms = BILLING_CATALOG.plans[cast(Literal["scholar", "investigator"], plan_key)]
    expected_price = terms.monthly_price if billing_period == "monthly" else terms.annual_price
    expected_minor = int(expected_price * 100) if expected_price is not None else -1
    payment_subscription_id = provider_payment.get("subscription_id")
    provider_matches = (
        provider_subscription.get("id") == subscription_id
        and provider_subscription.get("plan_id") == expected_plan_id
        and provider_subscription.get("status") == "active"
        and provider_subscription.get("quantity") == 1
        and provider_subscription.get("total_count") == expected_cycles
        and provider_payment.get("id") == payment_id
        and provider_payment.get("status") == "captured"
        and provider_payment.get("amount") == expected_minor
        and provider_payment.get("currency") == "INR"
        and payment_subscription_id in (None, subscription_id)
        and cycle_start is not None
        and cycle_end is not None
        and cycle_start < cycle_end
    )
    if not provider_matches or cycle_start is None or cycle_end is None:
        operation_event(
            "razorpay.subscription.reconcile",
            started=started,
            outcome="rejected",
            verificationFailure="provider_terms_mismatch",
        )
        raise HTTPException(
            409,
            "Razorpay payment or subscription details do not match the configured plan. "
            "No allowance was changed; contact support.",
        )

    async with system_session() as session:
        await session.execute(text("SELECT set_config('app.billing_system', 'on', true)"))
        subscription = await session.scalar(
            select(RazorpaySubscription)
            .where(
                RazorpaySubscription.subscription_id == subscription_id,
                RazorpaySubscription.tenant_id == caller.tenant_id,
                RazorpaySubscription.user_id == caller.user_id,
            )
            .with_for_update()
        )
        payment = await session.scalar(
            select(RazorpaySubscriptionPayment)
            .where(
                RazorpaySubscriptionPayment.payment_id == payment_id,
                RazorpaySubscriptionPayment.subscription_id == subscription_id,
            )
            .with_for_update()
        )
        if subscription is None:
            raise HTTPException(409, "The reconciliation record changed. Refresh status.")
        if payment is not None and payment.status == "processed":
            return {"status": "reconciled", "planKey": subscription.plan_key}
        if payment is not None and payment.status != "reconciliation_required":
            raise HTTPException(409, "The payment is not eligible for reconciliation")
        if payment is None:
            event_receipt = await session.scalar(
                select(RazorpayWebhookEvent)
                .where(
                    RazorpayWebhookEvent.event_id == subscription.last_event_id,
                    RazorpayWebhookEvent.event_type.in_(
                        ("subscription.charged", "subscription.activated")
                    ),
                    RazorpayWebhookEvent.payment_id == payment_id,
                    RazorpayWebhookEvent.processing_status == "reconciliation_required",
                )
                .with_for_update()
            )
            if event_receipt is None:
                raise HTTPException(409, "The reconciliation record changed. Refresh status.")

        result = await _grant_subscription_cycle(
            session,
            subscription=subscription,
            payment=provider_payment,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
        )
        if result != "processed":
            operation_event(
                "razorpay.subscription.reconcile",
                started=started,
                outcome="rejected",
                verificationFailure="ledger_conflict",
            )
            raise HTTPException(
                409,
                "The paid period conflicts with existing billing records. "
                "No allowance was changed; contact support.",
            )
        if payment is not None:
            payment.amount_minor = expected_minor
            payment.currency = "INR"
            payment.status = "processed"
        subscription.status = "active"
        subscription.current_period_start = cycle_start
        subscription.current_period_end = cycle_end
        await session.execute(
            update(RazorpayWebhookEvent)
            .where(
                RazorpayWebhookEvent.payment_id == payment_id,
                RazorpayWebhookEvent.event_type.in_(
                    ("subscription.charged", "subscription.activated")
                ),
                RazorpayWebhookEvent.processing_status == "reconciliation_required",
            )
            .values(processing_status="processed")
        )
    operation_event(
        "razorpay.subscription.reconcile",
        started=started,
        outcome="succeeded",
    )
    return {"status": "reconciled", "planKey": plan_key}


@router.get("/credit-packs")
async def list_credit_packs(caller: CallerDep) -> dict[str, object]:
    """List authenticated, server-configured Razorpay packs without provider secrets."""
    settings = get_settings()
    enabled = razorpay_credit_topups_available(settings)
    if enabled:
        async with tenant_session(str(caller.tenant_id)) as session:
            enabled = await _razorpay_schema_ready(session)
    packs = configured_razorpay_credit_packs(settings) if enabled else {}
    return {
        "enabled": enabled,
        "currency": next(iter(packs.values())).currency if packs else "INR",
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


@router.get("/credit-packs/diagnostics")
async def credit_pack_diagnostics(caller: CallerDep) -> dict[str, object]:
    """Explain credit-pack readiness without returning keys, secrets, or values."""
    settings = get_settings()
    key_id = settings.RAZORPAY_KEY_ID or ""
    key_mode_matches = key_id.startswith(
        "rzp_live_"
    ) == settings.RAZORPAY_LIVEMODE and key_id.startswith(("rzp_test_", "rzp_live_"))
    if key_id.startswith("rzp_live_") and not settings.BILLING_LIVE_LAUNCH_APPROVED:
        key_mode_matches = False
    packs = configured_razorpay_credit_packs(settings)
    checks: list[dict[str, object]] = [
        {
            "id": "razorpay_enabled",
            "label": "Razorpay checkout enabled",
            "ready": settings.BILLING_RAZORPAY_ENABLED,
        },
        {
            "id": "billing_enforced",
            "label": "Research-unit billing enabled",
            "ready": settings.BILLING_ENFORCEMENT_ENABLED,
        },
        {
            "id": "topups_enabled",
            "label": "Credit purchases enabled",
            "ready": settings.BILLING_CREDIT_TOPUPS_ENABLED,
        },
        {
            "id": "terms_approved",
            "label": "Credit terms approved",
            "ready": settings.BILLING_CREDIT_TERMS_APPROVED
            and settings.BILLING_CREDIT_TERMS_VERSION == "research-credit-terms-v1",
        },
        {
            "id": "fulfillment_enabled",
            "label": "Credit fulfillment enabled",
            "ready": settings.BILLING_CREDIT_FULFILLMENT_ENABLED,
        },
        {
            "id": "spending_enabled",
            "label": "Credit spending enabled",
            "ready": settings.BILLING_CREDIT_SPENDING_ENABLED,
        },
        {
            "id": "wallet_limit",
            "label": "Wallet capacity configured",
            "ready": settings.BILLING_CREDIT_MAX_WALLET_UNITS > 0,
        },
        {
            "id": "key_pair",
            "label": "Razorpay API key pair configured",
            "ready": bool(key_id and settings.RAZORPAY_KEY_SECRET),
        },
        {
            "id": "key_mode",
            "label": "Razorpay key mode matches configuration",
            "ready": key_mode_matches,
        },
        {
            "id": "webhook_secret",
            "label": "Webhook verification secret configured",
            "ready": bool(
                settings.RAZORPAY_WEBHOOK_SECRET
                and settings.RAZORPAY_WEBHOOK_SECRET.get_secret_value().strip()
            ),
        },
        {
            "id": "pack_catalog",
            "label": "At least one valid credit pack configured",
            "ready": bool(packs),
        },
        {
            "id": "inr_catalog",
            "label": "Credit packs use INR",
            "ready": bool(packs) and all(pack.currency == "INR" for pack in packs.values()),
        },
    ]
    async with tenant_session(str(caller.tenant_id)) as session:
        schema_ready = await _razorpay_schema_ready(session)
    checks.append(
        {
            "id": "database_schema",
            "label": "Credit-purchase database schema is ready",
            "ready": schema_ready,
        }
    )
    blocked = [str(check["id"]) for check in checks if not check["ready"]]
    return {
        "ready": not blocked,
        "mode": "live"
        if key_id.startswith("rzp_live_")
        else "test"
        if key_id.startswith("rzp_test_")
        else "unconfigured",
        "checks": checks,
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


@router.get("/credit-purchases/{order_id}")
async def read_credit_purchase(order_id: str, caller: CallerDep) -> dict[str, str]:
    """Read Razorpay fulfillment state for this authenticated purchase owner."""
    if not order_id.startswith("order_") or not order_id[6:].isalnum():
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
                BillingCreditPurchase.payment_provider == "razorpay",
                BillingCreditPurchase.provider_order_id == order_id,
                BillingAccount.user_id == caller.user_id,
            )
        )
        if purchase is None:
            raise HTTPException(404, "Credit purchase not found")
        return {"status": purchase.state}


async def _begin_credit_purchase(
    caller: Caller,
    *,
    pack_key: str,
    request_key: str,
    amount_minor: int,
    units: int,
    currency: str,
    terms_version: str,
    max_wallet_units: int,
    payment_provider: str = "razorpay",
) -> BillingCreditPurchase:
    """Persist immutable purchase terms before contacting the configured provider."""
    key_hash = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
    stable_key = (
        "research-billing-v1:razorpay-credit-checkout:"
        + hashlib.sha256(f"{caller.tenant_id}:{caller.user_id}:{request_key}".encode()).hexdigest()
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
                    payment_provider=payment_provider,
                    legacy_provider_price_id=None,
                    request_key_hash=key_hash,
                    provider_idempotency_key=stable_key,
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
            or purchase.payment_provider != payment_provider
            or purchase.legacy_provider_price_id is not None
            or purchase.amount_minor != amount_minor
            or purchase.currency != currency.upper()
            or purchase.unit_grant != units
            or purchase.terms_version != terms_version
        ):
            raise HTTPException(409, "Checkout idempotency key was used for different terms")
        if purchase.state != "pending":
            raise HTTPException(409, "This credit purchase is no longer payable")
        if purchase.provider_idempotency_key != stable_key:
            raise HTTPException(409, "Credit checkout idempotency record is inconsistent")
        return purchase


@router.post("/credit-checkout")
async def create_razorpay_credit_order(
    payload: CreditCheckoutRequest,
    caller: CallerDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> dict[str, str | int]:
    """Create/reuse a Razorpay order from an immutable server-owned credit pack."""
    settings = get_settings()
    if not razorpay_credit_topups_available(settings):
        raise HTTPException(503, "Research-credit purchases are not available")
    async with tenant_session(str(caller.tenant_id)) as session:
        schema_ready = await _razorpay_schema_ready(session)
    if not schema_ready:
        raise HTTPException(503, "Research-credit purchases are not available")
    if idempotency_key.strip() != idempotency_key or any(
        ord(character) < 32 for character in idempotency_key
    ):
        raise HTTPException(422, "Invalid checkout idempotency key")
    packs = configured_razorpay_credit_packs(settings)
    pack = packs.get(payload.package_key)
    if pack is None:
        raise HTTPException(422, "Unknown research-credit package")
    try:
        purchase = await _begin_credit_purchase(
            caller,
            pack_key=pack.key,
            request_key=idempotency_key,
            amount_minor=pack.amount_minor,
            units=pack.units,
            currency=pack.currency,
            terms_version=settings.BILLING_CREDIT_TERMS_VERSION or "",
            max_wallet_units=settings.BILLING_CREDIT_MAX_WALLET_UNITS,
            payment_provider="razorpay",
        )
        if purchase.payment_provider != "razorpay":
            raise HTTPException(409, "Checkout request conflicts with an existing purchase")
        if purchase.provider_order_id:
            if purchase.provider_order_state != "created":
                raise HTTPException(409, "This Razorpay order needs reconciliation")
            order_id = purchase.provider_order_id
        else:
            async with tenant_session(str(caller.tenant_id)) as session:
                await session.execute(
                    text("SELECT set_config('app.user_id', :id, true)"),
                    {"id": str(caller.user_id)},
                )
                await session.execute(text("SELECT set_config('app.billing_system', 'on', true)"))
                claimed = await session.scalar(
                    update(BillingCreditPurchase)
                    .where(
                        BillingCreditPurchase.id == purchase.id,
                        BillingCreditPurchase.provider_order_state == "not_started",
                        BillingCreditPurchase.provider_order_id.is_(None),
                    )
                    .values(provider_order_state="creating")
                    .returning(BillingCreditPurchase.id)
                )
            if claimed is None:
                raise HTTPException(
                    409, "This payment order is already being created or needs review"
                )
            try:
                result = await create_razorpay_order(
                    settings,
                    amount_minor=pack.amount_minor,
                    currency=pack.currency,
                    receipt=purchase.id.hex,
                )
            except (RazorpayUnavailable, ValueError) as exc:
                async with tenant_session(str(caller.tenant_id)) as session:
                    await session.execute(
                        text("SELECT set_config('app.user_id', :id, true)"),
                        {"id": str(caller.user_id)},
                    )
                    await session.execute(
                        text("SELECT set_config('app.billing_system', 'on', true)")
                    )
                    await session.execute(
                        update(BillingCreditPurchase)
                        .where(BillingCreditPurchase.id == purchase.id)
                        .values(provider_order_state="uncertain")
                    )
                raise HTTPException(
                    503,
                    "Payment order status is uncertain. Do not retry checkout; contact support.",
                ) from exc
            order_id = str(result["id"])
            async with tenant_session(str(caller.tenant_id)) as session:
                await session.execute(
                    text("SELECT set_config('app.user_id', :id, true)"),
                    {"id": str(caller.user_id)},
                )
                await session.execute(text("SELECT set_config('app.billing_system', 'on', true)"))
                saved = await session.scalar(
                    update(BillingCreditPurchase)
                    .where(
                        BillingCreditPurchase.id == purchase.id,
                        BillingCreditPurchase.provider_order_state == "creating",
                        BillingCreditPurchase.provider_order_id.is_(None),
                    )
                    .values(provider_order_id=order_id, provider_order_state="created")
                    .returning(BillingCreditPurchase.provider_order_id)
                )
                if saved is None:
                    raise HTTPException(409, "Payment order needs reconciliation")
        return {
            "purchaseId": str(purchase.id),
            "orderId": order_id,
            "amount": pack.amount_minor,
            "currency": pack.currency,
            "keyId": configured_key_id(settings),
        }
    except RazorpayUnavailable as exc:
        raise HTTPException(503, "Research-credit checkout is temporarily unavailable") from exc


@router.post("/credit-checkout/verify", response_model=None)
async def verify_razorpay_credit_payment(
    request: Request, caller: CallerDep
) -> dict[str, str] | JSONResponse:
    """Verify the signed callback and independently confirm capture before crediting."""
    settings = get_settings()
    if not razorpay_credit_topups_available(settings):
        raise HTTPException(503, "Research-credit verification is unavailable")
    try:
        payload = RazorpayPaymentVerification.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise HTTPException(400, "Payment verification fields are missing or invalid") from exc
    if not payment_signature_valid(
        order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature,
        secret=settings.RAZORPAY_KEY_SECRET,
    ):
        raise HTTPException(400, "Payment signature is invalid")

    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        purchase = await session.scalar(
            select(BillingCreditPurchase)
            .where(
                BillingCreditPurchase.tenant_id == caller.tenant_id,
                BillingCreditPurchase.user_id == caller.user_id,
                BillingCreditPurchase.payment_provider == "razorpay",
                BillingCreditPurchase.provider_order_id == payload.razorpay_order_id,
            )
            .with_for_update()
        )
        if purchase is None:
            raise HTTPException(404, "Credit purchase not found")
        if purchase.state == "paid":
            if purchase.provider_payment_id != payload.razorpay_payment_id:
                raise HTTPException(409, "A different payment already completed this order")
            return {"status": "paid"}
        if purchase.state != "pending" or purchase.provider_order_state != "created":
            raise HTTPException(409, "This payment order is not payable")

    try:
        payment = await fetch_razorpay_payment(settings, payload.razorpay_payment_id)
    except RazorpayUnavailable as exc:
        raise HTTPException(503, "Payment status could not be verified; retry safely") from exc

    exact_terms = (
        payment.get("id") == payload.razorpay_payment_id
        and payment.get("order_id") == payload.razorpay_order_id
        and payment.get("amount") == purchase.amount_minor
        and payment.get("currency") == purchase.currency
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        await session.execute(text("SELECT set_config('app.billing_system', 'on', true)"))
        current = await session.scalar(
            select(BillingCreditPurchase)
            .where(
                BillingCreditPurchase.id == purchase.id,
                BillingCreditPurchase.tenant_id == caller.tenant_id,
                BillingCreditPurchase.user_id == caller.user_id,
            )
            .with_for_update()
        )
        if current is None:
            raise HTTPException(404, "Credit purchase not found")
        if current.state == "paid":
            if current.provider_payment_id != payload.razorpay_payment_id:
                raise HTTPException(409, "A different payment already completed this order")
            return {"status": "paid"}
        if not exact_terms:
            current.state = "reconciliation_required"
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"status": "reconciliation_required"},
            )
        if payment.get("status") != "captured":
            if payment.get("status") == "failed":
                return {"status": "failed"}
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={"status": "processing"},
            )
        current.provider_payment_id = payload.razorpay_payment_id
        current.state = "paid"
        session.add(
            BillingCreditEntry(
                tenant_id=current.tenant_id,
                billing_account_id=current.billing_account_id,
                purchase_id=current.id,
                entry_type="grant",
                available_delta=current.unit_grant,
                reserved_delta=0,
                idempotency_key=f"credit-grant:{current.id}",
            )
        )
    return {"status": "paid"}


@router.post("/portal")
async def cancel_caller_subscription(caller: CallerDep) -> dict[str, object]:
    """Schedule cancellation at the current paid cycle end; immediate revoke is unsupported."""
    settings = get_settings()
    if not razorpay_subscriptions_available(settings):
        raise HTTPException(503, "Paid subscriptions are not available")
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        subscription = await session.scalar(
            select(RazorpaySubscription)
            .where(
                RazorpaySubscription.tenant_id == caller.tenant_id,
                RazorpaySubscription.user_id == caller.user_id,
                RazorpaySubscription.status.in_(
                    ("authenticated", "active", "pending", "halted", "paused")
                ),
            )
            .order_by(RazorpaySubscription.created_at.desc())
            .limit(1)
        )
        if subscription is None:
            raise HTTPException(404, "An active subscription was not found")
        subscription_id = subscription.subscription_id
    try:
        result = await cancel_razorpay_subscription(
            settings, subscription_id=subscription_id, cancel_at_cycle_end=True
        )
    except RazorpayUnavailable as exc:
        raise HTTPException(
            503, "Cancellation status is uncertain; check subscription status before retrying"
        ) from exc
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        await session.execute(
            update(RazorpaySubscription)
            .where(RazorpaySubscription.subscription_id == subscription_id)
            .values(
                status=result.get("status", "active"),
                cancel_at_cycle_end=bool(result.get("cancel_at_cycle_end", True)),
            )
        )
    return {"status": result.get("status", "active"), "cancelAtCycleEnd": True}


async def read_caller_entitlement(caller: Caller) -> BillingEntitlement:
    """Bind the authenticated owner to RLS before reading their projection."""
    settings = get_settings()
    internal_access = caller.user_id in settings.BILLING_INTERNAL_UNMETERED_USER_IDS
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"),
            {"id": str(caller.user_id)},
        )
        if get_settings().BILLING_ENFORCEMENT_ENABLED:
            await ensure_default_free_period(
                session, tenant_id=caller.tenant_id, user_id=caller.user_id
            )
        entitlement = await read_entitlement(
            session, tenant_id=caller.tenant_id, user_id=caller.user_id
        )
    if internal_access:
        return BillingEntitlement(
            status=EntitlementStatus.active,
            allowed_modes=[AllowedMode.focused, AllowedMode.balanced, AllowedMode.deep],
            internal_access=True,
        )
    return entitlement


@router.get(
    "/entitlement",
    response_model=BillingEntitlement,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
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


MAX_RAZORPAY_EVENT_BYTES = 1_000_000
_SUBSCRIPTION_EVENTS = {
    "subscription.authenticated": "authenticated",
    "subscription.activated": "active",
    "subscription.charged": "active",
    "subscription.pending": "pending",
    "subscription.halted": "halted",
    "subscription.cancelled": "cancelled",
    "subscription.paused": "paused",
    "subscription.resumed": "active",
    "subscription.completed": "completed",
}


def _provider_timestamp(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _monthly_period_bounds(
    billing_period: str, cycle_start: datetime, cycle_end: datetime
) -> list[tuple[datetime, datetime]] | None:
    if cycle_start.tzinfo is None or cycle_end.tzinfo is None or cycle_start >= cycle_end:
        return None
    if billing_period == "monthly":
        return [(cycle_start, cycle_end)]
    if billing_period != "yearly" or _add_calendar_months(cycle_start, 12) != cycle_end:
        return None
    periods = []
    for month in range(12):
        start = _add_calendar_months(cycle_start, month)
        end = cycle_end if month == 11 else _add_calendar_months(cycle_start, month + 1)
        periods.append((start, end))
    return periods


async def _grant_subscription_cycle(
    session: Any,
    *,
    subscription: RazorpaySubscription,
    payment: dict[str, Any],
    cycle_start: datetime,
    cycle_end: datetime,
) -> str:
    """Grant current/future monthly periods from a captured billing cycle, once."""
    if subscription.plan_key not in ("scholar", "investigator"):
        return "reconciliation_required"
    plan_key = cast(Literal["scholar", "investigator"], subscription.plan_key)
    terms = BILLING_CATALOG.plans[plan_key]
    expected_price = (
        terms.monthly_price if subscription.billing_period == "monthly" else terms.annual_price
    )
    expected_minor = int(expected_price * 100) if expected_price is not None else -1
    if (
        payment.get("status") != "captured"
        or payment.get("subscription_id") not in (None, subscription.subscription_id)
        or isinstance(payment.get("amount"), bool)
        or payment.get("amount") != expected_minor
        or payment.get("currency") != "INR"
        or cycle_start.tzinfo is None
        or cycle_end.tzinfo is None
        or cycle_start >= cycle_end
    ):
        return "reconciliation_required"

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"billing-account-v1:{subscription.tenant_id}:{subscription.user_id}"},
    )
    account_id = await session.scalar(
        select(BillingAccount.id).where(
            BillingAccount.tenant_id == subscription.tenant_id,
            BillingAccount.user_id == subscription.user_id,
        )
    )
    if account_id is None:
        return "reconciliation_required"

    existing_payment = await session.scalar(
        select(RazorpaySubscriptionPayment).where(
            RazorpaySubscriptionPayment.payment_id == payment["id"]
        )
    )
    if existing_payment is not None and existing_payment.status == "processed":
        return str(existing_payment.status)
    if (
        existing_payment is not None
        and existing_payment.subscription_id != subscription.subscription_id
    ):
        return "reconciliation_required"

    starts = _monthly_period_bounds(subscription.billing_period, cycle_start, cycle_end)
    if starts is None:
        return "reconciliation_required"

    # A renewal can overlap a still-active row only at its exact boundary. End
    # any prior monthly grant at the new provider-confirmed cycle boundary.
    overlap_rows = (
        await session.scalars(
            select(BillingPeriod)
            .where(
                BillingPeriod.tenant_id == subscription.tenant_id,
                BillingPeriod.billing_account_id == account_id,
                BillingPeriod.state == "active",
                BillingPeriod.starts_at < cycle_end,
                BillingPeriod.ends_at > cycle_start,
            )
            .with_for_update()
        )
    ).all()
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :tenant, true), "
            "set_config('app.user_id', :user, true)"
        ),
        {"tenant": str(subscription.tenant_id), "user": str(subscription.user_id)},
    )
    for row in overlap_rows:
        if row.plan_key != "free" and (
            row.plan_key != subscription.plan_key or row.starts_at >= cycle_start
        ):
            return "reconciliation_required"
        if cycle_start <= datetime.now(UTC):
            await transition_period_state(
                session,
                tenant_id=subscription.tenant_id,
                user_id=subscription.user_id,
                period=row,
                next_state="ended",
                effective_at=cycle_start,
            )

    for start, end in starts:
        state = (
            "ended"
            if end <= datetime.now(UTC)
            else ("active" if start <= datetime.now(UTC) < end else "pending")
        )
        period_row = BillingPeriod(
            tenant_id=subscription.tenant_id,
            billing_account_id=account_id,
            plan_key=subscription.plan_key,
            catalog_version=subscription.catalog_version,
            state=state,
            allowance_units=terms.monthly_allowance_units,
            starts_at=start,
            ends_at=end,
        )
        session.add(period_row)
    if existing_payment is not None:
        existing_payment.amount_minor = expected_minor
        existing_payment.currency = "INR"
        existing_payment.status = "processed"
    else:
        session.add(
            RazorpaySubscriptionPayment(
                payment_id=payment["id"],
                subscription_id=subscription.subscription_id,
                amount_minor=expected_minor,
                currency="INR",
                status="processed",
            )
        )
    return "processed"


async def _save_subscription_payment_for_reconciliation(
    session: Any, *, subscription: RazorpaySubscription, payment: dict[str, Any]
) -> None:
    """Persist the provider payment ID from a signed event for safe later recovery."""
    payment_id = payment.get("id")
    amount = payment.get("amount")
    currency = payment.get("currency")
    if (
        not isinstance(payment_id, str)
        or not payment_id.startswith("pay_")
        or isinstance(amount, bool)
        or not isinstance(amount, int)
        or amount <= 0
        or not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isalpha()
        or not currency.isupper()
    ):
        return
    existing = await session.scalar(
        select(RazorpaySubscriptionPayment)
        .where(RazorpaySubscriptionPayment.payment_id == payment_id)
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.subscription_id == subscription.subscription_id
            and existing.status != "processed"
        ):
            existing.amount_minor = amount
            existing.currency = currency
            existing.status = "reconciliation_required"
        return
    session.add(
        RazorpaySubscriptionPayment(
            payment_id=payment_id,
            subscription_id=subscription.subscription_id,
            amount_minor=amount,
            currency=currency,
            status="reconciliation_required",
        )
    )


@router.post("/webhooks/razorpay", response_model=None)
async def receive_razorpay_webhook(request: Request) -> dict[str, object] | JSONResponse:
    """Verify raw bytes and durably apply captured payments exactly once."""
    settings = get_settings()
    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    if webhook_secret is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Razorpay webhook is not configured"
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_RAZORPAY_EVENT_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Razorpay event is too large"
            )
    event_id = request.headers.get("x-razorpay-event-id", "")
    signature = request.headers.get("x-razorpay-signature", "")
    if not event_id or len(event_id) > 255 or any(ord(char) < 32 for char in event_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Razorpay event id")
    if not webhook_signature_valid(body=bytes(body), signature=signature, secret=webhook_secret):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Razorpay webhook signature")
    try:
        event = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Razorpay event") from exc
    if not isinstance(event, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Razorpay event envelope")
    event_type = event.get("event")
    payload = event.get("payload")
    payment_container = payload.get("payment") if isinstance(payload, dict) else None
    payment_entity = (
        payment_container.get("entity") if isinstance(payment_container, dict) else None
    )
    subscription_container = payload.get("subscription") if isinstance(payload, dict) else None
    subscription_entity = (
        subscription_container.get("entity") if isinstance(subscription_container, dict) else None
    )
    if not isinstance(event_type, str) or not 1 <= len(event_type) <= 160:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Razorpay event type")
    if event_type == "payment.captured":
        if (
            not isinstance(payment_entity, dict)
            or not isinstance(payment_entity.get("id"), str)
            or not isinstance(payment_entity.get("order_id"), str)
            or isinstance(payment_entity.get("amount"), bool)
            or not isinstance(payment_entity.get("amount"), int)
            or payment_entity.get("currency") not in SUPPORTED_CURRENCY_CODES
            or payment_entity.get("status") != "captured"
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid captured payment event")
    if event_type in _SUBSCRIPTION_EVENTS and (
        not isinstance(subscription_entity, dict)
        or not isinstance(subscription_entity.get("id"), str)
        or not subscription_entity["id"].startswith("sub_")
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Razorpay subscription event")

    payment_id = payment_entity.get("id") if isinstance(payment_entity, dict) else None
    reconciliation_required = False
    duplicate = False
    async with system_session() as session:
        await session.execute(text("SELECT set_config('app.billing_system', 'on', true)"))
        inserted = await session.scalar(
            insert(RazorpayWebhookEvent)
            .values(
                event_id=event_id,
                event_type=event_type,
                payment_id=payment_id if isinstance(payment_id, str) else None,
                processing_status="received"
                if event_type == "payment.captured" or event_type in _SUBSCRIPTION_EVENTS
                else "ignored",
            )
            .on_conflict_do_nothing(index_elements=[RazorpayWebhookEvent.event_id])
            .returning(RazorpayWebhookEvent.event_id)
        )
        duplicate = inserted is None
        if duplicate:
            previous = await session.scalar(
                select(RazorpayWebhookEvent).where(RazorpayWebhookEvent.event_id == event_id)
            )
            if previous is None or previous.processing_status != "received":
                return {"received": True, "duplicate": True}
        if event_type == "payment.captured" and isinstance(payment_entity, dict):
            purchase = await session.scalar(
                select(BillingCreditPurchase)
                .where(
                    BillingCreditPurchase.payment_provider == "razorpay",
                    BillingCreditPurchase.provider_order_id == payment_entity["order_id"],
                )
                .with_for_update()
            )
            if purchase is None:
                processing_status = "ignored"
            elif payment_entity["id"] == purchase.provider_payment_id and purchase.state == "paid":
                processing_status = "processed"
            elif (
                payment_entity["amount"] != purchase.amount_minor
                or payment_entity["currency"] != purchase.currency
                or purchase.state != "pending"
                or purchase.provider_order_state != "created"
                or purchase.provider_payment_id is not None
            ):
                if purchase.state in {"pending", "paid", "failed", "disputed"}:
                    purchase.state = "reconciliation_required"
                processing_status = "reconciliation_required"
                reconciliation_required = True
            else:
                purchase.provider_payment_id = payment_entity["id"]
                purchase.state = "paid"
                session.add(
                    BillingCreditEntry(
                        tenant_id=purchase.tenant_id,
                        billing_account_id=purchase.billing_account_id,
                        purchase_id=purchase.id,
                        entry_type="grant",
                        available_delta=purchase.unit_grant,
                        reserved_delta=0,
                        idempotency_key=f"credit-grant:{purchase.id}",
                    )
                )
                processing_status = "processed"
            await session.execute(
                update(RazorpayWebhookEvent)
                .where(RazorpayWebhookEvent.event_id == event_id)
                .values(processing_status=processing_status)
            )
        elif event_type in _SUBSCRIPTION_EVENTS and isinstance(subscription_entity, dict):
            subscription = await session.scalar(
                select(RazorpaySubscription)
                .where(RazorpaySubscription.subscription_id == subscription_entity["id"])
                .with_for_update()
            )
            processing_status = "reconciliation_required"
            if subscription is not None:
                event_created = _provider_timestamp(event.get("created_at"))
                provider_plan_id = subscription_entity.get("plan_id")
                if provider_plan_id != subscription.provider_plan_id:
                    subscription.status = "reconciliation_required"
                    reconciliation_required = True
                elif (
                    event_created is not None
                    and subscription.last_event_created is not None
                    and event_created < subscription.last_event_created
                ):
                    processing_status = "ignored"
                else:
                    next_status = _SUBSCRIPTION_EVENTS[event_type]
                    start = _provider_timestamp(subscription_entity.get("current_start"))
                    end = _provider_timestamp(subscription_entity.get("current_end"))
                    if start is not None:
                        subscription.current_period_start = start
                    if end is not None:
                        subscription.current_period_end = end
                    expected_price = None
                    if subscription.plan_key in {"scholar", "investigator"}:
                        plan_key = cast(
                            Literal["scholar", "investigator"],
                            subscription.plan_key,
                        )
                        plan_terms = BILLING_CATALOG.plans[plan_key]
                        expected_price = (
                            plan_terms.monthly_price
                            if subscription.billing_period == "monthly"
                            else plan_terms.annual_price
                        )
                    expected_minor = int(expected_price * 100) if expected_price is not None else -1
                    confirmed_full_charge = (
                        isinstance(payment_entity, dict)
                        and payment_entity.get("status") == "captured"
                        and payment_entity.get("amount") == expected_minor
                        and payment_entity.get("currency") == "INR"
                    )
                    if event_type == "subscription.charged" or (
                        event_type == "subscription.activated" and confirmed_full_charge
                    ):
                        if (
                            confirmed_full_charge
                            and isinstance(payment_entity, dict)
                            and isinstance(payment_entity.get("id"), str)
                            and start is not None
                            and end is not None
                        ):
                            processing_status = await _grant_subscription_cycle(
                                session,
                                subscription=subscription,
                                payment=payment_entity,
                                cycle_start=start,
                                cycle_end=end,
                            )
                        else:
                            processing_status = "reconciliation_required"
                        if processing_status == "reconciliation_required":
                            subscription.status = "reconciliation_required"
                            reconciliation_required = True
                        else:
                            subscription.status = "active"
                    else:
                        subscription.status = next_status
                        if event_type == "subscription.cancelled":
                            subscription.cancel_at_cycle_end = bool(
                                subscription_entity.get("cancel_at_cycle_end", False)
                            )
                        processing_status = "processed"
                    if event_created is not None:
                        subscription.last_event_created = event_created
                    subscription.last_event_id = event_id
                if (
                    processing_status == "reconciliation_required"
                    and event_type in {"subscription.charged", "subscription.activated"}
                    and isinstance(payment_entity, dict)
                ):
                    await _save_subscription_payment_for_reconciliation(
                        session, subscription=subscription, payment=payment_entity
                    )
            await session.execute(
                update(RazorpayWebhookEvent)
                .where(RazorpayWebhookEvent.event_id == event_id)
                .values(processing_status=processing_status)
            )
    if reconciliation_required:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"received": True, "reconciliationRequired": True},
        )
    return {"received": True, "duplicate": duplicate, "eventId": event_id}
