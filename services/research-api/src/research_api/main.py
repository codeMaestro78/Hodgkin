import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from time import monotonic

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from research_api.api import router as research_router
from research_api.auth import identity_transport
from research_api.billing.api import router as billing_router
from research_api.billing.stripe import (
    StripeUnavailable,
    app_base_url,
    configured_portal,
    configured_prices,
    validate_stripe_key_mode,
)
from research_api.checkpointing import CheckpointPool
from research_api.comparison_api import router as comparison_router
from research_api.config import Settings, configuration_files, get_settings
from research_api.db.runtime_security import validate_runtime_role
from research_api.db.session import engine
from research_api.dispatcher import dispatch_loop
from research_api.events.wakeups import event_wakeups
from research_api.library_api import router as library_router
from research_api.providers.http_clients import provider_http_transport
from research_api.runtime_api import router as runtime_router
from research_api.sharing_exports_api import router as sharing_exports_router
from research_api.telemetry import dependency_logging, operation_event, request_id


class RequestTiming:
    """Pure ASGI instrumentation: distinguish SSE header latency from stream life."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        try:
            identity = str(uuid.UUID(supplied))
        except ValueError:
            identity = str(uuid.uuid4())
        token = request_id.set(identity)
        started = monotonic()
        status_code = 500
        first_byte_ms = None

        async def timed_send(message: Message) -> None:
            nonlocal status_code, first_byte_ms
            if message["type"] == "http.response.start":
                status_code = message["status"]
                first_byte_ms = round((monotonic() - started) * 1000, 2)
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", identity.encode()),
                ]
                operation_event(
                    "http.headers",
                    started=started,
                    statusCode=status_code,
                    route=getattr(scope.get("route"), "path", "unmatched"),
                )
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        except BaseException as exc:
            operation_event(
                "http.request",
                started=started,
                outcome="failed",
                error=exc,
                statusCode=status_code,
                firstByteMs=first_byte_ms,
            )
            raise
        else:
            operation_event(
                "http.request",
                started=started,
                outcome=(
                    "failed"
                    if status_code >= 500
                    else "rejected"
                    if status_code >= 400
                    else "succeeded"
                ),
                statusCode=status_code,
                firstByteMs=first_byte_ms,
                route=getattr(scope.get("route"), "path", "unmatched"),
            )
        finally:
            request_id.reset(token)


def _should_start_embedded_dispatcher(settings: Settings) -> bool:
    """Run the in-process worker locally, but use the Daemon on Vercel."""
    return bool(
        settings.DISPATCHER_ENABLED
        and settings.APP_ENV != "test"
        and not os.environ.get("VERCEL")
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    with dependency_logging():
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(identity_transport())
            settings = get_settings()
            await stack.enter_async_context(
                provider_http_transport(
                    timeout_seconds=settings.PROVIDER_TIMEOUT_SECONDS,
                    worker_concurrency=settings.WORKER_CONCURRENCY,
                )
            )
            operation_event(
                "runtime.configuration",
                started=monotonic(),
                envFiles=configuration_files(),
                modelRoutes=settings.model_routing_snapshot(),
                modelCredentialsConfigured={
                    role: settings.model_api_key(settings.model_route(role).provider) is not None
                    for role in ("planner", "writer", "claim_review")
                },
                redisWakeupsEnabled=settings.SSE_REDIS_WAKEUPS_ENABLED,
            )
            await stack.enter_async_context(
                event_wakeups.transport(
                    settings.REDIS_URL
                    if settings.SSE_REDIS_WAKEUPS_ENABLED and settings.APP_ENV != "test"
                    else None
                )
            )
            if settings.APP_ENV != "test":
                await validate_runtime_role(engine)
            # Vercel Functions are request-driven and may be stopped between
            # requests; the dedicated research-worker Daemon owns dispatch there.
            if _should_start_embedded_dispatcher(settings):
                async with CheckpointPool(settings) as pool:
                    dispatcher = asyncio.create_task(dispatch_loop(settings, pool))
                    try:
                        yield
                    finally:
                        dispatcher.cancel()
                        await asyncio.gather(dispatcher, return_exceptions=True)
            else:
                yield


app = FastAPI(title="Research API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestTiming)
app.include_router(research_router)
app.include_router(runtime_router)
app.include_router(comparison_router)
app.include_router(library_router)
app.include_router(sharing_exports_router)
app.include_router(billing_router)


@app.get("/health", tags=["health"])
@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "research-api"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    settings = get_settings()
    if settings.BILLING_STRIPE_ENABLED:
        try:
            if not settings.BILLING_ENFORCEMENT_ENABLED:
                raise StripeUnavailable("quota enforcement must be active before sales")
            if settings.STRIPE_LIVEMODE and not settings.BILLING_LIVE_LAUNCH_APPROVED:
                raise StripeUnavailable("live billing launch has not been approved")
            if (
                settings.STRIPE_SECRET_KEY is None
                or settings.STRIPE_WEBHOOK_SECRET is None
                or not settings.STRIPE_API_VERSION
            ):
                raise StripeUnavailable("Stripe secrets are not configured")
            configured_prices(settings)
            configured_portal(settings)
            app_base_url(settings)
            validate_stripe_key_mode(settings)
        except StripeUnavailable as exc:
            raise HTTPException(503, "Stripe billing configuration is incomplete") from exc
    try:
        await validate_runtime_role(engine)
        async with engine.connect() as connection:
            required_revision = (
                "0028"
                if settings.BILLING_STRIPE_ENABLED
                else "0026"
                if settings.BILLING_ENFORCEMENT_ENABLED
                else "0022"
            )
            migration_table_exists = await connection.scalar(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            )
            if not migration_table_exists:
                raise HTTPException(
                    503, f"database migrations through {required_revision} are required"
                )
            migration_history_readable = await connection.scalar(
                text(
                    "SELECT has_table_privilege(current_user, "
                    "'public.alembic_version', 'SELECT')"
                )
            )
            if migration_history_readable:
                migration_ready = await connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM public.alembic_version "
                        "WHERE version_num >= :revision)"
                    ),
                    {"revision": required_revision},
                )
                if not migration_ready:
                    raise HTTPException(
                        503, f"database migrations through {required_revision} are required"
                    )
            ready = await connection.scalar(
                text(
                    "SELECT to_regclass('public.runtime_jobs') "
                    "IS NOT NULL AND to_regclass('research_checkpoints.checkpoints') IS NOT NULL "
                    "AND to_regclass('public.projects') IS NOT NULL "
                    "AND to_regclass('public.library_items') IS NOT NULL "
                    "AND to_regclass('public.report_shares') IS NOT NULL "
                    "AND to_regclass('public.report_exports') IS NOT NULL "
                    "AND to_regclass('public.billing_accounts') IS NOT NULL "
                    "AND to_regclass('public.billing_periods') IS NOT NULL "
                    "AND to_regclass('public.billing_unit_entries') IS NOT NULL "
                    "AND (NOT :stripe_enabled OR ("
                    "to_regclass('public.stripe_webhook_events') IS NOT NULL AND "
                    "to_regclass('public.stripe_customer_links') IS NOT NULL AND "
                    "to_regclass('public.stripe_subscriptions') IS NOT NULL AND "
                    "to_regclass('public.stripe_checkout_attempts') IS NOT NULL)) "
                    "AND EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='research_runs' "
                    "AND column_name='model_routing')"
                ),
                {"stripe_enabled": settings.BILLING_STRIPE_ENABLED},
            )
        if not ready:
            raise HTTPException(503, "database schema required by this API is incomplete")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "database unavailable") from exc
    return {"status": "ok", "environment": settings.APP_ENV}
