"""Bounded workers drain durable jobs. A process exit leaves a recoverable lease."""

import asyncio
import uuid
from time import monotonic
from typing import Any

from sqlalchemy import select

from research_api import jobs
from research_api.checkpointing import TenantPostgresSaver
from research_api.config import Settings
from research_api.db.models import Budget, PlanApproval, ResearchRun, RuntimeJob
from research_api.db.session import tenant_session
from research_api.graph.builder import run_graph
from research_api.runtime_context import JobFence, LeaseLostError, current_job
from research_api.telemetry import dependency_run, dispatcher_slot_event, operation_event


async def execute(fence: JobFence, settings: Settings, pool: Any) -> None:
    task = asyncio.current_task()
    assert task is not None
    last_beat = monotonic()
    execution_started = last_beat

    async def pulse() -> None:
        nonlocal last_beat
        while True:
            await asyncio.sleep(settings.WORKER_LEASE_SECONDS / 3)
            now = monotonic()
            try:
                alive = await jobs.heartbeat(fence, int((now - last_beat) * 1000), settings)
            except Exception as exc:
                operation_event("dispatcher.heartbeat", started=now, outcome="failed", error=exc)
                task.cancel()
                return
            if not alive:
                task.cancel()
                return
            last_beat = now

    # Create the heartbeat without inheriting a graph fence (it updates that job).
    heartbeat = asyncio.create_task(pulse())
    token = current_job.set(fence)
    run_token = dependency_run.set(fence.run_id)
    stopped = False
    try:
        async with tenant_session(str(fence.tenant_id)) as session:
            row = (
                await session.execute(
                    select(ResearchRun, RuntimeJob, Budget)
                    .join(
                        RuntimeJob,
                        (RuntimeJob.run_id == ResearchRun.id)
                        & (RuntimeJob.tenant_id == ResearchRun.tenant_id),
                    )
                    .join(
                        Budget,
                        (Budget.run_id == ResearchRun.id)
                        & (Budget.tenant_id == ResearchRun.tenant_id),
                    )
                    .where(ResearchRun.tenant_id == fence.tenant_id, ResearchRun.id == fence.run_id)
                )
            ).first()
            if row is None:
                raise LookupError("queued research data missing")
            run, job, budget = row
            choice = (
                await session.scalar(
                    select(PlanApproval).where(
                        PlanApproval.tenant_id == fence.tenant_id,
                        PlanApproval.run_id == fence.run_id,
                        PlanApproval.plan_id == run.active_plan_id,
                    )
                )
                if run.active_plan_id
                else None
            )
            resume = (
                {"planId": str(choice.plan_id), "decision": choice.decision} if choice else None
            )
            user, question = run.user_id, run.original_question
            remaining = max(0, budget.max_wall_clock_ms - job.active_ms)
        saver = TenantPostgresSaver(pool, fence.tenant_id, fence.run_id)
        remaining = max(0, remaining - int((monotonic() - execution_started) * 1000))
        operation_event(
            "dispatcher.budget",
            started=execution_started,
            remainingMs=remaining,
            limitMs=budget.max_wall_clock_ms,
        )
        await run_graph(
            settings,
            run_id=fence.run_id,
            tenant_id=fence.tenant_id,
            user_id=user,
            question=question,
            checkpointer=saver,
            resume=resume,
            remaining_ms=remaining,
        )
        stopped = True
    except (asyncio.CancelledError, LeaseLostError):
        # Never terminalize a newer owner's job or resume an ambiguous provider call.
        raise
    except Exception as exc:
        operation_event("dispatcher.execute", started=last_beat, outcome="failed", error=exc)
        # Leave the leased job for bounded recovery; do not discard a queued run.
    finally:
        current_job.reset(token)
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        try:
            if stopped:
                await jobs.finish(fence, int((monotonic() - last_beat) * 1000))
        finally:
            dependency_run.reset(run_token)


async def dispatch_loop(settings: Settings, pool: Any) -> None:
    owner = uuid.uuid4()
    tasks: set[asyncio.Task[None]] = set()
    active_tasks: set[asyncio.Task[None]] = set()

    async def execute_tracked(fence: JobFence) -> None:
        task = asyncio.current_task()
        assert task is not None
        active_tasks.add(task)
        dispatcher_slot_event(
            worker_instance_id=owner,
            run_id=fence.run_id,
            phase="acquired",
            active_workers=len(active_tasks),
            concurrency_limit=settings.WORKER_CONCURRENCY,
        )
        try:
            await execute(fence, settings, pool)
        finally:
            active_tasks.discard(task)
            dispatcher_slot_event(
                worker_instance_id=owner,
                run_id=fence.run_id,
                phase="released",
                active_workers=len(active_tasks),
                concurrency_limit=settings.WORKER_CONCURRENCY,
            )

    try:
        while True:
            # Retrieve exceptions, including cancellations, instead of discarding tasks.
            for task in list(tasks):
                if task.done():
                    tasks.remove(task)
                    if not task.cancelled():
                        task.exception()
            if len(tasks) < settings.WORKER_CONCURRENCY:
                poll_started = monotonic()
                try:
                    for tenant in await jobs.discover():
                        if len(tasks) >= settings.WORKER_CONCURRENCY:
                            break
                        fence = await jobs.claim(tenant, owner, settings)
                        if fence:
                            tasks.add(asyncio.create_task(execute_tracked(fence)))
                except Exception as exc:
                    operation_event(
                        "dispatcher.poll", started=poll_started, outcome="failed", error=exc
                    )
            await asyncio.sleep(1)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
