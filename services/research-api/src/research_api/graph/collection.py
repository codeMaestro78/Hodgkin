"""Source collection graph node and its bounded provider fan-out."""

import asyncio
import uuid
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from sqlalchemy import func, select

from research_api.artifacts.store import S3ArtifactStore
from research_api.config import Settings
from research_api.db.models import (
    Budget,
    ResearchPlan,
    ResearchRun,
    Source,
    SubQuestion,
    SubQuestionAttempt,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.graph.builder import (
    PROTECTED_EXPLICIT_GRAPH_VERSIONS,
    REPAIR_GRAPH_VERSIONS,
    _cancel_if_requested,
    _explicit_assessment_tail_seconds,
    _repair_tail_ms,
    _transition,
    assessment_deadline,
    logger,
)
from research_api.graph.state import RunState
from research_api.ingestion import TavilyEvidenceIngestor
from research_api.lifecycle import lock_run
from research_api.mode_planning import CoveragePlan
from research_api.providers.http_clients import get_provider_http_client
from research_api.providers.serper import SerperAdapter
from research_api.providers.tavily import TavilyAdapter
from research_api.research_limits import run_source_limit, source_allocations
from research_api.telemetry import operation_event


def ensure_collection_questions_resolved(
    expected_ids: list[uuid.UUID],
    rows: list[tuple[uuid.UUID, str]],
    *,
    allow_pending: bool = False,
) -> None:
    """Fail closed on missing or active work; bounded runs may leave work queued."""
    expected = set(expected_ids)
    observed = {question_id for question_id, _ in rows}
    terminal_statuses = {"complete", "failed", "skipped"}
    if allow_pending:
        terminal_statuses.add("pending")
    unresolved = sum(status not in terminal_statuses for _, status in rows)
    missing = len(expected - observed)
    if not expected or missing or unresolved or observed - expected:
        raise RuntimeError(
            "collection left planned questions unresolved "
            f"(planned={len(expected)}, missing={missing}, unresolved={unresolved}, "
            f"unexpected={len(observed - expected)})"
        )


def collection_attempt_cancel_reason(*, user_cancelled: bool, reserve_timeout: bool) -> str:
    """Distinguish user cancellation, intentional budget cutoff, and interruption."""
    if user_cancelled:
        return "run_cancelled"
    if reserve_timeout:
        return "assessment_time_reserved"
    return "worker_interrupted"


async def _reconcile_interrupted_collection_attempt(
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    question_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    reserve_timeout: bool = False,
) -> None:
    """Clear a running attempt if cancellation rolled back its final status write."""
    started = monotonic()
    async with tenant_session(str(tenant_id)) as session:
        run = await lock_run(session, tenant_id, run_id)
        question = await session.scalar(
            select(SubQuestion)
            .where(SubQuestion.tenant_id == tenant_id, SubQuestion.id == question_id)
            .with_for_update()
        )
        attempt = await session.scalar(
            select(SubQuestionAttempt)
            .where(
                SubQuestionAttempt.tenant_id == tenant_id,
                SubQuestionAttempt.run_id == run_id,
                SubQuestionAttempt.id == attempt_id,
            )
            .with_for_update()
        )
        cancelled_by_user = run.cancellation_requested_at is not None
        changed = False
        if question is not None and question.status == "running":
            question.status = "skipped" if cancelled_by_user else "pending"
            changed = True
        if attempt is not None and attempt.status == "running":
            attempt.status = "cancelled"
            attempt.error_code = collection_attempt_cancel_reason(
                user_cancelled=cancelled_by_user,
                reserve_timeout=reserve_timeout,
            )
            attempt.completed_at = datetime.now(UTC)
            changed = True
            await EventOutbox(session, tenant_id).append(
                run_id=run_id,
                event_type="task.state",
                payload={
                    "taskId": str(attempt_id),
                    "nodeId": "research_task",
                    "status": "cancelled",
                    "attempt": attempt.attempt,
                    "label": (
                        "Collection stopped to preserve time for evidence review"
                        if reserve_timeout and not cancelled_by_user
                        else "Research task interrupted; collected sources were preserved"
                    ),
                },
            )
        operation_event(
            "research.collect.reconcile",
            started=started,
            outcome="succeeded" if changed else "unchanged",
            userCancelled=cancelled_by_user,
        )


def build_collection_node(settings: Settings, checkpointer: Any = None) -> Any:
    """Build the collection worker without changing its provider/database seams."""

    async def research_worker(state: RunState) -> dict[str, list[str]]:
        collection_node_started = monotonic()
        tenant_id = uuid.UUID(state["tenant_id"])
        run_id = uuid.UUID(state["run_id"])
        if await _cancel_if_requested(tenant_id=tenant_id, run_id=run_id):
            return {"source_ids": []}
        if settings.TAVILY_API_KEY is None:
            raise RuntimeError("TAVILY_API_KEY is required to collect research sources")
        store = S3ArtifactStore(
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            bucket=settings.OBJECT_STORAGE_BUCKET,
            access_key=settings.OBJECT_STORAGE_ACCESS_KEY.get_secret_value(),
            secret_key=settings.OBJECT_STORAGE_SECRET_KEY.get_secret_value(),
            region=settings.OBJECT_STORAGE_REGION,
        )
        adapter = TavilyAdapter(
            api_key=settings.TAVILY_API_KEY.get_secret_value(),
            client=get_provider_http_client("tavily"),
            max_attempts=settings.PROVIDER_MAX_ATTEMPTS,
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
        )
        # The initial graph input is durably checkpointed before intake. Legacy
        # checkpoints without a route remain Tavily even if the flag changes.
        discovery_adapter = None
        if state.get("discovery_provider", "tavily") == "serper":
            if settings.SERPER_API_KEY is None:
                await adapter.aclose()
                raise RuntimeError("SERPER_API_KEY is required for this pinned discovery route")
            discovery_adapter = SerperAdapter(
                api_key=settings.SERPER_API_KEY.get_secret_value(),
                client=get_provider_http_client("serper"),
                max_attempts=settings.PROVIDER_MAX_ATTEMPTS,
                timeout=settings.PROVIDER_TIMEOUT_SECONDS,
                retry_after_max_s=settings.DISCOVERY_RETRY_AFTER_MAX_SECONDS,
            )
        academic_adapter = None
        if state.get("openalex_discovery_enabled", False):
            from research_api.providers.openalex import OpenAlexAdapter

            academic_adapter = OpenAlexAdapter(
                api_key=(
                    settings.OPENALEX_API_KEY.get_secret_value()
                    if settings.OPENALEX_API_KEY
                    else None
                ),
                client=get_provider_http_client("openalex"),
                max_attempts=settings.PROVIDER_MAX_ATTEMPTS,
                timeout=settings.PROVIDER_TIMEOUT_SECONDS,
            )
        ingestor = TavilyEvidenceIngestor(
            adapter=adapter,
            artifact_store=store,
            discovery_adapter=discovery_adapter,
            academic_adapter=academic_adapter,
        )
        source_ids: list[str] = []
        async with tenant_session(str(tenant_id)) as session:
            budget = await session.scalar(
                select(Budget).where(Budget.tenant_id == tenant_id, Budget.run_id == run_id)
            )
            existing = await session.scalar(
                select(func.count())
                .select_from(Source)
                .where(Source.tenant_id == tenant_id, Source.run_id == run_id)
            )
            if budget is None:
                raise LookupError("run budget not found")
            allocations = source_allocations(
                run_source_limit(budget, state["quick_mode"]),
                len(state["sub_question_ids"]),
                existing or 0,
            )
            # These setup reads share one short transaction; a separate tenant
            # scope here adds BEGIN/GUC/COMMIT round trips to a remote database.
            run = await session.scalar(
                select(ResearchRun).where(
                    ResearchRun.tenant_id == tenant_id, ResearchRun.id == run_id
                )
            )
            if run is not None and run.mode is not None:
                active_plan = await session.get(ResearchPlan, run.active_plan_id)
                if active_plan is None or run.mode_policy_version is None:
                    raise ValueError("explicit collection requires a versioned coverage plan")
                coverage_plan = CoveragePlan.model_validate(active_plan.plan["coverage"])
                coverage_plan.validate_budget(
                    budget, mode=run.mode, policy_version=run.mode_policy_version
                )
                planned = coverage_plan.sources_per_question
                if "repair" in active_plan.plan:
                    # Admission reserved exactly one source per repair task.
                    allocations = [min(actual, 1) for actual in allocations]
                elif len(planned) == len(allocations):
                    allocations = [
                        min(actual, allowed)
                        for actual, allowed in zip(allocations, planned, strict=True)
                    ]
        semaphore = asyncio.Semaphore(min(3, max(1, run.concurrency_limit if run else 3)))

        async def collect(sub_question_id: str, slots: int) -> None:
            task_started = monotonic()
            async with semaphore:
                collection_started = monotonic()
                if await _cancel_if_requested(tenant_id=tenant_id, run_id=run_id):
                    return
                async with tenant_session(str(tenant_id)) as session:
                    sub_question = await session.scalar(
                        select(SubQuestion).where(
                            SubQuestion.tenant_id == tenant_id,
                            SubQuestion.id == uuid.UUID(sub_question_id),
                        )
                    )
                    if sub_question is None:
                        raise LookupError("sub-question not found")
                    if (checkpointer or state.get("mode")) and sub_question.status in {
                        "complete",
                        "failed",
                        "skipped",
                    }:
                        saved = list(
                            await session.scalars(
                                select(Source.id).where(
                                    Source.tenant_id == tenant_id,
                                    Source.run_id == run_id,
                                    Source.sub_question_id == sub_question.id,
                                )
                            )
                        )
                        source_ids.extend(str(item) for item in saved)
                        return
                    # Persist the original request size before network dispatch. Recomputing
                    # from remaining quota after a crash changes the paid-call fingerprint.
                    previous_slots = (
                        sub_question.payload.get("dispatchSlots")
                        if checkpointer or state.get("mode")
                        else None
                    )
                    if (checkpointer or state.get("mode")) and isinstance(previous_slots, int):
                        slots = previous_slots
                    if slots == 0:
                        if state.get("mode"):
                            sub_question.status = "skipped"
                            sub_question.payload = sub_question.payload | {
                                "dispatchSlots": 0,
                                "skipReason": "source_capacity_exhausted",
                            }
                            await EventOutbox(session, tenant_id).append(
                                run_id=run_id,
                                event_type="node.progress",
                                payload={
                                    "nodeId": "research_task",
                                    "message": (
                                        "A planned question was skipped because source capacity "
                                        "was exhausted."
                                    ),
                                    "percent": None,
                                },
                            )
                        return
                    if checkpointer or state.get("mode"):
                        sub_question.payload = {**sub_question.payload, "dispatchSlots": slots}
                    query = sub_question.question
                    question_payload = getattr(sub_question, "payload", {})
                    question_payload = (
                        question_payload if isinstance(question_payload, dict) else {}
                    )
                    source_classes = question_payload.get("source_classes", [])
                    allowed_domains = question_payload.get("allowed_domains", [])
                    if not isinstance(allowed_domains, list) or any(
                        not isinstance(domain, str) for domain in allowed_domains
                    ):
                        allowed_domains = []
                    if state.get("mode"):
                        saved_query = sub_question.payload.get("dispatchQuery")
                        if isinstance(saved_query, str):
                            query = saved_query
                        else:
                            strategies = {
                                "primary": "original publications and primary documentation",
                                "secondary": "independent secondary analysis and commentary",
                                "academic": "academic publications with original results",
                                "official": "official institutional publications",
                            }
                            hints = [
                                strategies[key]
                                for key in sorted(
                                    set(sub_question.payload.get("source_classes", []))
                                )
                                if key in strategies
                            ]
                            if hints:
                                query += " Source strategy: " + "; ".join(hints) + "."
                            sub_question.payload = sub_question.payload | {"dispatchQuery": query}
                    sub_question.status = "running"
                    sub_question.attempts += 1
                    attempt = SubQuestionAttempt(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        run_id=run_id,
                        sub_question_id=sub_question.id,
                        attempt=sub_question.attempts,
                        status="running",
                        started_at=datetime.now(UTC),
                    )
                    session.add(attempt)
                    await session.flush()
                    attempt_id = attempt.id
                    await EventOutbox(session, tenant_id).append(
                        run_id=run_id,
                        event_type="task.state",
                        payload={
                            "taskId": str(attempt.id),
                            "nodeId": "research_task",
                            "status": "running",
                            "attempt": attempt.attempt,
                            "label": "Research task started",
                        },
                    )
                task_status = "completed"
                stopped_at_assessment_reserve = False
                try:
                    ids = await ingestor.ingest(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        sub_question_id=uuid.UUID(sub_question_id),
                        query=query,
                        source_classes=source_classes,
                        allowed_domains=allowed_domains,
                        max_results=slots,
                        quick_mode=state["quick_mode"],
                    )
                except asyncio.CancelledError:
                    ids = []
                    task_status = "cancelled"
                    stopped_at_assessment_reserve = bool(
                        collection_timeout is not None and collection_timeout.expired()
                    )
                except Exception as exc:
                    ids = []
                    task_status = "failed"
                    operation_event(
                        "research.collect.provider",
                        started=collection_started,
                        outcome="failed",
                        error=exc,
                    )
                source_ids.extend(str(item) for item in ids)
                try:
                    async with tenant_session(str(tenant_id)) as session:
                        run = await lock_run(session, tenant_id, run_id)
                        sub_question = await session.scalar(
                            select(SubQuestion).where(
                                SubQuestion.tenant_id == tenant_id,
                                SubQuestion.id == uuid.UUID(sub_question_id),
                            )
                        )
                        if sub_question is not None:
                            # Shutdown interrupts an attempt, not its research question.
                            # Read durable user intent under the same lock as this write.
                            sub_question.status = (
                                (
                                    "skipped"
                                    if run.cancellation_requested_at is not None
                                    else "pending"
                                )
                                if task_status == "cancelled"
                                else ("complete" if ids else "failed")
                            )
                        attempt_row = await session.scalar(
                            select(SubQuestionAttempt).where(
                                SubQuestionAttempt.tenant_id == tenant_id,
                                SubQuestionAttempt.run_id == run_id,
                                SubQuestionAttempt.id == attempt_id,
                            )
                        )
                        if attempt_row is not None:
                            attempt_row.status = (
                                task_status if ids or task_status == "cancelled" else "failed"
                            )
                            attempt_row.error_code = (
                                None if ids else "source_collection_empty_or_failed"
                            )
                            if task_status == "cancelled":
                                attempt_row.error_code = collection_attempt_cancel_reason(
                                    user_cancelled=run.cancellation_requested_at is not None,
                                    reserve_timeout=stopped_at_assessment_reserve,
                                )
                            attempt_row.completed_at = datetime.now(UTC)
                            await EventOutbox(session, tenant_id).append(
                                run_id=run_id,
                                event_type="task.state",
                                payload={
                                    "taskId": str(attempt_id),
                                    "nodeId": "research_task",
                                    "status": attempt_row.status,
                                    "attempt": attempt_row.attempt,
                                    "label": (
                                        "Collection stopped to preserve time for evidence review"
                                        if stopped_at_assessment_reserve
                                        and run.cancellation_requested_at is None
                                        else "Research task finished"
                                    ),
                                },
                            )
                except asyncio.CancelledError:
                    cleanup = asyncio.create_task(
                        _reconcile_interrupted_collection_attempt(
                            tenant_id,
                            run_id,
                            uuid.UUID(sub_question_id),
                            attempt_id,
                            reserve_timeout=bool(
                                collection_timeout is not None and collection_timeout.expired()
                            ),
                        )
                    )
                    while not cleanup.done():
                        try:
                            await asyncio.shield(cleanup)
                        except asyncio.CancelledError:
                            continue
                    cleanup.result()
                    raise
                if task_status == "cancelled":
                    operation_event(
                        "research.collect",
                        started=task_started,
                        outcome="cancelled",
                        semaphoreWaitMs=round((collection_started - task_started) * 1000, 2),
                        sourceCount=len(ids),
                        operationSlots=slots,
                    )
                    raise asyncio.CancelledError
                operation_event(
                    "research.collect",
                    started=task_started,
                    outcome=(
                        "failed" if task_status == "failed" else "succeeded" if ids else "empty"
                    ),
                    semaphoreWaitMs=round((collection_started - task_started) * 1000, 2),
                    sourceCount=len(ids),
                    operationSlots=slots,
                )

        # Explicit-mode collection must leave its writer, claim review,
        # criterion review and publication tail. Timed-out workers persist
        # already-collected sources and return remaining tasks to pending.
        window: float | None = None
        deadline = assessment_deadline.get()
        if deadline is not None and state.get("graph_version") in PROTECTED_EXPLICIT_GRAPH_VERSIONS:
            tail_seconds = _explicit_assessment_tail_seconds(settings, state.get("mode"))
            window = max(0.0, deadline - monotonic() - tail_seconds)
        elif deadline is not None and state.get("graph_version") in REPAIR_GRAPH_VERSIONS:
            window = max(0.0, deadline - monotonic() - _repair_tail_ms(settings) / 1000)
        try:
            if window is None or window > 0:
                async with asyncio.timeout(window) as collection_timeout:
                    async with asyncio.TaskGroup() as tasks:
                        for sub_question_id, slots in zip(
                            state["sub_question_ids"], allocations, strict=True
                        ):
                            tasks.create_task(collect(sub_question_id, slots))
        except TimeoutError:
            if state.get("mode") is None:
                raise
            logger.warning("explicit collection reached its assessment time reserve")
        finally:
            await adapter.aclose()
            if discovery_adapter:
                await discovery_adapter.aclose()
            if academic_adapter:
                await academic_adapter.aclose()
        if await _cancel_if_requested(tenant_id=tenant_id, run_id=run_id):
            return {"source_ids": source_ids}
        expected_question_ids = [uuid.UUID(item) for item in state["sub_question_ids"]]
        async with tenant_session(str(tenant_id)) as session:
            result = await session.execute(
                select(SubQuestion.id, SubQuestion.status).where(
                    SubQuestion.tenant_id == tenant_id,
                    SubQuestion.run_id == run_id,
                    SubQuestion.id.in_(expected_question_ids),
                )
            )
            question_rows = [(row[0], row[1]) for row in result.all()]
        ensure_collection_questions_resolved(
            expected_question_ids, question_rows, allow_pending=window is not None
        )
        operation_event(
            "research.collect.tasks",
            started=collection_node_started,
            plannedQuestionCount=len(expected_question_ids),
            resolvedQuestionCount=len(question_rows),
            attemptedQuestionCount=sum(
                status in {"complete", "failed"} for _, status in question_rows
            ),
            skippedQuestionCount=sum(status == "skipped" for _, status in question_rows),
            pendingQuestionCount=sum(status == "pending" for _, status in question_rows),
        )
        await _transition(
            tenant_id=tenant_id,
            run_id=run_id,
            status="verifying",
            event_type="research_worker.completed",
            label="Source collection complete; verification is next",
        )
        return {"source_ids": source_ids}

    return research_worker
