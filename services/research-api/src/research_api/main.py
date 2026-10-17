import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from time import monotonic

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from research_api.api import router as research_router
from research_api.auth import identity_transport
from research_api.checkpointing import CheckpointPool
from research_api.comparison_api import router as comparison_router
from research_api.config import configuration_files, get_settings
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
            if settings.DISPATCHER_ENABLED and settings.APP_ENV != "test":
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


@app.get("/health", tags=["health"])
@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "research-api"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    settings = get_settings()
    try:
        await validate_runtime_role(engine)
        async with engine.connect() as connection:
            migration_table_exists = await connection.scalar(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            )
            migration_ready = bool(
                migration_table_exists
                and await connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM public.alembic_version "
                        "WHERE version_num >= '0019')"
                    )
                )
            )
            if not migration_ready:
                raise HTTPException(503, "database migrations through 0019 are required")
            ready = await connection.scalar(
                text(
                    "SELECT to_regclass('public.runtime_jobs') "
                    "IS NOT NULL AND to_regclass('research_checkpoints.checkpoints') IS NOT NULL "
                    "AND to_regclass('public.projects') IS NOT NULL "
                    "AND to_regclass('public.library_items') IS NOT NULL "
                    "AND to_regclass('public.report_shares') IS NOT NULL "
                    "AND to_regclass('public.report_exports') IS NOT NULL "
                    "AND EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='research_runs' "
                    "AND column_name='model_routing')"
                )
            )
        if not ready:
            raise HTTPException(503, "database schema required by this API is incomplete")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "database unavailable") from exc
    return {"status": "ok", "environment": settings.APP_ENV}
