"""Real local queue/checkpoint transactions; all paid boundaries are replaced."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import api, dispatcher, jobs, runtime_api
from research_api.checkpointing import CheckpointPool
from research_api.config import Settings
from research_api.db.models import (
    Budget,
    NodeExecution,
    Report,
    ResearchBatch,
    ResearchPlan,
    ResearchRun,
    ResearchSchedule,
    RunEvent,
    RuntimeJob,
    SubQuestion,
    SubQuestionAttempt,
    Tenant,
    User,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.execution import finish_node, start_node
from research_api.graph import builder, collection
from research_api.lifecycle import lock_run
from research_api.repositories.runs import RunRepository
from research_api.runtime_context import LeaseLostError, current_job
from research_api.schemas.generated.approval_request import ApprovalRequest
from research_api.schemas.generated.batch_request import BatchRequest
from research_api.schemas.generated.schedule_request import ScheduleRequest

pytestmark = pytest.mark.integration


async def seed(monkeypatch, *, approval=False, settings=None):
    settings = settings or Settings()
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Durable fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    async with tenant_session(str(tenant)) as session:
        run, _ = await RunRepository(session, tenant).create_once(
            user_id=user,
            question="Compare durable research",
            approval_required=approval,
        )
        await jobs.enqueue(session, run, settings)
    monkeypatch.setattr(runtime_api, "get_settings", lambda: settings)
    monkeypatch.setattr(
        runtime_api,
        "_caller",
        AsyncMock(
            return_value=SimpleNamespace(tenant_id=tenant, user_id=user),
        ),
    )
    return tenant, user, run.id, settings


async def test_claim_is_exclusive_and_expired_owner_cannot_write(monkeypatch):
    tenant, _, run, settings = await seed(monkeypatch)
    claims = await asyncio.gather(*(jobs.claim(tenant, uuid.uuid4(), settings) for _ in range(4)))
    assert sum(item is not None for item in claims) == 1
    first = next(item for item in claims if item)
    async with tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run)
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    second = await jobs.claim(tenant, uuid.uuid4(), settings)
    assert second and second.generation == first.generation + 1
    assert not await jobs.heartbeat(first, 10, settings)
    token = current_job.set(first)
    try:
        with pytest.raises(LeaseLostError):
            async with tenant_session(str(tenant)):
                pass
    finally:
        current_job.reset(token)
    await jobs.finish(first, 99)
    async with tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run)
        assert job.owner_id == second.owner_id
        assert job.active_ms == settings.WORKER_LEASE_SECONDS * 1000


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_plan_pause_survives_new_pool_and_decision_is_idempotent(monkeypatch, decision):
    tenant, _, run_id, settings = await seed(monkeypatch, approval=True)
    planner = AsyncMock(return_value=builder._heuristic_plan("Compare durable research", 1))
    monkeypatch.setattr(builder, "_plan_with_openai", planner)
    original_build = builder.build_graph
    collected = []

    # Use the real planner and approval nodes and official PostgreSQL saver;
    # a deterministic final node proves no paid boundary runs before approval.
    def graph(settings, checkpointer=None):
        real = original_build(settings, checkpointer=checkpointer)
        test_graph = StateGraph(builder.RunState)
        for name in ("planner", "approval_gate"):
            test_graph.add_node(name, real.nodes[name].bound.afunc)

        async def collect(state):
            collected.append(state["run_id"])
            async with tenant_session(str(tenant)) as session:
                run = await session.get(ResearchRun, run_id)
                run.status = "completed"
            return {}

        test_graph.add_node("collect", collect)
        test_graph.add_edge(START, "planner")
        test_graph.add_edge("planner", "approval_gate")
        test_graph.add_edge("approval_gate", "collect")
        test_graph.add_edge("collect", END)
        return test_graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(builder, "build_graph", graph)
    first = await jobs.claim(tenant, uuid.uuid4(), settings)
    async with CheckpointPool(settings) as pool:
        await dispatcher.execute(first, settings, pool)
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        assert run.status == "awaiting_approval"
        assert job.state == "waiting" and job.owner_id is None
        plan_id = run.active_plan_id
        paused_ms = job.active_ms
        statuses = list(
            await session.scalars(
                select(NodeExecution.status).where(
                    NodeExecution.run_id == run_id,
                    NodeExecution.tenant_id == tenant,
                )
            )
        )
        assert "paused" in statuses and "failed" not in statuses
    assert collected == [] and planner.await_count == 1
    monkeypatch.setattr(api, "_caller", runtime_api._caller)
    waiting_snapshot = await api.get_research_run(run_id)
    waiting = waiting_snapshot["approval"]
    waiting_timing = waiting_snapshot["timing"]
    assert waiting["state"] == "pending"
    assert waiting["waitStartedAt"] and waiting["waitedMs"] == 0
    assert waiting_timing["processingMs"] == paused_ms
    assert waiting_timing["approvalWaitMs"] >= waiting["waitedMs"]
    assert waiting_timing["elapsedMs"] >= waiting_timing["processingMs"]
    payload = ApprovalRequest(planId=plan_id, decision=decision)
    await runtime_api.approve(run_id, payload)
    decided = (await api.get_research_run(run_id))["approval"]
    assert decided["state"] == decision
    assert decided["waitStartedAt"] is None and decided["waitedMs"] >= 0
    await runtime_api.approve(run_id, payload)
    with pytest.raises(HTTPException) as conflict:
        await runtime_api.approve(
            run_id,
            ApprovalRequest(
                planId=plan_id,
                decision="reject" if decision == "approve" else "approve",
            ),
        )
    assert conflict.value.status_code == 409
    second = await jobs.claim(tenant, uuid.uuid4(), settings)
    if decision == "approve":
        assert second
        async with CheckpointPool(settings) as pool:
            await dispatcher.execute(second, settings, pool)
    else:
        assert second is None
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        expected = "completed" if decision == "approve" else "cancelled"
        assert run.status == job.state == expected
        assert job.active_ms >= paused_ms
    assert len(collected) == (1 if decision == "approve" else 0)
    assert planner.await_count == 1


async def editable_plan(monkeypatch):
    tenant, user, run_id, settings = await seed(monkeypatch, approval=True)
    planned = builder._heuristic_plan("Compare durable research", 1)
    plan_id = uuid.uuid4()
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        run.status = "awaiting_approval"
        run.active_plan_id = plan_id
        run.plan_version = 1
        job.state = "waiting"
        session.add(
            ResearchPlan(
                id=plan_id,
                tenant_id=tenant,
                run_id=run_id,
                plan_version=1,
                plan=planned.model_dump(mode="json"),
            )
        )
    return tenant, user, run_id, plan_id


async def test_plan_edit_is_versioned_and_stale_edits_conflict(monkeypatch):
    tenant, _, run_id, plan_id = await editable_plan(monkeypatch)
    from research_api.runtime_api import EditResearchPlanRequest

    payload = EditResearchPlanRequest.model_validate(
        {
            "planId": str(plan_id),
            "expectedPlanVersion": 1,
            "questions": ["How does durable execution work in research systems?"],
        }
    )
    edited = await runtime_api.edit_plan(run_id, payload)
    assert edited.plan_version == 2 and edited.plan_id != plan_id
    assert edited.questions[0].question == "How does durable execution work in research systems?"
    with pytest.raises(HTTPException) as stale:
        await runtime_api.edit_plan(run_id, payload)
    assert stale.value.status_code == 409
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        versions = list(
            await session.scalars(
                select(ResearchPlan.plan_version).where(
                    ResearchPlan.tenant_id == tenant,
                    ResearchPlan.run_id == run_id,
                )
            )
        )
        assert run.plan_version == 2 and run.active_plan_id == edited.plan_id
        assert sorted(versions) == [1, 2]


async def test_batch_atomic_capacity_and_idempotency(monkeypatch):
    tenant, _, _, settings = await seed(
        monkeypatch, settings=Settings(MAX_PENDING_RUNS_PER_TENANT=2)
    )
    payload = BatchRequest(
        questions=["First research", "Second research"], idempotencyKey=str(uuid.uuid4())
    )
    with pytest.raises(HTTPException) as full:
        await runtime_api.create_batch(payload)
    assert full.value.status_code == 429
    async with tenant_session(str(tenant)) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ResearchBatch)
                .where(
                    ResearchBatch.tenant_id == tenant,
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RuntimeJob)
                .where(
                    RuntimeJob.tenant_id == tenant,
                )
            )
            == 1
        )
    smaller = BatchRequest(
        questions=["First research"],
        idempotencyKey=payload.idempotency_key,
        mode="focused",
    )
    first = await runtime_api.create_batch(smaller)
    assert await runtime_api.create_batch(smaller) == first
    assert len(first["runIds"]) == 1
    async with tenant_session(str(tenant)) as session:
        batch = await session.get(ResearchBatch, uuid.UUID(first["batchId"]))
        child = await session.get(ResearchRun, uuid.UUID(first["runIds"][0]))
        assert batch.mode == child.mode == "focused"
        assert batch.mode_policy_version == child.mode_policy_version
    with pytest.raises(HTTPException) as conflict:
        await runtime_api.create_batch(
            BatchRequest(
                questions=["Changed research"],
                idempotencyKey=payload.idempotency_key,
            )
        )
    assert conflict.value.status_code == 409


async def test_schedule_two_ticks_create_one_occurrence_and_disable(monkeypatch):
    tenant, _, _, settings = await seed(monkeypatch)
    request = ScheduleRequest(
        question="Track reliable research",
        intervalMinutes=60,
        idempotencyKey=str(uuid.uuid4()),
        mode="deep",
    )
    first = await runtime_api.create_schedule(request)
    assert await runtime_api.create_schedule(request) == first
    schedule_id = uuid.UUID(first["id"])
    async with tenant_session(str(tenant)) as session:
        schedule = await session.get(ResearchSchedule, schedule_id)
        schedule.next_run_at = datetime.now(UTC) - timedelta(days=10)
    await asyncio.gather(
        jobs.claim(tenant, uuid.uuid4(), settings), jobs.claim(tenant, uuid.uuid4(), settings)
    )
    async with tenant_session(str(tenant)) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ResearchRun)
                .where(
                    ResearchRun.tenant_id == tenant,
                    ResearchRun.idempotency_key.like(f"schedule:{schedule_id}:%"),
                )
            )
            == 1
        )
        schedule = await session.get(ResearchSchedule, schedule_id)
        assert schedule.next_run_at > datetime.now(UTC)
        occurrence = await session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == tenant,
                ResearchRun.idempotency_key.like(f"schedule:{schedule_id}:%"),
            )
        )
        assert schedule.mode == occurrence.mode == "deep"
        assert schedule.mode_policy_version == occurrence.mode_policy_version
    await runtime_api.disable_schedule(schedule_id)
    async with tenant_session(str(tenant)) as session:
        assert not (await session.get(ResearchSchedule, schedule_id)).enabled


async def test_incompatible_graph_fails_without_dispatch(monkeypatch):
    tenant, _, run, settings = await seed(monkeypatch)
    async with tenant_session(str(tenant)) as session:
        (await session.get(RuntimeJob, run)).graph_version = "unknown"
    assert await jobs.claim(tenant, uuid.uuid4(), settings) is None
    async with tenant_session(str(tenant)) as session:
        row = await session.get(ResearchRun, run)
        assert row.status == "failed" and row.error_code == "graph_version_incompatible"


async def test_cancel_waiting_job_releases_capacity_without_resume(monkeypatch):
    from research_api import api

    tenant, _, run_id, _ = await seed(monkeypatch, approval=True)
    monkeypatch.setattr(api, "_caller", runtime_api._caller)
    async with tenant_session(str(tenant)) as session:
        (await session.get(ResearchRun, run_id)).status = "awaiting_approval"
        (await session.get(RuntimeJob, run_id)).state = "waiting"
    await api.cancel_research_run(run_id)
    async with tenant_session(str(tenant)) as session:
        assert (await session.get(ResearchRun, run_id)).status == "cancelled"
        assert (await session.get(RuntimeJob, run_id)).state == "cancelled"


async def test_crashed_node_resumes_checkpoint_without_replanning(monkeypatch):
    tenant, _, run_id, settings = await seed(monkeypatch)
    original_build = builder.build_graph
    plan = AsyncMock(return_value=builder._heuristic_plan("Compare durable research", 1))
    monkeypatch.setattr(builder, "_plan_with_openai", plan)
    attempts = []

    def graph(settings, checkpointer=None):
        real = original_build(settings, checkpointer=checkpointer)
        graph = StateGraph(builder.RunState)
        graph.add_node("planner", real.nodes["planner"].bound.afunc)

        async def crash_once(state):
            attempts.append(state["run_id"])
            if len(attempts) == 1:
                raise asyncio.CancelledError
            async with tenant_session(str(tenant)) as session:
                (await session.get(ResearchRun, run_id)).status = "completed"
            return {}

        graph.add_node("crash_once", crash_once)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "crash_once")
        graph.add_edge("crash_once", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(builder, "build_graph", graph)
    first = await jobs.claim(tenant, uuid.uuid4(), settings)
    async with CheckpointPool(settings) as pool:
        with pytest.raises(asyncio.CancelledError):
            await dispatcher.execute(first, settings, pool)
    async with tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run_id)
        assert job.state == "running"
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    second = await jobs.claim(tenant, uuid.uuid4(), settings)
    async with CheckpointPool(settings) as pool:
        await dispatcher.execute(second, settings, pool)
    async with tenant_session(str(tenant)) as session:
        assert (await session.get(ResearchRun, run_id)).status == "completed"
        assert (await session.get(RuntimeJob, run_id)).state == "completed"
    assert plan.await_count == 1 and len(attempts) == 2


@pytest.mark.parametrize("active_ms", [120_000, 119_990])
async def test_runtime_deadline_is_not_reset_by_recovery(monkeypatch, active_ms):
    tenant, _, run_id, settings = await seed(monkeypatch)

    def graph(settings, checkpointer=None):
        graph = StateGraph(builder.RunState)

        async def slow(state):
            await asyncio.sleep(1)
            raise AssertionError("deadline must interrupt this node")

        graph.add_node("slow", slow)
        graph.add_edge(START, "slow")
        graph.add_edge("slow", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(builder, "build_graph", graph)
    async with tenant_session(str(tenant)) as session:
        (await session.get(RuntimeJob, run_id)).active_ms = active_ms
    fence = await jobs.claim(tenant, uuid.uuid4(), settings)
    async with CheckpointPool(settings) as pool:
        await dispatcher.execute(fence, settings, pool)
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        assert run.status == job.state == "failed"
        assert run.error_code == "wall_clock_limit_exceeded"
        assert job.active_ms >= active_ms


@pytest.mark.parametrize("report_committed", [True, False])
async def test_deadline_after_open_node_settles_task_with_run(monkeypatch, report_committed):
    tenant, _, run_id, settings = await seed(monkeypatch)

    def graph(settings, checkpointer=None):
        graph = StateGraph(builder.RunState)

        async def synthesizer(state):
            await start_node(tenant, run_id, "synthesizer")
            if report_committed:
                async with tenant_session(str(tenant)) as session:
                    run = await lock_run(session, tenant, run_id)
                    report = Report(tenant_id=tenant, run_id=run_id, version=1, markdown="Fixture")
                    session.add(report)
                    await session.flush()
                    run.report_id, run.status = report.id, "completed"
            await asyncio.sleep(5)
            raise AssertionError("deadline must interrupt this node")

        graph.add_node("synthesizer", synthesizer)
        graph.add_edge(START, "synthesizer")
        graph.add_edge("synthesizer", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(builder, "build_graph", graph)
    async with tenant_session(str(tenant)) as session:
        budget = await session.scalar(select(Budget).where(Budget.run_id == run_id))
        (await session.get(RuntimeJob, run_id)).active_ms = budget.max_wall_clock_ms - 1_000
    fence = await jobs.claim(tenant, uuid.uuid4(), settings)
    async with CheckpointPool(settings) as pool:
        await dispatcher.execute(fence, settings, pool)
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        node = await session.scalar(select(NodeExecution).where(NodeExecution.run_id == run_id))
        expected = "completed" if report_committed else "failed"
        assert run.status == node.status == expected
        assert node.completed_at is not None
        if not report_committed:
            assert run.error_code == "wall_clock_limit_exceeded"


async def test_repair_plan_requires_its_own_approval_before_more_collection(monkeypatch):
    tenant, _, run_id, settings = await seed(monkeypatch, approval=True)
    monkeypatch.setattr(
        builder,
        "_plan_with_openai",
        AsyncMock(
            return_value=builder._heuristic_plan("Compare durable research", 1),
        ),
    )
    original_build = builder.build_graph
    collections = []

    def graph(settings, checkpointer=None):
        real = original_build(settings, checkpointer=checkpointer)
        graph = StateGraph(builder.RunState)
        for name in ("planner", "approval_gate", "planner_delta"):
            graph.add_node(name, real.nodes[name].bound.afunc)

        async def collect(state):
            collections.append(state["sub_question_ids"])
            async with tenant_session(str(tenant)) as session:
                if state.get("reflection_round", 0) == 0:
                    question = await session.get(
                        SubQuestion, uuid.UUID(state["sub_question_ids"][0])
                    )
                    question.status = "failed"
                else:
                    (await session.get(ResearchRun, run_id)).status = "completed"
            return {}

        graph.add_node("collect", collect)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "approval_gate")
        graph.add_edge("approval_gate", "collect")
        graph.add_conditional_edges(
            "collect", lambda state: END if state.get("reflection_round", 0) else "planner_delta"
        )
        graph.add_edge("planner_delta", "approval_gate")
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(builder, "build_graph", graph)
    monkeypatch.setattr(api, "_caller", runtime_api._caller)
    plans, waits = [], []
    for expected_collections in (0, 1):
        fence = await jobs.claim(tenant, uuid.uuid4(), settings)
        async with CheckpointPool(settings) as pool:
            await dispatcher.execute(fence, settings, pool)
        async with tenant_session(str(tenant)) as session:
            run = await session.get(ResearchRun, run_id)
            assert run.status == "awaiting_approval"
            plans.append(run.active_plan_id)
        assert len(collections) == expected_collections
        waits.append((await api.get_research_run(run_id))["approval"])
        await runtime_api.approve(run_id, ApprovalRequest(planId=plans[-1], decision="approve"))
    assert plans[0] != plans[1]
    # The repair plan opens its own wait; collection time between them is not paused.
    assert waits[0]["waitedMs"] == 0 and waits[0]["waitStartedAt"]
    assert waits[1]["waitStartedAt"] > waits[0]["waitStartedAt"]
    first_gap = datetime.fromisoformat(waits[1]["waitStartedAt"]) - datetime.fromisoformat(
        waits[0]["waitStartedAt"]
    )
    assert 0 <= waits[1]["waitedMs"] <= first_gap.total_seconds() * 1000
    fence = await jobs.claim(tenant, uuid.uuid4(), settings)
    async with CheckpointPool(settings) as pool:
        await dispatcher.execute(fence, settings, pool)
    async with tenant_session(str(tenant)) as session:
        assert (await session.get(ResearchRun, run_id)).status == "completed"
    assert len(collections) == 2 and collections[0] != collections[1]


async def test_explicit_retry_time_changes_only_new_runs_deadline(monkeypatch):
    from research_api import api

    tenant, _, prior_id, _ = await seed(monkeypatch)
    monkeypatch.setattr(api, "_caller", runtime_api._caller)
    async with tenant_session(str(tenant)) as session:
        (await session.get(ResearchRun, prior_id)).status = "failed"
        (await session.get(RuntimeJob, prior_id)).state = "failed"
        budget = await session.scalar(select(Budget).where(Budget.run_id == prior_id))
        budget.max_search_calls = 20
    result = await api.retry_research_run(prior_id, SimpleNamespace(), max_wall_clock_ms=600_000)
    async with tenant_session(str(tenant)) as session:
        old = await session.scalar(select(Budget).where(Budget.run_id == prior_id))
        fresh = await session.scalar(
            select(Budget).where(Budget.run_id == uuid.UUID(result["runId"]))
        )
        assert old.max_wall_clock_ms == 120_000 and fresh.max_wall_clock_ms == 600_000
        for field in (
            "max_search_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_estimated_cost_usd",
        ):
            assert getattr(old, field) == getattr(fresh, field)


async def abandoned_attempts(monkeypatch):
    tenant, user, run_id, settings = await seed(monkeypatch)
    fence = await jobs.claim(tenant, uuid.uuid4(), settings)
    node_id = await start_node(tenant, run_id, "research_worker")
    async with tenant_session(str(tenant)) as session:
        plan = ResearchPlan(tenant_id=tenant, run_id=run_id, plan_version=1, plan={})
        session.add(plan)
        await session.flush()
        question = SubQuestion(
            tenant_id=tenant,
            run_id=run_id,
            plan_id=plan.id,
            question="Collect fixture evidence",
            payload={},
            status="running",
            attempts=1,
        )
        session.add(question)
        await session.flush()
        attempt = SubQuestionAttempt(
            id=uuid.uuid4(),
            tenant_id=tenant,
            run_id=run_id,
            sub_question_id=question.id,
            attempt=1,
            status="running",
            started_at=datetime.now(UTC),
        )
        session.add(attempt)
        (await session.get(ResearchRun, run_id)).status = "researching"
        (await session.get(RuntimeJob, run_id)).lease_expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        other = await RunRepository(session, tenant).create(user_id=user, question="Other run")
        other_run_id = other.id
    other_node = await start_node(tenant, other_run_id, "planner")
    return tenant, run_id, settings, fence, node_id, attempt.id, other_node


async def test_takeover_closes_abandoned_attempts_and_events_atomically(monkeypatch):
    tenant, run_id, settings, first, node_id, attempt_id, other_node = await abandoned_attempts(
        monkeypatch
    )
    original = EventOutbox.append

    async def fail_after_event(self, **kwargs):
        await original(self, **kwargs)
        raise RuntimeError("injected takeover rollback")

    monkeypatch.setattr(EventOutbox, "append", fail_after_event)
    with pytest.raises(RuntimeError, match="injected takeover rollback"):
        await jobs.claim(tenant, uuid.uuid4(), settings)
    async with tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run_id)
        assert job.generation == first.generation and job.owner_id == first.owner_id
        assert (await session.get(NodeExecution, node_id)).status == "running"
        assert (await session.get(SubQuestionAttempt, attempt_id)).status == "running"
        assert (
            await session.scalar(
                select(func.count()).select_from(RunEvent).where(RunEvent.run_id == run_id)
            )
            == 1
        )  # Only the original task-start event survived.
    monkeypatch.setattr(EventOutbox, "append", original)
    claims = await asyncio.gather(*(jobs.claim(tenant, uuid.uuid4(), settings) for _ in range(3)))
    assert sum(item is not None for item in claims) == 1
    second = next(item for item in claims if item)
    assert second.generation == first.generation + 1
    assert not await jobs.heartbeat(first, 1, settings)
    async with tenant_session(str(tenant)) as session:
        for model, identity in ((NodeExecution, node_id), (SubQuestionAttempt, attempt_id)):
            row = await session.get(model, identity)
            assert row.status == "failed" and row.completed_at is not None
        assert (
            await session.get(SubQuestionAttempt, attempt_id)
        ).error_code == "worker_lease_expired"
        assert (await session.get(NodeExecution, other_node)).status == "running"
        events = list(
            await session.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.event_sequence)
            )
        )
        assert [event.event_sequence for event in events] == [1, 2, 3]
        assert {event.payload["taskId"] for event in events[1:]} == {str(node_id), str(attempt_id)}
        assert all(event.payload["status"] == "failed" for event in events[1:])


async def test_takeover_excludes_inflight_emitter_and_rejects_stale_task_writes(monkeypatch):
    tenant, run_id, settings, first, node_id, attempt_id, _ = await abandoned_attempts(monkeypatch)
    async with tenant_session(str(tenant)) as session:
        (await session.get(RuntimeJob, run_id)).lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=1
        )
    token = current_job.set(first)
    try:
        async with tenant_session(str(tenant)) as session:
            # Match worker/emitter order: shared job fence, then the run lock.
            await lock_run(session, tenant, run_id)
            await session.execute(text("SELECT pg_sleep(1.05)"))
            # Expiry alone cannot allow takeover while this authorized write is in flight.
            probe_token = current_job.set(None)
            try:
                assert await asyncio.wait_for(jobs.claim(tenant, uuid.uuid4(), settings), 2) is None
            finally:
                current_job.reset(probe_token)
            attempt = await session.get(SubQuestionAttempt, attempt_id)
            attempt.status, attempt.completed_at = "completed", datetime.now(UTC)
            await EventOutbox(session, tenant).append(
                run_id=run_id,
                event_type="task.state",
                payload={
                    "taskId": str(attempt_id),
                    "nodeId": "research_task",
                    "status": "completed",
                    "attempt": 1,
                    "label": "Completed in flight",
                },
            )
    finally:
        current_job.reset(token)
    second = await jobs.claim(tenant, uuid.uuid4(), settings)
    assert second and second.generation == first.generation + 1
    token = current_job.set(first)
    try:
        with pytest.raises(LeaseLostError):
            await finish_node(tenant, run_id, node_id, "completed")
        with pytest.raises(LeaseLostError):
            async with tenant_session(str(tenant)) as session:
                await EventOutbox(session, tenant).append(
                    run_id=run_id, event_type="fixture.stale", payload={"label": "Must not commit"}
                )
    finally:
        current_job.reset(token)
    async with tenant_session(str(tenant)) as session:
        assert (await session.get(NodeExecution, node_id)).status == "failed"
        assert (await session.get(SubQuestionAttempt, attempt_id)).status == "completed"
        events = list(
            await session.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.event_sequence)
            )
        )
        assert [event.event_sequence for event in events] == [1, 2, 3]
        assert [event.payload["status"] for event in events] == ["running", "completed", "failed"]


@pytest.mark.parametrize("incompatible", [False, True])
async def test_committed_cancel_precedes_recovery_failure(monkeypatch, incompatible):
    from research_api import api

    tenant, run_id, settings, _, node_id, attempt_id, _ = await abandoned_attempts(monkeypatch)
    monkeypatch.setattr(api, "_caller", runtime_api._caller)
    async with tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run_id)
        job.attempts = 5
        if incompatible:
            job.graph_version = "incompatible"
    result = await api.cancel_research_run(run_id)
    assert result["status"] == "researching"
    for _ in range(2):
        assert await jobs.claim(tenant, uuid.uuid4(), settings) is None
    async with tenant_session(str(tenant)) as session:
        run, job = await session.get(ResearchRun, run_id), await session.get(RuntimeJob, run_id)
        assert run.status == job.state == "cancelled"
        assert run.cancelled_at == run.cancellation_requested_at
        assert run.error_code is None and job.owner_id is None and job.lease_expires_at is None
        assert (await session.get(NodeExecution, node_id)).status == "cancelled"
        assert (await session.get(SubQuestionAttempt, attempt_id)).status == "cancelled"
        types = list(
            await session.scalars(select(RunEvent.event_type).where(RunEvent.run_id == run_id))
        )
        assert types.count("run.cancelled") == 1 and "run.failed" not in types


@pytest.mark.parametrize("user_cancel", [False, True])
async def test_collection_shutdown_resumes_but_user_cancel_stays_terminal(monkeypatch, user_cancel):
    from research_api import api

    settings = Settings(_env_file=None, TAVILY_API_KEY="fixture")
    tenant, _, run_id, settings = await seed(monkeypatch, settings=settings)
    monkeypatch.setattr(api, "_caller", runtime_api._caller)
    planner = AsyncMock(return_value=builder._heuristic_plan("Compare durable research", 1))
    monkeypatch.setattr(builder, "_plan_with_openai", planner)
    entered = asyncio.Event()
    slots = []

    async def ingest(**kwargs):
        slots.append(kwargs["max_results"])
        if len(slots) == 1:
            entered.set()
            await asyncio.Event().wait()  # Cancel before any provider dispatch.
        return [uuid.uuid4()]

    monkeypatch.setattr(collection, "S3ArtifactStore", lambda **kwargs: object())
    monkeypatch.setattr(
        collection, "TavilyAdapter", lambda **kwargs: SimpleNamespace(aclose=AsyncMock())
    )
    monkeypatch.setattr(
        collection, "TavilyEvidenceIngestor", lambda **kwargs: SimpleNamespace(ingest=ingest)
    )
    original_build = builder.build_graph

    def graph(settings, checkpointer=None):
        real = original_build(settings, checkpointer=checkpointer)
        graph = StateGraph(builder.RunState)
        for name in ("planner", "research_worker"):
            graph.add_node(name, real.nodes[name].bound.afunc)

        async def complete(state):
            async with tenant_session(str(tenant)) as session:
                (await session.get(ResearchRun, run_id)).status = "completed"
            return {}

        graph.add_node("complete", complete)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "research_worker")
        graph.add_edge("research_worker", "complete")
        graph.add_edge("complete", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(builder, "build_graph", graph)
    first = await jobs.claim(tenant, uuid.uuid4(), settings)
    async with CheckpointPool(settings) as pool:
        task = asyncio.create_task(dispatcher.execute(first, settings, pool))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if user_cancel:
                await api.cancel_research_run(run_id)
            task.cancel()
            if user_cancel:
                await asyncio.wait_for(task, 5)
            else:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with tenant_session(str(tenant)) as session:
        question = await session.scalar(select(SubQuestion).where(SubQuestion.run_id == run_id))
        assert question.status == ("skipped" if user_cancel else "pending")
        job = await session.get(RuntimeJob, run_id)
        if not user_cancel:
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    second = await jobs.claim(tenant, uuid.uuid4(), settings)
    if user_cancel:
        assert second is None and len(slots) == 1
    else:
        assert second is not None
        async with CheckpointPool(settings) as pool:
            await dispatcher.execute(second, settings, pool)
        assert len(slots) == 2 and slots[0] == slots[1] and planner.await_count == 1
    async with tenant_session(str(tenant)) as session:
        expected = "cancelled" if user_cancel else "completed"
        assert (await session.get(ResearchRun, run_id)).status == expected
        assert (await session.get(RuntimeJob, run_id)).state == expected
        attempts = list(
            await session.scalars(
                select(SubQuestionAttempt)
                .where(SubQuestionAttempt.run_id == run_id)
                .order_by(SubQuestionAttempt.attempt)
            )
        )
        assert [row.status for row in attempts] == (
            ["cancelled"] if user_cancel else ["cancelled", "completed"]
        )
