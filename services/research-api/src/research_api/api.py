from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterable, Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import func, select

from research_api.auth import authenticated_caller as _caller
from research_api.billing.ledger import BillingLedgerError, billing_http_status
from research_api.billing.lifecycle import settle_terminal_run
from research_api.config import get_settings
from research_api.db.assessments import ResearchAssessment
from research_api.db.models import (
    Budget,
    Citation,
    EvidenceClaim,
    PlanApproval,
    Report,
    ResearchGap,
    ResearchPlan,
    ResearchRun,
    RunEvent,
    RuntimeJob,
    Source,
    SubQuestion,
    UsageLedger,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.events.wakeups import event_wakeups
from research_api.execution import prior_dependencies, task_projection
from research_api.jobs import enqueue, lock_registry, refresh_due
from research_api.lifecycle import TERMINAL_RUN_STATUSES
from research_api.mode_planning import planning_admission
from research_api.mode_policy import resolve_mode_budget
from research_api.reliability import claim_status, source_assessments
from research_api.repositories.runs import (
    IdempotencyConflictError,
    RunBudgetDefaults,
    RunRepository,
)
from research_api.research_limits import (
    active_time_limit,
    is_run_quick,
    operation_limit,
    run_source_limit,
)
from research_api.retrieval_accounting import build_retrieval_accounting
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest
from research_api.schemas.generated.followup_request import FollowupRequest
from research_api.schemas.generated.public_claim_check import PublicClaimCheck
from research_api.schemas.generated.run_insights import RunInsights
from research_api.snapshots import load_collections
from research_api.verified_preview import verified_preview

router = APIRouter(prefix="/research", tags=["research"])
AfterSequenceQuery = Annotated[int, Query(ge=0, alias="after")]

_PUBLIC_REPAIR_REASONS = frozenset(
    {
        "claim_capacity_exhausted",
        "failed",
        "insufficient_time",
        "no_delta_claims",
        "no_new_evidence",
        "no_verified_delta_claims",
        "timeout",
    }
)


def _public_repair_outcome(value: object) -> dict[str, object] | None:
    """Expose only the durable user-facing repair result, never internal failure detail."""
    if not isinstance(value, dict) or value.get("status") not in {"repaired", "stopped"}:
        return None
    result: dict[str, object] = {"status": value["status"]}
    reason = value.get("reason")
    if isinstance(reason, str) and reason in _PUBLIC_REPAIR_REASONS:
        result["reason"] = reason
    for source_key, public_key in (
        ("new_source_count", "newSourceCount"),
        ("delta_claim_count", "verifiedFindingCount"),
    ):
        count = value.get(source_key)
        if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 40:
            result[public_key] = count
    return result


def _created_projection(run: ResearchRun, budget: RunBudgetDefaults) -> dict[str, object]:
    result: dict[str, object] = {"runId": str(run.id), "status": "queued"}
    if run.mode is not None:
        result.update(
            {
                "mode": run.mode,
                "modePolicyVersion": run.mode_policy_version,
                "modeResolution": "explicit",
                "budget": {
                    "maxSearchCalls": budget.max_search_calls,
                    "maxProviderOperations": operation_limit(budget),
                    "maxSources": run_source_limit(budget),
                    "maxWallClockMs": budget.max_wall_clock_ms,
                    "maxBrowserSessions": budget.max_browser_sessions,
                    "maxReflectionRounds": budget.max_reflection_rounds,
                    "maxInputTokens": budget.max_input_tokens,
                    "maxOutputTokens": budget.max_output_tokens,
                    "maxEstimatedCostUsd": float(budget.max_estimated_cost_usd),
                },
            }
        )
    return result


def _public_claim_checks(
    rows: Iterable[tuple[EvidenceClaim, Citation | None]],
) -> list[dict[str, object]]:
    """Expose stored checks, not an inferred report-wide verification badge."""
    claims: dict[str, dict[str, object]] = {}
    for claim, citation in rows:
        key = str(claim.id)
        if key not in claims:
            claims[key] = {
                "id": key,
                "claim": claim.claim,
                "caveats": claim.caveats,
                "citations": [],
                "reportId": str(getattr(claim, "report_id", None))
                if getattr(claim, "report_id", None)
                else None,
                "section": claim.provenance.get("reportSection"),
                "publishedInReport": claim.provenance.get("publishedInReport") == "true",
                "method": claim.provenance.get("method", "legacy-stored-quote-checks"),
            }
        if citation is None:
            continue
        verification = citation.verification if isinstance(citation.verification, dict) else {}
        exact = verification.get("exactSpan", {})
        semantic = verification.get("semanticSupport", {})
        citations = claims[key]["citations"]
        assert isinstance(citations, list)
        citations.append(
            {
                "id": str(citation.id),
                "sourceId": str(citation.source_id),
                "quote": citation.quote,
                "exactSpanVerified": isinstance(exact, dict) and exact.get("verified") is True,
                "verdict": str(semantic.get("verdict") or "not_recorded")
                if isinstance(semantic, dict)
                else "not_recorded",
                "context": verification.get("context")
                if isinstance(verification.get("context"), str)
                else None,
            }
        )
    for item in claims.values():
        citations = item["citations"]
        assert isinstance(citations, list)
        item["status"] = claim_status(citations)
        if not item["citations"] and item["method"] != "legacy-stored-quote-checks":
            item["status"] = "insufficient_evidence"
        item["supportingSourceIds"] = sorted(
            {
                citation["sourceId"]
                for citation in citations
                if citation["exactSpanVerified"]
                and citation["verdict"] in {"supports", "partially_supports"}
            }
        )
        item["contradictingSourceIds"] = sorted(
            {
                citation["sourceId"]
                for citation in citations
                if citation["exactSpanVerified"] and citation["verdict"] == "contradicts"
            }
        )
    return [
        PublicClaimCheck.model_validate(item).model_dump(mode="json", by_alias=True)
        for item in claims.values()
    ]


def _budget_from_request(
    request: CreateResearchRunRequest, policy_version: str | None = None
) -> RunBudgetDefaults:
    mode = getattr(request, "mode", None)
    if mode is not None:
        try:
            return resolve_mode_budget(
                mode, request.budget_overrides, policy_version=policy_version
            )
        except ValueError as exc:
            raise HTTPException(422, {"code": "mode_budget_invalid", "message": str(exc)}) from exc
    defaults = RunBudgetDefaults()
    overrides = request.budget_overrides
    if overrides is None:
        return RunBudgetDefaults(max_wall_clock_ms=active_time_limit(defaults.max_search_calls))
    return RunBudgetDefaults(
        max_wall_clock_ms=overrides.max_wall_clock_ms
        or active_time_limit(overrides.max_search_calls or defaults.max_search_calls),
        max_search_calls=overrides.max_search_calls or defaults.max_search_calls,
        max_browser_sessions=overrides.max_browser_sessions
        if overrides.max_browser_sessions is not None
        else defaults.max_browser_sessions,
        max_reflection_rounds=overrides.max_reflection_rounds
        if overrides.max_reflection_rounds is not None
        else defaults.max_reflection_rounds,
        max_input_tokens=overrides.max_input_tokens or defaults.max_input_tokens,
        max_output_tokens=overrides.max_output_tokens or defaults.max_output_tokens,
        max_estimated_cost_usd=Decimal(str(overrides.max_estimated_cost_usd))
        if overrides.max_estimated_cost_usd is not None
        else defaults.max_estimated_cost_usd,
    )


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_research_run(
    payload: CreateResearchRunRequest,
    request: Request,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: str | None = Header(default=None),
    x_development_tenant_id: str | None = Header(default=None),
    x_development_user_id: str | None = Header(default=None),
) -> dict[str, object]:
    settings = get_settings()
    caller = await _caller(
        settings,
        x_internal_service_auth,
        x_development_tenant_id,
        x_development_user_id,
        authorization=authorization,
    )
    idempotency_key = payload.idempotency_key or idempotency_key_header
    selected_budget = (
        _budget_from_request(payload) if getattr(payload, "mode", None) is None else None
    )
    if selected_budget is not None and operation_limit(selected_budget) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="the Tavily research slice requires at least two search-call budget units",
        )
    async with tenant_session(str(caller.tenant_id)) as session:
        repository = RunRepository(session, caller.tenant_id)
        try:
            run, created = await repository.create_once(
                user_id=caller.user_id,
                question=payload.question,
                report_requirements=[item.root for item in payload.report_requirements],
                budget=selected_budget,
                idempotency_key=idempotency_key,
                approval_required=payload.require_approval,
                mode=getattr(payload, "mode", None),
                budget_resolver=(lambda version: _budget_from_request(payload, version))
                if getattr(payload, "mode", None) is not None
                else None,
            )
        except IdempotencyConflictError as exc:
            raise HTTPException(409, "idempotency key belongs to another request") from exc
        except BillingLedgerError as exc:
            code, message, extra = billing_http_status(exc)
            raise HTTPException(code, {"message": message, **extra}) from exc
        response = _created_projection(run, _budget_from_request(payload, run.mode_policy_version))
        if not created:
            return response
        await EventOutbox(session, caller.tenant_id).append(
            run_id=run.id,
            event_type="run.created",
            payload={"status": "queued", "questionLength": len(run.original_question)},
        )
        await enqueue(session, run, settings)
    return response


@router.get("/runs")
async def list_research_runs(
    reports_only: Annotated[bool, Query(alias="reportsOnly")] = False,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: str | None = Header(default=None),
    x_development_tenant_id: str | None = Header(default=None),
    x_development_user_id: str | None = Header(default=None),
) -> dict[str, object]:
    """Return the current operator's recent runs, newest first.

    This is deliberately a compact projection: it gives the workspace a useful
    history rail without exposing source material or another tenant's work.
    """
    settings = get_settings()
    caller = await _caller(
        settings,
        x_internal_service_auth,
        x_development_tenant_id,
        x_development_user_id,
        authorization=authorization,
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        source_count = (
            select(func.count())
            .select_from(Source)
            .where(Source.tenant_id == caller.tenant_id, Source.run_id == ResearchRun.id)
            .correlate(ResearchRun)
            .scalar_subquery()
        )
        rows = list(
            await session.execute(
                select(ResearchRun, source_count)
                .where(
                    ResearchRun.tenant_id == caller.tenant_id,
                    ResearchRun.user_id == caller.user_id,
                    *(
                        [ResearchRun.report_id.is_not(None), ResearchRun.status == "completed"]
                        if reports_only
                        else []
                    ),
                )
                .order_by(ResearchRun.created_at.desc())
                .limit(100 if reports_only else 24)
            )
        )
        return {
            "runs": [
                {
                    "runId": str(run.id),
                    "question": run.original_question,
                    "status": run.status,
                    "sourceCount": count,
                    "reportId": str(run.report_id) if run.report_id else None,
                    # Pre-fast-path runs are still in the ledger. The compact
                    # evidence footprint distinguishes a new fast run from an
                    # older definition query that used the full planner.
                    "quickMode": is_run_quick(run) and count <= 2,
                    "mode": run.mode,
                    "modePolicyVersion": run.mode_policy_version,
                    "modeResolution": "explicit" if run.mode is not None else "legacy-inferred",
                    "createdAt": run.created_at.isoformat(),
                }
                for run, count in rows
            ]
        }


@router.get("/runs/{run_id}")
async def get_research_run(
    run_id: uuid.UUID,
    report_version: Annotated[int | None, Query(alias="reportVersion", ge=1, le=10000)] = None,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: str | None = Header(default=None),
    x_development_tenant_id: str | None = Header(default=None),
    x_development_user_id: str | None = Header(default=None),
) -> dict[str, object]:
    settings = get_settings()
    caller = await _caller(
        settings,
        x_internal_service_auth,
        x_development_tenant_id,
        x_development_user_id,
        authorization=authorization,
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        source_total = (
            select(func.count())
            .select_from(Source)
            .where(Source.tenant_id == caller.tenant_id, Source.run_id == run_id)
            .scalar_subquery()
        )
        header = (
            await session.execute(
                select(ResearchRun, Budget, UsageLedger, source_total, RuntimeJob.active_ms)
                .select_from(ResearchRun)
                .outerjoin(
                    Budget, (Budget.tenant_id == caller.tenant_id) & (Budget.run_id == run_id)
                )
                .outerjoin(
                    UsageLedger,
                    (UsageLedger.tenant_id == caller.tenant_id) & (UsageLedger.run_id == run_id),
                )
                .outerjoin(
                    RuntimeJob,
                    (RuntimeJob.tenant_id == caller.tenant_id) & (RuntimeJob.run_id == run_id),
                )
                .where(
                    ResearchRun.tenant_id == caller.tenant_id,
                    ResearchRun.id == run_id,
                    ResearchRun.user_id == caller.user_id,
                )
            )
        ).first()
        if header is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="research run not found"
            )
        run, budget, usage, source_count, processing_ms = header
        report = await session.scalar(
            select(Report)
            .where(
                Report.tenant_id == caller.tenant_id,
                Report.run_id == run_id,
                *([Report.version == report_version] if report_version is not None else []),
            )
            .order_by(Report.version.desc())
            .limit(1)
        )
        if report_version is not None and report is None:
            raise HTTPException(404, "report version not found")
        repair_outcome = None
        report_assessment_id = (
            report.document.get("assessmentId")
            if report and isinstance(report.document, dict)
            else None
        )
        if isinstance(report_assessment_id, str):
            repair_assessments = list(
                await session.scalars(
                    select(ResearchAssessment)
                    .where(
                        ResearchAssessment.tenant_id == caller.tenant_id,
                        ResearchAssessment.run_id == run_id,
                    )
                    .order_by(ResearchAssessment.created_at.desc())
                    .limit(8)
                )
            )
            for assessment in repair_assessments:
                result = assessment.result
                repair = result.get("repair") if isinstance(result, dict) else None
                if isinstance(repair, dict) and (
                    str(assessment.id) == report_assessment_id
                    or repair.get("base_assessment_id") == report_assessment_id
                ):
                    repair_outcome = _public_repair_outcome(repair)
                    if repair_outcome is not None:
                        break
        # Explicit tenant/run predicates on both sides of the join. Only compact,
        # named evidence fields leave the API; artifact locations stay private.
        evidence_rows = await session.execute(
            select(EvidenceClaim, Citation)
            .outerjoin(
                Citation,
                (
                    (Citation.evidence_claim_id == EvidenceClaim.id)
                    & (Citation.tenant_id == caller.tenant_id)
                    & (Citation.run_id == run_id)
                ),
            )
            .where(
                EvidenceClaim.tenant_id == caller.tenant_id,
                EvidenceClaim.run_id == run_id,
                *(
                    [
                        (EvidenceClaim.report_id == report.id)
                        | (EvidenceClaim.report_id.is_(None) if report.version == 1 else False)
                    ]
                    if report
                    else []
                ),
            )
            .order_by(EvidenceClaim.created_at, EvidenceClaim.id, Citation.id)
            .limit(320)
        )
        claim_checks = _public_claim_checks(evidence_rows)
        collections = await load_collections(session, caller.tenant_id, run_id)
        sources, questions = collections.sources, collections.questions
        nodes, attempts = collections.nodes, collections.attempts
        gaps, versions, calls = collections.gaps, collections.versions, collections.calls
        approval = None
        if run.approval_required and run.active_plan_id:
            active_plan = await session.scalar(
                select(ResearchPlan).where(
                    ResearchPlan.tenant_id == caller.tenant_id,
                    ResearchPlan.run_id == run_id,
                    ResearchPlan.id == run.active_plan_id,
                )
            )
            decision = await session.scalar(
                select(PlanApproval).where(
                    PlanApproval.tenant_id == caller.tenant_id,
                    PlanApproval.run_id == run_id,
                    PlanApproval.plan_id == run.active_plan_id,
                )
            )
            active_questions = list(
                (
                    await session.execute(
                        select(SubQuestion.id, SubQuestion.question)
                        .where(
                            SubQuestion.tenant_id == caller.tenant_id,
                            SubQuestion.run_id == run_id,
                            SubQuestion.plan_id == run.active_plan_id,
                        )
                        .order_by(
                            SubQuestion.payload["planIndex"].as_integer().nulls_last(),
                            SubQuestion.created_at,
                            SubQuestion.id,
                        )
                        .limit(8)
                    )
                ).mappings()
            )
            # Approval runs never reserve bounded repair; this matches the planner split.
            maximum_questions = (
                planning_admission(
                    budget, mode=run.mode, quick_mode=is_run_quick(run)
                ).max_initial_questions
                if budget is not None
                else 1
            )
            # Time spent waiting for a decision is not research time. Each request
            # opens a wait and the next recorded decision (or cancellation) closes it;
            # plan edits replace the plan id without reopening the wait.
            requested = (
                await session.scalars(
                    select(RunEvent.occurred_at).where(
                        RunEvent.tenant_id == caller.tenant_id,
                        RunEvent.run_id == run_id,
                        RunEvent.event_type == "approval.requested",
                    )
                )
            ).all()
            decided = (
                await session.scalars(
                    select(PlanApproval.decided_at).where(
                        PlanApproval.tenant_id == caller.tenant_id,
                        PlanApproval.run_id == run_id,
                    )
                )
            ).all()
            timeline = sorted(
                [(moment, 0) for moment in requested] + [(moment, 1) for moment in decided]
            )
            waited_ms, open_wait = 0, None
            for moment, closes in timeline:
                if not closes and open_wait is None:
                    open_wait = moment
                elif closes and open_wait is not None:
                    waited_ms += max(0, int((moment - open_wait).total_seconds() * 1000))
                    open_wait = None
            if open_wait is not None and run.status == "cancelled" and run.cancelled_at:
                waited_ms += max(0, int((run.cancelled_at - open_wait).total_seconds() * 1000))
                open_wait = None
            approval = {
                "planId": str(run.active_plan_id),
                "waitedMs": waited_ms,
                "waitStartedAt": open_wait.isoformat() if open_wait else None,
                "planVersion": run.plan_version,
                "state": decision.decision if decision else "pending",
                "editable": bool(
                    active_plan and isinstance(active_plan.plan.get("sub_questions"), list)
                ),
                "maxQuestions": maximum_questions,
                "questions": [
                    {"id": str(item["id"]), "question": item["question"]}
                    for item in active_questions
                ],
            }
        if report:
            gaps = [
                gap
                for gap in gaps
                if gap.details.get("reportId") == str(report.id)
                or (report.version == 1 and gap.details.get("reportId") is None)
            ]
        now = datetime.now(UTC)
        elapsed_end = run.updated_at if run.status in TERMINAL_RUN_STATUSES else now
        elapsed_ms = max(0, int((elapsed_end - run.created_at).total_seconds() * 1000))
        approval_wait_ms = int(approval.get("waitedMs", 0)) if approval else 0
        if approval and approval.get("waitStartedAt") and run.status not in TERMINAL_RUN_STATUSES:
            wait_started_at = datetime.fromisoformat(approval["waitStartedAt"])
            approval_wait_ms += max(0, int((now - wait_started_at).total_seconds() * 1000))
        tasks = [
            task_projection(
                node,
                dependencies=prior_dependencies(node, nodes),
            )
            for node in nodes
        ]
        by_question = {item.id: item for item in questions}
        for attempt in attempts:
            question = by_question.get(attempt.sub_question_id)
            if question:
                tasks.append(
                    task_projection(
                        attempt,
                        name=question.question,
                        source_ids=[
                            str(source.id)
                            for source in sources
                            if source.sub_question_id == question.id
                            or any(
                                path.get("subQuestionId") == str(question.id)
                                for path in (source.discovery_paths or [])
                            )
                        ],
                        dependencies=[
                            str(node.id)
                            for node in nodes
                            if node.node_id == "research_worker"
                            and node.started_at <= attempt.started_at
                            and (not node.completed_at or node.completed_at >= attempt.started_at)
                        ][-1:],
                    )
                )
        attempted = {attempt.sub_question_id for attempt in attempts}
        for question in questions:
            if question.id not in attempted:
                tasks.append(
                    {
                        "id": str(question.id),
                        "nodeId": "research_task",
                        "name": question.question,
                        "status": {
                            "complete": "completed",
                            "failed": "failed",
                            "running": "running",
                            "skipped": "skipped",
                        }.get(question.status, "queued"),
                        "attempt": question.attempts,
                        "startedAt": None,
                        "completedAt": None,
                        "errorCode": None,
                        "sourceIds": [],
                        "dependsOn": ["planner"],
                    }
                )
        parent_run_id = None
        if getattr(run, "parent_report_id", None):
            parent_run_id = await session.scalar(
                select(Report.run_id)
                .join(
                    ResearchRun,
                    (ResearchRun.id == Report.run_id)
                    & (ResearchRun.tenant_id == caller.tenant_id)
                    & (ResearchRun.user_id == caller.user_id),
                )
                .where(Report.tenant_id == caller.tenant_id, Report.id == run.parent_report_id)
            )
        followups = (
            list(
                await session.scalars(
                    select(ResearchRun)
                    .where(
                        ResearchRun.tenant_id == caller.tenant_id,
                        ResearchRun.user_id == caller.user_id,
                        ResearchRun.parent_report_id == report.id,
                    )
                    .order_by(ResearchRun.created_at.desc())
                    .limit(20)
                )
            )
            if report
            else []
        )
        insights = RunInsights.model_validate(
            {
                "schemaVersion": "1.3",
                "tasks": tasks,
                "providerCalls": [
                    {
                        "id": str(call.id),
                        "provider": call.provider,
                        "operation": call.operation,
                        "outcome": call.outcome,
                        "startedAt": call.started_at.isoformat(),
                        "completedAt": call.completed_at.isoformat() if call.completed_at else None,
                    }
                    for call in calls
                ],
                "gaps": [
                    {
                        "id": str(gap.id),
                        "description": gap.description,
                        "why": gap.details.get(
                            "why", "A recorded research limitation remains unresolved."
                        ),
                        "suggestedQuery": gap.target_query,
                        "status": gap.status
                        if gap.status in {"open", "investigating", "resolved"}
                        else "open",
                        "claimIds": gap.details.get("claimIds", []),
                        "subQuestionIds": gap.details.get("subQuestionIds", []),
                    }
                    for gap in gaps
                ],
                "parentReportId": str(run.parent_report_id)
                if getattr(run, "parent_report_id", None)
                else None,
                "parentRunId": str(parent_run_id) if parent_run_id else None,
                "followupRuns": [
                    {
                        "runId": str(item.id),
                        "status": item.status,
                        "createdAt": item.created_at.isoformat(),
                    }
                    for item in followups
                ],
                "reportVersions": [
                    {
                        "id": str(item.id),
                        "version": item.version,
                        "createdAt": item.created_at.isoformat(),
                    }
                    for item in versions
                ],
                "retrievalAccounting": build_retrieval_accounting(
                    calls=[
                        {
                            "provider": call.provider,
                            "operation": call.operation,
                            "outcome": call.outcome,
                            "provider_usage": call.provider_usage,
                        }
                        for call in calls
                    ],
                    sources=[
                        {
                            "id": str(source.id),
                            "provider": source.provider,
                            "contentHash": source.content_hash,
                            "sourceClass": source.source_class,
                        }
                        for source in sources
                    ],
                    claim_checks=claim_checks,
                ),
            }
        )
        assessments = source_assessments(sources, run.original_question)
        return {
            "schemaVersion": "1.5",
            "insights": insights.model_dump(mode="json", by_alias=True),
            "runId": str(run.id),
            "status": run.status,
            "originalQuestion": run.original_question,
            "mode": getattr(run, "mode", None),
            "modePolicyVersion": getattr(run, "mode_policy_version", None),
            "modeResolution": "explicit"
            if getattr(run, "mode", None) is not None
            else "legacy-inferred",
            "reportRequirements": run.report_requirements or [],
            "approval": approval,
            "timing": {
                "processingMs": max(0, int(processing_ms)) if processing_ms is not None else None,
                "approvalWaitMs": approval_wait_ms,
                "elapsedMs": elapsed_ms,
            },
            "planVersion": run.plan_version,
            "sourceCount": source_count or 0,
            "claimChecks": claim_checks,
            "sourceLimit": run_source_limit(budget, is_run_quick(run)) if budget else 0,
            "errorCode": run.error_code,
            "createdAt": run.created_at.isoformat(),
            "updatedAt": run.updated_at.isoformat(),
            "budget": {
                "maxSearchCalls": budget.max_search_calls if budget else 0,
                "maxProviderOperations": operation_limit(budget) if budget else 0,
                "maxSources": run_source_limit(budget, is_run_quick(run)) if budget else 0,
                "maxWallClockMs": budget.max_wall_clock_ms if budget else 0,
                "maxEstimatedCostUsd": float(budget.max_estimated_cost_usd) if budget else 0,
            },
            "usage": {
                "searchCalls": usage.search_calls if usage else 0,
                "providerOperations": usage.search_calls if usage else 0,
                "reservedProviderOperations": getattr(usage, "reserved_search_calls", 0),
                "sources": source_count or 0,
            },
            "report": (
                {
                    "id": str(report.id),
                    "version": report.version,
                    "markdown": report.markdown,
                    "document": report.document,
                    "retrievalAccounting": report.retrieval_accounting,
                    "repairOutcome": repair_outcome,
                    "answerQuality": (
                        report.document["quality"]["status"] if report.document else "not_assessed"
                    ),
                    "publishedAt": (report.published_at or report.created_at).isoformat(),
                }
                if report
                else None
            ),
            "quickMode": is_run_quick(run) and (source_count or 0) <= 2,
            "sources": [
                {
                    "id": str(source.id),
                    "title": source.title,
                    "url": source.canonical_url,
                    "provider": source.provider,
                    "sourceClass": source.source_class,
                    "assessment": assessments[str(source.id)],
                    "discoveryPaths": source.discovery_paths or [],
                }
                for source in sources
            ],
            "subQuestions": [
                {
                    "id": str(item.id),
                    "question": item.question,
                    "status": item.status,
                }
                for item in questions
            ],
            "events": [
                {
                    "sequence": event.event_sequence,
                    "type": event.event_type,
                    "label": event.payload.get("label") or event.payload.get("message"),
                    "occurredAt": event.occurred_at.isoformat(),
                    **(verified_preview(event.event_type, event.payload) or {}),
                }
                for event in collections.events
            ],
        }


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_research_run(
    run_id: uuid.UUID,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: str | None = Header(default=None),
    x_development_tenant_id: str | None = Header(default=None),
    x_development_user_id: str | None = Header(default=None),
) -> dict[str, str]:
    """Request cancellation once; workers honor it at safe graph boundaries."""
    settings = get_settings()
    caller = await _caller(
        settings,
        x_internal_service_auth,
        x_development_tenant_id,
        x_development_user_id,
        authorization=authorization,
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        registry = await lock_registry(session, caller.tenant_id)
        job = await session.scalar(
            select(RuntimeJob)
            .where(
                RuntimeJob.tenant_id == caller.tenant_id,
                RuntimeJob.user_id == caller.user_id,
                RuntimeJob.run_id == run_id,
            )
            .with_for_update()
        )
        run = await session.scalar(
            select(ResearchRun)
            .where(
                ResearchRun.tenant_id == caller.tenant_id,
                ResearchRun.user_id == caller.user_id,
                ResearchRun.id == run_id,
            )
            .with_for_update()
        )
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="research run not found"
            )
        if run.status in {"completed", "failed", "cancelled"}:
            return {"runId": str(run.id), "status": run.status}
        if run.cancellation_requested_at is None:
            run.cancellation_requested_at = datetime.now(UTC)
            await EventOutbox(session, caller.tenant_id).append(
                run_id=run.id,
                event_type="run.cancellation_requested",
                payload={"label": "Cancellation requested"},
            )
        if run.status in {"queued", "awaiting_approval"}:
            run.status = "cancelled"
            run.cancelled_at = datetime.now(UTC)
            await EventOutbox(session, caller.tenant_id).append(
                run_id=run.id,
                event_type="run.cancelled",
                payload={"label": "Research run cancelled"},
            )
            if job is not None:
                job.state = "cancelled"
                job.owner_id, job.lease_expires_at = None, None
            await settle_terminal_run(session, run)
            await session.flush()
            await refresh_due(session, registry)
        return {"runId": str(run.id), "status": run.status}


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_research_run(
    run_id: uuid.UUID,
    request: Request,
    max_wall_clock_ms: Annotated[
        int | None, Query(alias="maxWallClockMs", gt=0, le=1_800_000)
    ] = None,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: str | None = Header(default=None),
    x_development_tenant_id: str | None = Header(default=None),
    x_development_user_id: str | None = Header(default=None),
) -> dict[str, str]:
    """Create a fresh, auditable attempt instead of mutating terminal evidence."""
    settings = get_settings()
    caller = await _caller(
        settings,
        x_internal_service_auth,
        x_development_tenant_id,
        x_development_user_id,
        authorization=authorization,
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        prior = await session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == caller.tenant_id,
                ResearchRun.user_id == caller.user_id,
                ResearchRun.id == run_id,
            )
        )
        if prior is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="research run not found"
            )
        if prior.status not in {"failed", "cancelled"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="only failed or cancelled research can be retried",
            )
        budget = await session.scalar(
            select(Budget).where(Budget.tenant_id == caller.tenant_id, Budget.run_id == run_id)
        )
        if budget is None:
            raise RuntimeError("run budget not found")
        if prior.mode is not None and max_wall_clock_ms not in {None, budget.max_wall_clock_ms}:
            raise HTTPException(
                422,
                {
                    "code": "mode_budget_invalid",
                    "message": "explicit-mode retries inherit the original time limit",
                },
            )
        try:
            fresh = await RunRepository(session, caller.tenant_id).create(
                user_id=caller.user_id,
                question=prior.original_question,
                report_requirements=prior.report_requirements,
                budget=RunBudgetDefaults(
                    max_wall_clock_ms=max_wall_clock_ms or budget.max_wall_clock_ms,
                    max_search_calls=budget.max_search_calls,
                    max_browser_sessions=budget.max_browser_sessions,
                    max_reflection_rounds=budget.max_reflection_rounds,
                    max_input_tokens=budget.max_input_tokens,
                    max_output_tokens=budget.max_output_tokens,
                    max_estimated_cost_usd=budget.max_estimated_cost_usd,
                    max_provider_operations=budget.max_provider_operations,
                    max_sources=budget.max_sources,
                ),
                mode=prior.mode,
                mode_policy_version=prior.mode_policy_version,
                approval_required=prior.approval_required,
            )
        except BillingLedgerError as exc:
            code, message, extra = billing_http_status(exc)
            raise HTTPException(code, {"message": message, **extra}) from exc
        await EventOutbox(session, caller.tenant_id).append(
            run_id=fresh.id,
            event_type="run.retried",
            payload={
                "label": "Retry created from a prior terminal run",
                "priorRunId": str(prior.id),
            },
        )
        fresh_id = fresh.id
        await enqueue(session, fresh, settings)
    return {"runId": str(fresh_id), "status": "queued"}


@router.post("/runs/{run_id}/followups", status_code=status.HTTP_202_ACCEPTED)
async def followup_research_run(
    run_id: uuid.UUID,
    body: FollowupRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: str | None = Header(default=None),
    x_development_tenant_id: str | None = Header(default=None),
    x_development_user_id: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    if len(body.question.strip()) < 5:
        raise HTTPException(422, "follow-up question is too short")
    caller = await _caller(
        settings,
        x_internal_service_auth,
        x_development_tenant_id,
        x_development_user_id,
        authorization=authorization,
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        await lock_registry(session, caller.tenant_id)
        prior = await session.scalar(
            select(ResearchRun)
            .where(
                ResearchRun.tenant_id == caller.tenant_id,
                ResearchRun.user_id == caller.user_id,
                ResearchRun.id == run_id,
            )
            .with_for_update()
        )
        if prior is None:
            raise HTTPException(404, "research run not found")
        if prior.status != "completed" or not prior.report_id:
            raise HTTPException(409, "follow-ups require a completed report")
        parent_report_id: uuid.UUID | None = prior.report_id
        if body.report_version is not None:
            parent_report_id = await session.scalar(
                select(Report.id).where(
                    Report.tenant_id == caller.tenant_id,
                    Report.run_id == run_id,
                    Report.version == body.report_version,
                )
            )
            if parent_report_id is None:
                raise HTTPException(404, "report version not found")
        gap = None
        if body.gap_id:
            gap = await session.scalar(
                select(ResearchGap)
                .where(
                    ResearchGap.tenant_id == caller.tenant_id,
                    ResearchGap.run_id == run_id,
                    ResearchGap.id == body.gap_id,
                )
                .with_for_update()
            )
            if gap is None:
                raise HTTPException(404, "research gap not found")
            if gap.details.get("reportId") not in {None, str(parent_report_id)}:
                raise HTTPException(409, "gap belongs to another report version")
        repository = RunRepository(session, caller.tenant_id)
        requested_mode = getattr(body, "mode", None)
        inherited_mode = requested_mode if requested_mode is not None else prior.mode
        changed_mode = requested_mode is not None and requested_mode != prior.mode
        fresh = await repository.get_by_idempotency_key(
            user_id=caller.user_id, idempotency_key=body.idempotency_key
        )
        if fresh:
            expected_question = (
                f"Follow-up to: {prior.original_question}\nInvestigate: {body.question.strip()}"
            )
            if (
                fresh.parent_report_id != parent_report_id
                or fresh.original_question != expected_question
                or fresh.mode != inherited_mode
                or (not changed_mode and fresh.mode_policy_version != prior.mode_policy_version)
            ):
                raise HTTPException(409, "idempotency key belongs to another request")
            linked_gap = await session.scalar(
                select(ResearchGap.id)
                .where(
                    ResearchGap.tenant_id == caller.tenant_id,
                    ResearchGap.run_id == run_id,
                    ResearchGap.details["followupRunId"].as_string() == str(fresh.id),
                )
                .limit(1)
            )
            if linked_gap != body.gap_id:
                raise HTTPException(409, "idempotency key belongs to another gap investigation")
            return {"runId": str(fresh.id), "status": fresh.status}
        if gap and gap.details.get("followupRunId"):
            raise HTTPException(409, "gap already has a follow-up; open the existing investigation")
        budget = await session.scalar(
            select(Budget).where(Budget.tenant_id == caller.tenant_id, Budget.run_id == run_id)
        )
        if budget is None:
            raise HTTPException(409, "parent budget unavailable")
        question = f"Follow-up to: {prior.original_question}\nInvestigate: {body.question.strip()}"
        try:
            fresh, created = await repository.create_once(
                user_id=caller.user_id,
                question=question,
                idempotency_key=body.idempotency_key,
                report_requirements=prior.report_requirements,
                parent_report_id=parent_report_id,
                approval_required=prior.approval_required,
                mode=inherited_mode,
                mode_policy_version=None if changed_mode else prior.mode_policy_version,
                budget_resolver=(
                    lambda version: resolve_mode_budget(str(inherited_mode), policy_version=version)
                )
                if changed_mode
                else None,
                budget=RunBudgetDefaults(
                    **{
                        field: getattr(budget, field)
                        for field in RunBudgetDefaults.__dataclass_fields__
                    }
                ),
            )
        except IdempotencyConflictError as exc:
            raise HTTPException(409, "idempotency key belongs to another request") from exc
        except BillingLedgerError as exc:
            code, message, extra = billing_http_status(exc)
            raise HTTPException(code, {"message": message, **extra}) from exc
        if not created:
            return {"runId": str(fresh.id), "status": fresh.status}
        if gap:
            gap.status = "investigating"
            gap.details = {**gap.details, "followupRunId": str(fresh.id)}
        await EventOutbox(session, caller.tenant_id).append(
            run_id=fresh.id,
            event_type="followup.created",
            payload={
                "label": "Follow-up created; evidence will be collected afresh",
                "parentReportId": str(parent_report_id),
            },
        )
        fresh_id = fresh.id
        await enqueue(session, fresh, settings)
    return {"runId": str(fresh_id), "status": "queued"}


@router.get("/runs/{run_id}/events", response_class=EventSourceResponse)
async def stream_research_run_events(
    run_id: uuid.UUID,
    request: Request,
    after: AfterSequenceQuery = 0,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: str | None = Header(default=None),
    x_development_tenant_id: str | None = Header(default=None),
    x_development_user_id: str | None = Header(default=None),
) -> AsyncIterable[ServerSentEvent]:
    """Replay committed run events, then tail them with monotonic sequence IDs."""
    settings = get_settings()
    caller = await _caller(
        settings,
        x_internal_service_auth,
        x_development_tenant_id,
        x_development_user_id,
        authorization=authorization,
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        run = await session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == caller.tenant_id,
                ResearchRun.user_id == caller.user_id,
                ResearchRun.id == run_id,
            )
        )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="research run not found")

    cursor = request.headers.get("last-event-id")
    if cursor is not None:
        if not cursor.isascii() or not cursor.isdecimal() or len(cursor) > 16:
            raise HTTPException(422, "invalid event cursor")
        after = max(after, int(cursor))

    async def event_stream(wake: asyncio.Event) -> AsyncIterable[ServerSentEvent]:
        watermark = after
        terminal_statuses = {"completed", "failed", "cancelled"}
        idle_polls = 0
        while not await request.is_disconnected():
            # Register before reading, then clear before each transaction: commits
            # during/after the read stay signalled until the next read.
            wake.clear()
            async with tenant_session(str(caller.tenant_id)) as session:
                rows = list(
                    await session.execute(
                        select(ResearchRun.status, RunEvent)
                        .select_from(ResearchRun)
                        .outerjoin(
                            RunEvent,
                            (RunEvent.tenant_id == caller.tenant_id)
                            & (RunEvent.run_id == run_id)
                            & (RunEvent.event_sequence > watermark),
                        )
                        .where(
                            ResearchRun.tenant_id == caller.tenant_id,
                            ResearchRun.user_id == caller.user_id,
                            ResearchRun.id == run_id,
                        )
                        .order_by(RunEvent.event_sequence)
                        .limit(128)
                    )
                )
                if not rows:
                    return
                current_status = rows[0][0]
                events = [row[1] for row in rows if row[1] is not None]
            for event in events:
                watermark = event.event_sequence
                yield ServerSentEvent(
                    id=str(event.event_sequence),
                    data={
                        "sequence": event.event_sequence,
                        "type": event.event_type,
                        "label": event.payload.get("label") or event.payload.get("message"),
                        "occurredAt": event.occurred_at.isoformat(),
                        **(verified_preview(event.event_type, event.payload) or {}),
                        "errorCode": event.payload.get("errorCode")
                        if event.event_type == "run.failed"
                        else None,
                    },
                )
            if len(events) == 128:
                # Drain replay pages without waiting, even after a terminal event.
                continue
            if current_status in terminal_statuses:
                return
            if not events:
                yield ServerSentEvent(comment="keepalive")
            idle_polls = 0 if events else min(idle_polls + 1, 5)
            # Quiet tabs should not compete continuously with graph persistence.
            try:
                await asyncio.wait_for(
                    wake.wait(),
                    timeout=5 if current_status == "awaiting_approval" else max(1, idle_polls),
                )
            except TimeoutError:
                pass  # Lost hints and Redis outages still resynchronize from PostgreSQL.

    with event_wakeups.watch(caller.tenant_id, run_id) as wake:
        async for event in event_stream(wake):
            yield event
