"""PostgreSQL is the queue. Registry discovery contains no research payloads."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic
from typing import cast

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.billing.ledger import (
    BillingLedgerError,
    BillingModeUnavailable,
    BillingUnitsExhausted,
)
from research_api.billing.lifecycle import settle_terminal_run
from research_api.config import Settings
from research_api.db.models import (
    DispatchRegistry,
    NodeExecution,
    ResearchRun,
    ResearchSchedule,
    RuntimeJob,
    SubQuestionAttempt,
)
from research_api.db.session import session_factory, tenant_session
from research_api.events.outbox import EventOutbox
from research_api.repositories.runs import RunBudgetDefaults, RunRepository
from research_api.runtime_context import JobFence
from research_api.telemetry import operation_event

GRAPH_VERSION = "research-v4"
# Older binaries reject this version instead of resuming a Serper receipt with
# Tavily. Existing v3/v4 jobs retain their original discovery semantics.
SERPER_GRAPH_VERSION = "research-v5-serper"
# v7 checkpoints include pre-reflection, write-once evidence assessment. Local
# v6 checkpoints must fail closed rather than resume into a different topology.
PREVIOUS_MODE_GRAPH_VERSION = "research-v7-assessed-modes"
PREVIOUS_MODE_SERPER_GRAPH_VERSION = "research-v7-assessed-modes-serper"
# v8 checkpoints publish report V3 without narrative composition; they resume
# unchanged. v9 adds the evidence-verified narrative pass and report V4.
PROVENANCE_MODE_GRAPH_VERSION = "research-v8-report-provenance"
PROVENANCE_MODE_SERPER_GRAPH_VERSION = "research-v8-report-provenance-serper"
NARRATIVE_MODE_GRAPH_VERSION = "research-v9-evidence-narrative"
NARRATIVE_MODE_SERPER_GRAPH_VERSION = "research-v9-evidence-narrative-serper"
# v9 checkpoints resume without repair. v10 may admit one bounded, budgeted
# repair round (child plan + delta assessment) for Balanced and Deep runs.
MODE_GRAPH_VERSION = "research-v10-bounded-repair"
MODE_SERPER_GRAPH_VERSION = "research-v10-bounded-repair-serper"
# v11 keeps the v10 explicit-mode report/repair topology and pins OpenAlex as
# an available academic route. OpenAlex is selected only for academic-planned
# tasks; other tasks retain the separately pinned Tavily/Serper route.
OPENALEX_GRAPH_VERSION = "research-v6-openalex"
OPENALEX_SERPER_GRAPH_VERSION = "research-v6-openalex-serper"
MODE_OPENALEX_GRAPH_VERSION = "research-v11-bounded-repair-openalex"
MODE_OPENALEX_SERPER_GRAPH_VERSION = "research-v11-bounded-repair-openalex-serper"
# v12 changes the criterion-review model request's output cap. Older jobs keep
# their original request fingerprint so recovery cannot redispatch that call.
EXPANDED_MODE_GRAPH_VERSION = "research-v12-criterion-budget"
EXPANDED_MODE_SERPER_GRAPH_VERSION = "research-v12-criterion-budget-serper"
EXPANDED_MODE_OPENALEX_GRAPH_VERSION = "research-v12-criterion-budget-openalex"
EXPANDED_MODE_OPENALEX_SERPER_GRAPH_VERSION = "research-v12-criterion-budget-openalex-serper"
# v13 keeps the criterion-budget contract but disables automatic repair by
# default. v14 opts in to the same bounded repair contract; existing v10-v12
# jobs retain their pinned semantics.
SAFE_MODE_GRAPH_VERSION = "research-v13-criterion-budget"
SAFE_MODE_SERPER_GRAPH_VERSION = "research-v13-criterion-budget-serper"
SAFE_MODE_OPENALEX_GRAPH_VERSION = "research-v13-criterion-budget-openalex"
SAFE_MODE_OPENALEX_SERPER_GRAPH_VERSION = "research-v13-criterion-budget-openalex-serper"
REPAIR_MODE_GRAPH_VERSION = "research-v14-criterion-budget-bounded-repair"
REPAIR_MODE_SERPER_GRAPH_VERSION = "research-v14-criterion-budget-bounded-repair-serper"
REPAIR_MODE_OPENALEX_GRAPH_VERSION = "research-v14-criterion-budget-bounded-repair-openalex"
REPAIR_MODE_OPENALEX_SERPER_GRAPH_VERSION = (
    "research-v14-criterion-budget-bounded-repair-openalex-serper"
)


def graph_version_for(settings: Settings, *, explicit_mode: bool) -> str:
    """Pin discovery and bounded-repair capabilities when the job is created."""
    if explicit_mode:
        repair_versions = settings.BOUNDED_GAP_REPAIR_ENABLED
        if settings.OPENALEX_DISCOVERY_ENABLED:
            if settings.SERPER_DISCOVERY_ENABLED:
                return (
                    REPAIR_MODE_OPENALEX_SERPER_GRAPH_VERSION
                    if repair_versions
                    else SAFE_MODE_OPENALEX_SERPER_GRAPH_VERSION
                )
            return (
                REPAIR_MODE_OPENALEX_GRAPH_VERSION
                if repair_versions
                else SAFE_MODE_OPENALEX_GRAPH_VERSION
            )
        if settings.SERPER_DISCOVERY_ENABLED:
            return (
                REPAIR_MODE_SERPER_GRAPH_VERSION
                if repair_versions
                else SAFE_MODE_SERPER_GRAPH_VERSION
            )
        return REPAIR_MODE_GRAPH_VERSION if repair_versions else SAFE_MODE_GRAPH_VERSION
    if settings.OPENALEX_DISCOVERY_ENABLED:
        return (
            OPENALEX_SERPER_GRAPH_VERSION
            if settings.SERPER_DISCOVERY_ENABLED
            else OPENALEX_GRAPH_VERSION
        )
    return SERPER_GRAPH_VERSION if settings.SERPER_DISCOVERY_ENABLED else GRAPH_VERSION


async def lock_registry(session: AsyncSession, tenant: uuid.UUID) -> DispatchRegistry:
    await session.execute(
        insert(DispatchRegistry)
        .values(tenant_id=tenant)
        .on_conflict_do_nothing(index_elements=[DispatchRegistry.tenant_id])
    )
    row = await session.scalar(
        select(DispatchRegistry)
        .where(DispatchRegistry.tenant_id == tenant)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def enqueue(
    session: AsyncSession, run: ResearchRun, settings: Settings, batch_id: uuid.UUID | None = None
) -> None:
    registry = await lock_registry(session, run.tenant_id)
    count = await session.scalar(
        select(func.count())
        .select_from(RuntimeJob)
        .where(
            RuntimeJob.tenant_id == run.tenant_id,
            RuntimeJob.state.in_(["queued", "running", "waiting"]),
        )
    )
    if (count or 0) >= settings.MAX_PENDING_RUNS_PER_TENANT:
        raise HTTPException(429, "workspace research queue is full")
    session.add(
        RuntimeJob(
            run_id=run.id,
            tenant_id=run.tenant_id,
            user_id=run.user_id,
            batch_id=batch_id,
            graph_version=graph_version_for(settings, explicit_mode=run.mode is not None),
        )
    )
    registry.next_due_at = datetime.now(UTC)


async def discover() -> list[uuid.UUID]:
    # Explicit, restricted coordination exception: only registry IDs/wake-up times.
    async with session_factory() as session, session.begin():
        await session.execute(text("SELECT set_config('app.dispatcher','on',true)"))
        return list(
            await session.scalars(
                select(DispatchRegistry.tenant_id)
                .where(DispatchRegistry.next_due_at <= func.now())
                .order_by(DispatchRegistry.next_due_at, DispatchRegistry.tenant_id)
                .limit(100)
            )
        )


async def refresh_due(session: AsyncSession, registry: DispatchRegistry) -> None:
    queued = await session.scalar(
        select(func.count())
        .select_from(RuntimeJob)
        .where(RuntimeJob.tenant_id == registry.tenant_id, RuntimeJob.state == "queued")
    )
    if queued:
        registry.next_due_at = datetime.now(UTC)
        return
    lease = await session.scalar(
        select(func.min(RuntimeJob.lease_expires_at)).where(
            RuntimeJob.tenant_id == registry.tenant_id, RuntimeJob.state == "running"
        )
    )
    schedule = await session.scalar(
        select(func.min(ResearchSchedule.next_run_at)).where(
            ResearchSchedule.tenant_id == registry.tenant_id, ResearchSchedule.enabled.is_(True)
        )
    )
    registry.next_due_at = min([date for date in (lease, schedule) if date], default=None)


async def schedule_due(session: AsyncSession, tenant: uuid.UUID, settings: Settings) -> None:
    schedules = list(
        await session.scalars(
            select(ResearchSchedule)
            .where(
                ResearchSchedule.tenant_id == tenant,
                ResearchSchedule.enabled.is_(True),
                ResearchSchedule.next_run_at <= func.now(),
            )
            .order_by(ResearchSchedule.next_run_at)
            .with_for_update(skip_locked=True)
            .limit(5)
        )
    )
    count = await session.scalar(
        select(func.count())
        .select_from(RuntimeJob)
        .where(
            RuntimeJob.tenant_id == tenant, RuntimeJob.state.in_(["queued", "running", "waiting"])
        )
    )
    for schedule in schedules:
        if (count or 0) >= settings.MAX_PENDING_RUNS_PER_TENANT:
            break
        data = {
            **schedule.budget,
            "max_estimated_cost_usd": Decimal(schedule.budget["max_estimated_cost_usd"]),
        }
        try:
            async with session.begin_nested():
                run, created = await RunRepository(session, tenant).create_once(
                    user_id=schedule.user_id,
                    question=schedule.question,
                    budget=RunBudgetDefaults(**data),
                    idempotency_key=f"schedule:{schedule.id}:{schedule.next_run_at.isoformat()}",
                    approval_required=schedule.approval_required,
                    mode=schedule.mode,
                    mode_policy_version=schedule.mode_policy_version,
                )
        except (BillingUnitsExhausted, BillingModeUnavailable) as exc:
            schedule.last_quota_blocked_at = datetime.now(UTC)
            schedule.last_quota_blocked_reason = (
                "insufficient_units"
                if isinstance(exc, BillingUnitsExhausted)
                else "mode_unavailable"
            )
            schedule.next_run_at = datetime.now(UTC) + timedelta(minutes=schedule.interval_minutes)
            continue
        except BillingLedgerError:
            raise
        if created:
            schedule.last_quota_blocked_at = None
            schedule.last_quota_blocked_reason = None
            session.add(
                RuntimeJob(
                    run_id=run.id,
                    tenant_id=tenant,
                    user_id=run.user_id,
                    graph_version=graph_version_for(settings, explicit_mode=run.mode is not None),
                )
            )
            await EventOutbox(session, tenant).append(
                run_id=run.id,
                event_type="run.created",
                payload={"label": "Scheduled research queued"},
            )
            count = (count or 0) + 1
        # One occurrence, not an unbounded catch-up storm after downtime.
        schedule.next_run_at = datetime.now(UTC) + timedelta(minutes=schedule.interval_minutes)


async def _close_abandoned_attempts(
    session: AsyncSession, tenant: uuid.UUID, run_id: uuid.UUID, *, cancelled: bool
) -> None:
    """Caller holds the expired job exclusively and the run lock until commit."""
    for model in (NodeExecution, SubQuestionAttempt):
        rows = list(
            await session.scalars(
                select(model)
                .where(model.tenant_id == tenant, model.run_id == run_id, model.status == "running")
                .order_by(model.id)
                .with_for_update()
            )
        )
        for record in rows:
            row = cast(NodeExecution | SubQuestionAttempt, record)
            row.status = "cancelled" if cancelled else "failed"
            row.completed_at = datetime.now(UTC)
            if isinstance(row, SubQuestionAttempt):
                row.error_code = "worker_lease_expired"
            await EventOutbox(session, tenant).append(
                run_id=run_id,
                event_type="task.state",
                payload={
                    "taskId": str(row.id),
                    "nodeId": row.node_id if isinstance(row, NodeExecution) else "research_task",
                    "status": row.status,
                    "attempt": row.attempt,
                    "label": "Worker lease expired; attempt closed",
                },
            )


async def claim(tenant: uuid.UUID, owner: uuid.UUID, settings: Settings) -> JobFence | None:
    started = monotonic()
    async with tenant_session(str(tenant)) as session:
        # Discovery/enqueue already created the registry. Do not wait behind a
        # busy workspace and stall claims for every other tenant. Keep the same
        # exclusive registry lock through commit once acquired; enqueue's quota
        # lock and scheduling/claim atomicity are otherwise unchanged.
        registry = await session.scalar(
            select(DispatchRegistry)
            .where(DispatchRegistry.tenant_id == tenant)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if registry is None:
            return None
        await schedule_due(session, tenant, settings)
        job = await session.scalar(
            select(RuntimeJob)
            .where(
                RuntimeJob.tenant_id == tenant,
                (RuntimeJob.state == "queued")
                | ((RuntimeJob.state == "running") & (RuntimeJob.lease_expires_at <= func.now())),
            )
            .order_by(RuntimeJob.updated_at, RuntimeJob.run_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            await refresh_due(session, registry)
            return None
        run = await session.scalar(
            select(ResearchRun)
            .where(
                ResearchRun.tenant_id == tenant,
                ResearchRun.id == job.run_id,
                ResearchRun.user_id == job.user_id,
            )
            .with_for_update(key_share=True)
        )
        if run is not None and job.state == "running":
            await _close_abandoned_attempts(
                session,
                tenant,
                run.id,
                cancelled=run.cancellation_requested_at is not None or run.status == "cancelled",
            )
        if run is None or run.status in {"completed", "failed", "cancelled"}:
            job.state = run.status if run else "failed"
            job.owner_id, job.lease_expires_at = None, None
            if run is not None:
                await settle_terminal_run(session, run)
            await session.flush()
            await refresh_due(session, registry)
            return None
        if run.cancellation_requested_at is not None:
            job.state, run.status = "cancelled", "cancelled"
            job.owner_id, job.lease_expires_at = None, None
            run.cancelled_at = run.cancellation_requested_at
            await settle_terminal_run(session, run)
            await EventOutbox(session, tenant).append(
                run_id=run.id,
                event_type="run.cancelled",
                payload={"label": "Research run cancelled before recovery"},
            )
            await session.flush()
            await refresh_due(session, registry)
            return None
        # Empty-brief v3 jobs retain their exact model request/parser contracts.
        # Consult the locked, immutable run brief, never checkpoint/model output;
        # do not upgrade the stored version or redispatch incompatible receipts.
        graph_compatible = (
            job.graph_version
            in {
                PREVIOUS_MODE_GRAPH_VERSION,
                PREVIOUS_MODE_SERPER_GRAPH_VERSION,
                PROVENANCE_MODE_GRAPH_VERSION,
                PROVENANCE_MODE_SERPER_GRAPH_VERSION,
                NARRATIVE_MODE_GRAPH_VERSION,
                NARRATIVE_MODE_SERPER_GRAPH_VERSION,
                MODE_GRAPH_VERSION,
                MODE_SERPER_GRAPH_VERSION,
                MODE_OPENALEX_GRAPH_VERSION,
                MODE_OPENALEX_SERPER_GRAPH_VERSION,
                EXPANDED_MODE_GRAPH_VERSION,
                EXPANDED_MODE_SERPER_GRAPH_VERSION,
                EXPANDED_MODE_OPENALEX_GRAPH_VERSION,
                EXPANDED_MODE_OPENALEX_SERPER_GRAPH_VERSION,
                SAFE_MODE_GRAPH_VERSION,
                SAFE_MODE_SERPER_GRAPH_VERSION,
                SAFE_MODE_OPENALEX_GRAPH_VERSION,
                SAFE_MODE_OPENALEX_SERPER_GRAPH_VERSION,
                REPAIR_MODE_GRAPH_VERSION,
                REPAIR_MODE_SERPER_GRAPH_VERSION,
                REPAIR_MODE_OPENALEX_GRAPH_VERSION,
                REPAIR_MODE_OPENALEX_SERPER_GRAPH_VERSION,
            }
            if run.mode is not None
            else job.graph_version
            in {
                GRAPH_VERSION,
                SERPER_GRAPH_VERSION,
                OPENALEX_GRAPH_VERSION,
                OPENALEX_SERPER_GRAPH_VERSION,
            }
            or (job.graph_version == "research-v3" and run.report_requirements == [])
        )
        if not graph_compatible or job.attempts >= 5:
            job.state, run.status = "failed", "failed"
            job.owner_id, job.lease_expires_at = None, None
            run.error_code = (
                "graph_version_incompatible" if not graph_compatible else "recovery_limit"
            )
            await settle_terminal_run(session, run)
            await EventOutbox(session, tenant).append(
                run_id=run.id,
                event_type="run.failed",
                payload={
                    "errorCode": run.error_code,
                    "message": "Recovery requires operator review",
                    "retryable": False,
                },
            )
            await session.flush()
            await refresh_due(session, registry)
            return None
        if job.state == "running":
            # Conservatively account for an unobserved crash tail, never reset the time budget.
            job.active_ms += settings.WORKER_LEASE_SECONDS * 1000
        job.state, job.owner_id = "running", owner
        job.generation += 1
        job.attempts += 1
        job.updated_at = datetime.now(UTC)
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.WORKER_LEASE_SECONDS)
        await session.flush()
        await refresh_due(session, registry)
        fence = JobFence(tenant, job.run_id, owner, job.generation)
        attempts, active_ms = job.attempts, job.active_ms
    # Log committed ownership, not a transaction that might still roll back.
    operation_event(
        "dispatcher.claim",
        started=started,
        runId=str(fence.run_id),
        generation=fence.generation,
        attempts=attempts,
        activeMs=active_ms,
    )
    return fence


async def heartbeat(fence: JobFence, delta_ms: int, settings: Settings) -> bool:
    async with tenant_session(str(fence.tenant_id)) as session:
        job = await session.scalar(
            select(RuntimeJob)
            .where(
                RuntimeJob.tenant_id == fence.tenant_id,
                RuntimeJob.run_id == fence.run_id,
                RuntimeJob.owner_id == fence.owner_id,
                RuntimeJob.generation == fence.generation,
                RuntimeJob.state == "running",
                RuntimeJob.lease_expires_at > func.now(),
            )
            .with_for_update()
        )
        if job is None:
            return False
        job.active_ms += max(0, delta_ms)
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.WORKER_LEASE_SECONDS)
        job.updated_at = datetime.now(UTC)
        return True


async def finish(fence: JobFence, delta_ms: int) -> None:
    started = monotonic()
    async with tenant_session(str(fence.tenant_id)) as session:
        registry = await lock_registry(session, fence.tenant_id)
        job = await session.scalar(
            select(RuntimeJob)
            .where(
                RuntimeJob.tenant_id == fence.tenant_id,
                RuntimeJob.run_id == fence.run_id,
                RuntimeJob.owner_id == fence.owner_id,
                RuntimeJob.generation == fence.generation,
                RuntimeJob.state == "running",
                RuntimeJob.lease_expires_at > func.now(),
            )
            .with_for_update()
        )
        if job is None:
            return
        run = await session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == fence.tenant_id, ResearchRun.id == fence.run_id
            )
        )
        job.active_ms += max(0, delta_ms)
        job.state = (
            "waiting"
            if run and run.status == "awaiting_approval"
            else (
                run.status
                if run and run.status in {"completed", "failed", "cancelled"}
                else "queued"
            )
        )
        job.owner_id, job.lease_expires_at = None, None
        job.updated_at = datetime.now(UTC)
        await session.flush()
        await refresh_due(session, registry)
        state, active_ms = job.state, job.active_ms
    operation_event(
        "dispatcher.finish",
        started=started,
        runId=str(fence.run_id),
        generation=fence.generation,
        state=state,
        activeMs=active_ms,
    )
