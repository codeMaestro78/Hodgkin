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
    validate_monthly_price,
)
from research_api.billing.subscriptions import apply_checkout_event, apply_subscription_event
from research_api.config import Settings, get_settings
from research_api.db.models import (
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
                raise HTTPException(409, "A secure checkout is already open for this account")
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
