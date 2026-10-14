"""Owner-authorized plan decisions and bounded batch/schedule submission."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select

from research_api.api import _budget_from_request
from research_api.auth import authenticated_caller as _caller
from research_api.config import get_settings
from research_api.db.models import (
    PlanApproval,
    ResearchBatch,
    ResearchSchedule,
    RuntimeJob,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.jobs import enqueue, lock_registry, refresh_due
from research_api.lifecycle import lock_run
from research_api.repositories.runs import RunBudgetDefaults, RunRepository
from research_api.schemas.generated.approval_request import ApprovalRequest
from research_api.schemas.generated.batch_request import BatchRequest
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest
from research_api.schemas.generated.schedule_request import ScheduleRequest

router = APIRouter(prefix="/research", tags=["runtime"])


def budget_from(request: BatchRequest | ScheduleRequest) -> RunBudgetDefaults:
    return _budget_from_request(
        CreateResearchRunRequest(
            question="Batch template",
            require_approval=request.require_approval,
            report_requirements=[],
            budget_overrides=(
                request.budget_overrides.model_dump(by_alias=True, exclude_none=True)
                if request.budget_overrides
                else None
            ),
        )
    )


@router.post("/runs/{run_id}/approve")
async def approve(
    run_id: uuid.UUID,
    payload: ApprovalRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    settings = get_settings()
    caller = await _caller(settings, x_internal_service_auth, authorization=authorization)
    async with tenant_session(str(caller.tenant_id)) as session:
        registry = await lock_registry(session, caller.tenant_id)
        job = await session.scalar(
            select(RuntimeJob)
            .where(
                RuntimeJob.tenant_id == caller.tenant_id,
                RuntimeJob.run_id == run_id,
                RuntimeJob.user_id == caller.user_id,
            )
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "research run not found")
        run = await lock_run(session, caller.tenant_id, run_id)
        if run.user_id != caller.user_id or run.active_plan_id != payload.plan_id:
            raise HTTPException(409, "approval does not match the active plan")
        stored = await session.scalar(
            select(PlanApproval).where(
                PlanApproval.tenant_id == caller.tenant_id,
                PlanApproval.run_id == run_id,
                PlanApproval.plan_id == payload.plan_id,
            )
        )
        if stored:
            if stored.decision != payload.decision:
                raise HTTPException(409, "the plan already has a different decision")
            return {"runId": str(run_id), "status": run.status}
        if (
            run.status != "awaiting_approval"
            or job.state != "waiting"
            or run.cancellation_requested_at is not None
        ):
            raise HTTPException(409, "plan is not waiting for approval")
        session.add(
            PlanApproval(
                tenant_id=caller.tenant_id,
                run_id=run_id,
                plan_id=payload.plan_id,
                user_id=caller.user_id,
                decision=payload.decision,
            )
        )
        if payload.decision == "reject":
            run.cancellation_requested_at = run.cancelled_at = datetime.now(UTC)
            run.status, job.state = "cancelled", "cancelled"
        else:
            run.status, job.state = "planning", "queued"
        await EventOutbox(session, caller.tenant_id).append(
            run_id=run_id,
            event_type="approval.decided",
            payload={
                "planId": str(payload.plan_id),
                "decision": payload.decision,
                "label": "Plan decision recorded",
            },
        )
        if payload.decision == "reject":
            await EventOutbox(session, caller.tenant_id).append(
                run_id=run_id,
                event_type="run.cancelled",
                payload={"label": "Research plan rejected"},
            )
        await session.flush()
        await refresh_due(session, registry)
        return {"runId": str(run_id), "status": run.status}


@router.post("/batches", status_code=202)
async def create_batch(
    payload: BatchRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    settings = get_settings()
    caller = await _caller(settings, x_internal_service_auth, authorization=authorization)
    fingerprint = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    budget = budget_from(payload)
    if budget.max_search_calls < 2:
        raise HTTPException(422, "at least two provider-call budget units are required")
    async with tenant_session(str(caller.tenant_id)) as session:
        registry = await lock_registry(session, caller.tenant_id)
        existing = await session.scalar(
            select(ResearchBatch).where(
                ResearchBatch.tenant_id == caller.tenant_id,
                ResearchBatch.user_id == caller.user_id,
                ResearchBatch.idempotency_key == payload.idempotency_key,
            )
        )
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise HTTPException(409, "batch key belongs to another request")
            stored_ids = list(
                await session.scalars(
                    select(RuntimeJob.run_id).where(
                        RuntimeJob.tenant_id == caller.tenant_id, RuntimeJob.batch_id == existing.id
                    )
                )
            )
            return {"batchId": str(existing.id), "runIds": [str(item) for item in stored_ids]}
        batch = ResearchBatch(
            tenant_id=caller.tenant_id,
            user_id=caller.user_id,
            idempotency_key=payload.idempotency_key,
            request_fingerprint=fingerprint,
        )
        session.add(batch)
        await session.flush()
        ids: list[str] = []
        for index, question in enumerate(payload.questions):
            run, _ = await RunRepository(session, caller.tenant_id).create_once(
                user_id=caller.user_id,
                question=question.root,
                budget=budget,
                idempotency_key=f"batch:{batch.id}:{index}",
                approval_required=payload.require_approval,
            )
            await enqueue(session, run, settings, batch.id)
            await EventOutbox(session, caller.tenant_id).append(
                run_id=run.id, event_type="run.created", payload={"label": "Batch research queued"}
            )
            ids.append(str(run.id))
        registry.next_due_at = datetime.now(UTC)
        return {"batchId": str(batch.id), "runIds": ids}


@router.get("/batches")
async def list_batches(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    settings = get_settings()
    caller = await _caller(settings, x_internal_service_auth, authorization=authorization)
    async with tenant_session(str(caller.tenant_id)) as session:
        rows = list(
            await session.execute(
                select(ResearchBatch.id, RuntimeJob.run_id)
                .join(
                    RuntimeJob,
                    (RuntimeJob.tenant_id == caller.tenant_id)
                    & (RuntimeJob.batch_id == ResearchBatch.id),
                )
                .where(
                    ResearchBatch.tenant_id == caller.tenant_id,
                    ResearchBatch.user_id == caller.user_id,
                )
                .order_by(ResearchBatch.created_at.desc())
                .limit(400)
            )
        )
        groups: dict[str, list[str]] = {}
        for batch_id, run_id in rows:
            groups.setdefault(str(batch_id), []).append(str(run_id))
        return {"batches": [{"batchId": key, "runIds": ids} for key, ids in groups.items()]}


@router.post("/schedules", status_code=201)
async def create_schedule(
    payload: ScheduleRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    settings = get_settings()
    caller = await _caller(settings, x_internal_service_auth, authorization=authorization)
    budget = budget_from(payload)
    if budget.max_search_calls < 2:
        raise HTTPException(422, "at least two provider-call budget units are required")
    encoded = {
        field: str(getattr(budget, field))
        if field == "max_estimated_cost_usd"
        else getattr(budget, field)
        for field in budget.__dataclass_fields__
    }
    async with tenant_session(str(caller.tenant_id)) as session:
        registry = await lock_registry(session, caller.tenant_id)
        existing = await session.scalar(
            select(ResearchSchedule).where(
                ResearchSchedule.tenant_id == caller.tenant_id,
                ResearchSchedule.user_id == caller.user_id,
                ResearchSchedule.idempotency_key == payload.idempotency_key,
            )
        )
        if existing:
            if (
                existing.question != payload.question
                or existing.interval_minutes != payload.interval_minutes
                or existing.approval_required != payload.require_approval
                or existing.budget != encoded
            ):
                raise HTTPException(409, "schedule key belongs to another request")
            return {"id": str(existing.id)}
        count = await session.scalar(
            select(func.count())
            .select_from(ResearchSchedule)
            .where(
                ResearchSchedule.tenant_id == caller.tenant_id, ResearchSchedule.enabled.is_(True)
            )
        )
        if (count or 0) >= 10:
            raise HTTPException(429, "workspace schedule limit reached")
        schedule = ResearchSchedule(
            tenant_id=caller.tenant_id,
            user_id=caller.user_id,
            idempotency_key=payload.idempotency_key,
            question=payload.question,
            budget=encoded,
            interval_minutes=payload.interval_minutes,
            approval_required=payload.require_approval,
            next_run_at=datetime.now(UTC) + timedelta(minutes=payload.interval_minutes),
        )
        session.add(schedule)
        await session.flush()
        await refresh_due(session, registry)
        return {"id": str(schedule.id)}


@router.get("/schedules")
async def list_schedules(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    settings = get_settings()
    caller = await _caller(settings, x_internal_service_auth, authorization=authorization)
    async with tenant_session(str(caller.tenant_id)) as session:
        rows = list(
            await session.scalars(
                select(ResearchSchedule)
                .where(
                    ResearchSchedule.tenant_id == caller.tenant_id,
                    ResearchSchedule.user_id == caller.user_id,
                )
                .order_by(ResearchSchedule.next_run_at)
                .limit(100)
            )
        )
        return {
            "schedules": [
                {
                    "id": str(row.id),
                    "question": row.question,
                    "intervalMinutes": row.interval_minutes,
                    "enabled": row.enabled,
                    "nextRunAt": row.next_run_at.isoformat(),
                }
                for row in rows
            ]
        }


@router.post("/schedules/{schedule_id}/disable")
async def disable_schedule(
    schedule_id: uuid.UUID,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    settings = get_settings()
    caller = await _caller(settings, x_internal_service_auth, authorization=authorization)
    async with tenant_session(str(caller.tenant_id)) as session:
        registry = await lock_registry(session, caller.tenant_id)
        row = await session.scalar(
            select(ResearchSchedule)
            .where(
                ResearchSchedule.tenant_id == caller.tenant_id,
                ResearchSchedule.id == schedule_id,
                ResearchSchedule.user_id == caller.user_id,
            )
            .with_for_update()
        )
        if row is None:
            raise HTTPException(404, "schedule not found")
        row.enabled = False
        await session.flush()
        await refresh_due(session, registry)
        return {"id": str(row.id), "status": "disabled"}
