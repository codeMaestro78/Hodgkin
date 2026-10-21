"""Billing read, operator and public signed-webhook endpoints."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from research_api.auth import Caller, authenticated_caller
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
)
from research_api.billing.razorpay import (
    RazorpayUnavailable,
    configured_key_id,
    payment_signature_valid,
    webhook_signature_valid,
)
from research_api.billing.razorpay import (
    create_order as create_razorpay_order,
)
from research_api.billing.razorpay import (
    fetch_payment as fetch_razorpay_payment,
)
from research_api.config import get_settings
from research_api.db.models import (
    BillingAccount,
    BillingCreditEntry,
    BillingCreditPurchase,
    RazorpayWebhookEvent,
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


@router.get("/checkout-availability")
async def checkout_availability() -> dict[str, object]:
    """Paid subscriptions are disabled until a Razorpay Subscriptions flow exists."""
    return {"enabled": False, "plans": []}


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
        "currency": "INR",
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
    stable_key = "research-billing-v1:razorpay-credit-checkout:" + hashlib.sha256(
        f"{caller.tenant_id}:{caller.user_id}:{request_key}".encode()
    ).hexdigest()
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
    """Create/reuse a Razorpay order from an immutable, server-owned INR pack."""
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


@router.post("/checkout")
async def create_checkout_session() -> None:
    """Subscription checkout has no active provider implementation."""
    raise HTTPException(status.HTTP_410_GONE, "Monthly plan checkout is unavailable")


@router.post("/portal")
async def create_portal_session() -> None:
    """Subscription self-service has no active provider implementation."""
    raise HTTPException(status.HTTP_410_GONE, "Subscription management is unavailable")


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


MAX_RAZORPAY_EVENT_BYTES = 1_000_000


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
    entity = payment_container.get("entity") if isinstance(payment_container, dict) else None
    if not isinstance(event_type, str) or not 1 <= len(event_type) <= 160:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Razorpay event type")
    if event_type == "payment.captured":
        if (
            not isinstance(entity, dict)
            or not isinstance(entity.get("id"), str)
            or not isinstance(entity.get("order_id"), str)
            or isinstance(entity.get("amount"), bool)
            or not isinstance(entity.get("amount"), int)
            or entity.get("currency") != "INR"
            or entity.get("status") != "captured"
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid captured payment event")

    payment_id = entity.get("id") if isinstance(entity, dict) else None
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
                processing_status="received" if event_type == "payment.captured" else "ignored",
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
        if event_type == "payment.captured" and isinstance(entity, dict):
            purchase = await session.scalar(
                select(BillingCreditPurchase)
                .where(
                    BillingCreditPurchase.payment_provider == "razorpay",
                    BillingCreditPurchase.provider_order_id == entity["order_id"],
                )
                .with_for_update()
            )
            if purchase is None:
                processing_status = "ignored"
            elif (
                entity["id"] == purchase.provider_payment_id
                and purchase.state == "paid"
            ):
                processing_status = "processed"
            elif (
                entity["amount"] != purchase.amount_minor
                or entity["currency"] != purchase.currency
                or purchase.state != "pending"
                or purchase.provider_order_state != "created"
                or purchase.provider_payment_id is not None
            ):
                if purchase.state in {"pending", "paid", "failed", "disputed"}:
                    purchase.state = "reconciliation_required"
                processing_status = "reconciliation_required"
                reconciliation_required = True
            else:
                purchase.provider_payment_id = entity["id"]
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
    if reconciliation_required:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"received": True, "reconciliationRequired": True},
        )
    return {"received": True, "duplicate": duplicate, "eventId": event_id}
