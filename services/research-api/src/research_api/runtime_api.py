"""Owner-authorized plan decisions and bounded batch/schedule submission."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import ValidationError, field_validator
from sqlalchemy import func, select

from research_api.api import _budget_from_request
from research_api.auth import authenticated_caller as _caller
from research_api.billing.ledger import BillingLedgerError, billing_http_status
from research_api.billing.lifecycle import settle_terminal_run
from research_api.config import get_settings
from research_api.db.models import (
    Budget,
    PlanApproval,
    ResearchBatch,
    ResearchPlan,
    ResearchSchedule,
    RuntimeJob,
    SubQuestion,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.graph.builder import PlannedQuestion, PlannerOutput
from research_api.jobs import enqueue, lock_registry, refresh_due
from research_api.lifecycle import lock_run
from research_api.mode_planning import CoveragePlan, attach_coverage_plan, planning_admission
from research_api.mode_policy import MODE_POLICY_VERSION
from research_api.repositories.runs import RunBudgetDefaults, RunRepository
from research_api.research_limits import is_run_quick, operation_limit, run_source_limit
from research_api.schemas.generated.approval_request import ApprovalRequest
from research_api.schemas.generated.batch_request import BatchRequest
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest
from research_api.schemas.generated.edit_research_plan_request import (
    EditResearchPlanRequest as GeneratedEditResearchPlanRequest,
)
from research_api.schemas.generated.edit_research_plan_response import EditResearchPlanResponse
from research_api.schemas.generated.schedule_request import ScheduleRequest

router = APIRouter(prefix="/research", tags=["runtime"])


class EditResearchPlanRequest(GeneratedEditResearchPlanRequest):
    @field_validator("questions", mode="before")
    @classmethod
    def trim_questions(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value


def budget_from(
    request: BatchRequest | ScheduleRequest, policy_version: str | None = None
) -> RunBudgetDefaults:
    return _budget_from_request(
        CreateResearchRunRequest(
            mode=request.mode.value if request.mode is not None else None,
            question="Batch template",
            require_approval=request.require_approval,
            report_requirements=[],
            budget_overrides=(
                request.budget_overrides.model_dump(
                    by_alias=True, exclude_none=True, exclude_unset=True
                )
                if request.budget_overrides
                else None
            ),
        ),
        policy_version,
    )


def _encoded_budget(budget: RunBudgetDefaults) -> dict[str, object]:
    return {
        field: str(getattr(budget, field))
        if field == "max_estimated_cost_usd"
        else getattr(budget, field)
        for field in budget.__dataclass_fields__
    }


def _batch_request_fingerprint(payload: BatchRequest) -> str:
    # Keep the exact legacy JSON representation when mode is absent, so a
    # deployment adding this optional field does not break idempotent replays.
    serialized = payload.model_dump_json(exclude={"mode"} if payload.mode is None else set())
    return hashlib.sha256(serialized.encode()).hexdigest()


@router.post("/runs/{run_id}/plan", response_model=EditResearchPlanResponse)
async def edit_plan(
    run_id: uuid.UUID,
    payload: EditResearchPlanRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> EditResearchPlanResponse:
    """Append a replacement plan only while its owner is reviewing it."""
    settings = get_settings()
    caller = await _caller(settings, x_internal_service_auth, authorization=authorization)
    questions = [question.root for question in payload.questions]
    if any(not question.strip() for question in questions):
        raise HTTPException(422, "each research question must contain non-space text")

    async with tenant_session(str(caller.tenant_id)) as session:
        # Keep the same registry -> job -> run lock order as approval and cancel.
        await lock_registry(session, caller.tenant_id)
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
        if run.user_id != caller.user_id:
            raise HTTPException(404, "research run not found")
        if (
            run.status != "awaiting_approval"
            or job.state != "waiting"
            or run.cancellation_requested_at is not None
        ):
            raise HTTPException(409, "the research plan is no longer editable")
        if (
            run.active_plan_id != payload.plan_id
            or run.plan_version != payload.expected_plan_version
        ):
            raise HTTPException(409, "the research plan changed; refresh before editing")
        if await session.scalar(
            select(PlanApproval.id).where(
                PlanApproval.tenant_id == caller.tenant_id,
                PlanApproval.run_id == run_id,
                PlanApproval.plan_id == payload.plan_id,
            )
        ):
            raise HTTPException(409, "the research plan already has a decision")

        current = await session.scalar(
            select(ResearchPlan).where(
                ResearchPlan.tenant_id == caller.tenant_id,
                ResearchPlan.run_id == run_id,
                ResearchPlan.id == payload.plan_id,
                ResearchPlan.plan_version == run.plan_version,
            )
        )
        budget = await session.scalar(
            select(Budget).where(Budget.tenant_id == caller.tenant_id, Budget.run_id == run_id)
        )
        if current is None or budget is None:
            raise HTTPException(409, "the active research plan could not be loaded")
        try:
            original = PlannerOutput.model_validate(
                {"sub_questions": current.plan.get("sub_questions")}
                if run.mode is not None
                else current.plan
            )
        except ValidationError as exc:
            raise HTTPException(409, "this research plan format cannot be edited") from exc
        # Approval runs never reserve bounded repair; this matches the planner split.
        admission = planning_admission(budget, mode=run.mode, quick_mode=is_run_quick(run))
        maximum = admission.max_initial_questions
        if len(questions) > maximum:
            raise HTTPException(
                422,
                f"this run's budget supports at most {maximum} research question(s)",
            )

        edited = original.model_copy(
            update={
                "sub_questions": [
                    PlannedQuestion.model_validate(
                        original.sub_questions[
                            min(index, len(original.sub_questions) - 1)
                        ].model_dump()
                        | {
                            "question": question,
                            "rationale": "Researcher-edited scope.",
                            "success_criteria": [
                                "Collect directly relevant, verifiable evidence for this question."
                            ],
                        }
                    )
                    for index, question in enumerate(questions)
                ]
            }
        )
        version = run.plan_version + 1
        plan_payload = current.plan | edited.model_dump(mode="json")
        coverage: CoveragePlan | None = None
        if run.mode is not None:
            if run.mode_policy_version is None:
                raise HTTPException(409, "the explicit research policy snapshot is missing")
            try:
                coverage = attach_coverage_plan(
                    run_id=run.id,
                    question=run.original_question,
                    requirements=run.report_requirements or [],
                    questions=[item.model_dump(mode="json") for item in edited.sub_questions],
                    mode=run.mode,
                    policy_version=run.mode_policy_version,
                    operations=operation_limit(budget),
                    sources=run_source_limit(budget),
                    repair_operations=admission.repair_operations_reserved,
                    repair_sources=admission.repair_sources_reserved,
                )
            except ValueError as exc:
                raise HTTPException(422, "edited coverage plan is invalid: " + str(exc)) from exc
            plan_payload["coverage"] = coverage.model_dump(mode="json")
        replacement = ResearchPlan(
            tenant_id=caller.tenant_id,
            run_id=run_id,
            plan_version=version,
            parent_plan_version=run.plan_version,
            plan=plan_payload,
        )
        session.add(replacement)
        await session.flush()
        replacement_questions: list[SubQuestion] = []
        for index, item in enumerate(edited.sub_questions):
            question = SubQuestion(
                tenant_id=caller.tenant_id,
                run_id=run_id,
                plan_id=replacement.id,
                question=item.question,
                payload=item.model_dump(mode="json")
                | {"planIndex": index}
                | (
                    {"dimensionIds": [str(key) for key in coverage.question_dimensions[index]]}
                    if coverage is not None
                    else {}
                ),
                status="pending",
                attempts=0,
            )
            session.add(question)
            replacement_questions.append(question)
        run.active_plan_id = replacement.id
        run.plan_version = version
        await session.flush()
        await EventOutbox(session, caller.tenant_id).append(
            run_id=run_id,
            event_type="approval.plan_updated",
            payload={
                "planId": str(replacement.id),
                "planVersion": version,
                "questionCount": len(replacement_questions),
                "label": "Research plan updated; review the new version",
            },
        )
        return EditResearchPlanResponse.model_validate(
            {
                "runId": str(run_id),
                "planId": str(replacement.id),
                "planVersion": version,
                "status": "awaiting_approval",
                "questions": [
                    {"id": str(question.id), "question": question.question}
                    for question in replacement_questions
                ],
            }
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
            await settle_terminal_run(session, run)
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
    fingerprint = _batch_request_fingerprint(payload)
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
            replay_budget = budget_from(payload, existing.mode_policy_version)
            if replay_budget.max_search_calls < 2:
                raise HTTPException(422, "at least two provider-call budget units are required")
            if existing.request_fingerprint != fingerprint or existing.mode != (
                payload.mode.value if payload.mode is not None else None
            ):
                raise HTTPException(409, "batch key belongs to another request")
            stored_ids = list(
                await session.scalars(
                    select(RuntimeJob.run_id).where(
                        RuntimeJob.tenant_id == caller.tenant_id, RuntimeJob.batch_id == existing.id
                    )
                )
            )
            return {"batchId": str(existing.id), "runIds": [str(item) for item in stored_ids]}
        budget = budget_from(payload)
        if budget.max_search_calls < 2:
            raise HTTPException(422, "at least two provider-call budget units are required")
        batch = ResearchBatch(
            tenant_id=caller.tenant_id,
            user_id=caller.user_id,
            idempotency_key=payload.idempotency_key,
            request_fingerprint=fingerprint,
            mode=payload.mode.value if payload.mode is not None else None,
            mode_policy_version=MODE_POLICY_VERSION if payload.mode is not None else None,
        )
        session.add(batch)
        await session.flush()
        ids: list[str] = []
        try:
            for index, question in enumerate(payload.questions):
                run, _ = await RunRepository(session, caller.tenant_id).create_once(
                    user_id=caller.user_id,
                    question=question.root,
                    budget=budget,
                    idempotency_key=f"batch:{batch.id}:{index}",
                    approval_required=payload.require_approval,
                    mode=payload.mode.value if payload.mode is not None else None,
                    mode_policy_version=MODE_POLICY_VERSION if payload.mode is not None else None,
                )
                await enqueue(session, run, settings, batch.id)
                await EventOutbox(session, caller.tenant_id).append(
                    run_id=run.id,
                    event_type="run.created",
                    payload={"label": "Batch research queued"},
                )
                ids.append(str(run.id))
        except BillingLedgerError as exc:
            code, message, extra = billing_http_status(exc)
            raise HTTPException(code, {"message": message, **extra}) from exc
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
            replay_budget = budget_from(payload, existing.mode_policy_version)
            encoded_replay_budget = _encoded_budget(replay_budget)
            if (
                existing.question != payload.question
                or existing.interval_minutes != payload.interval_minutes
                or existing.approval_required != payload.require_approval
                or existing.budget != encoded_replay_budget
                or existing.mode != (payload.mode.value if payload.mode is not None else None)
            ):
                raise HTTPException(409, "schedule key belongs to another request")
            return {"id": str(existing.id)}
        budget = budget_from(payload)
        if budget.max_search_calls < 2:
            raise HTTPException(422, "at least two provider-call budget units are required")
        encoded = _encoded_budget(budget)
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
            mode=payload.mode.value if payload.mode is not None else None,
            mode_policy_version=MODE_POLICY_VERSION if payload.mode is not None else None,
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
                    "quotaBlockedAt": (
                        row.last_quota_blocked_at.isoformat() if row.last_quota_blocked_at else None
                    ),
                    "quotaBlockedReason": row.last_quota_blocked_reason,
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
