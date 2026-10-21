"""Long-running durable research-job worker for container/daemon deployments."""

from __future__ import annotations

import asyncio
import signal
from contextlib import AsyncExitStack
from time import monotonic

from research_api.checkpointing import CheckpointPool
from research_api.config import get_settings
from research_api.db.runtime_security import validate_runtime_role
from research_api.db.session import engine
from research_api.dispatcher import dispatch_loop
from research_api.events.wakeups import event_wakeups
from research_api.providers.http_clients import provider_http_transport
from research_api.telemetry import dependency_logging, operation_event


async def run_worker() -> None:
    """Initialize worker-owned pools and run the durable dispatcher until SIGTERM."""
    settings = get_settings()
    if settings.APP_ENV == "test":
        raise RuntimeError("the research worker must not run with APP_ENV=test")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    with dependency_logging():
        try:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(
                    provider_http_transport(
                        timeout_seconds=settings.PROVIDER_TIMEOUT_SECONDS,
                        worker_concurrency=settings.WORKER_CONCURRENCY,
                    )
                )
                await stack.enter_async_context(
                    event_wakeups.transport(
                        settings.REDIS_URL if settings.SSE_REDIS_WAKEUPS_ENABLED else None
                    )
                )
                await validate_runtime_role(engine)
                async with CheckpointPool(settings) as pool:
                    operation_event(
                        "runtime.worker",
                        started=monotonic(),
                        outcome="started",
                        workerConcurrency=settings.WORKER_CONCURRENCY,
                    )
                    dispatcher = asyncio.create_task(dispatch_loop(settings, pool))
                    try:
                        await stop.wait()
                    finally:
                        dispatcher.cancel()
                        await asyncio.gather(dispatcher, return_exceptions=True)
                        operation_event("runtime.worker", started=monotonic(), outcome="stopped")
        finally:
            await engine.dispose()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
