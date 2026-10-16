"""Local PostgreSQL regressions for API submission and terminal-state races."""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import api
from research_api.db.models import (
    Report,
    ResearchGap,
    ResearchRun,
    RunEvent,
    RuntimeJob,
    Tenant,
    User,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.execution import finish_node, start_node
from research_api.graph import builder
from research_api.repositories.runs import RunRepository
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest
from research_api.schemas.generated.followup_request import FollowupRequest

pytestmark = pytest.mark.integration


async def fixture_run(monkeypatch):
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Atomic lifecycle fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(user_id=user, question="Compare evidence")
    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id=tenant,
                user_id=user,
            )
        ),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_tasks=set())))
    return tenant, user, run.id, request


@pytest.mark.parametrize("terminal", ["cancelled", "completed", "failed"])
async def test_transition_cannot_resurrect_terminal_run(monkeypatch, terminal):
    tenant, _, run, _ = await fixture_run(monkeypatch)
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        row.status = terminal
    try:
        await builder._transition(
            tenant_id=tenant,
            run_id=run,
            status="researching",
            event_type="research_worker.started",
            label="Fixture",
        )
    except asyncio.CancelledError:
        pass
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        assert row.status == terminal
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RunEvent)
                .where(RunEvent.tenant_id == tenant, RunEvent.run_id == run)
            )
            == 0
        )


async def test_transition_does_not_overwrite_committed_cancel_request(monkeypatch):
    tenant, _, run, _ = await fixture_run(monkeypatch)
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        row.status = "planning"
        row.cancellation_requested_at = datetime.now(UTC)
    with pytest.raises(asyncio.CancelledError):
        await builder._transition(
            tenant_id=tenant,
            run_id=run,
            status="researching",
            event_type="research_worker.started",
            label="Fixture",
        )


async def test_cancel_commits_while_transition_waits_for_run_lock(monkeypatch):
    tenant, _, run, _ = await fixture_run(monkeypatch)
    entered = asyncio.Event()
    original = builder.lock_run

    async def observe_lock(*args):
        entered.set()
        return await original(*args)

    monkeypatch.setattr(builder, "lock_run", observe_lock)
    task = None
    try:
        async with tenant_session(str(tenant)) as session:
            row = await original(session, tenant, run)
            row.status = "planning"
            task = asyncio.create_task(
                builder._transition(
                    tenant_id=tenant,
                    run_id=run,
                    status="researching",
                    event_type="research_worker.started",
                    label="Fixture",
                )
            )
            await asyncio.wait_for(entered.wait(), 2)
            row.cancellation_requested_at = datetime.now(UTC)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        async with tenant_session(str(tenant)) as session:
            row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
            assert row.status == "planning" and row.cancellation_requested_at is not None
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_plan_result_after_cancellation_is_not_persisted(monkeypatch):
    from research_api.config import Settings
    from research_api.db.models import ResearchPlan

    tenant, _, run, _ = await fixture_run(monkeypatch)

    async def plan(_settings, question, count):
        await api.cancel_research_run(run)
        return builder._heuristic_plan(question, count)

    monkeypatch.setattr(builder, "_plan_with_openai", plan)
    planner = builder.build_graph(Settings()).nodes["planner"].bound.afunc
    with pytest.raises(asyncio.CancelledError):
        await planner(
            {
                "tenant_id": str(tenant),
                "run_id": str(run),
                "question": "Compare evidence",
                "quick_mode": False,
            }
        )
    async with tenant_session(str(tenant)) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ResearchPlan)
                .where(ResearchPlan.tenant_id == tenant, ResearchPlan.run_id == run)
            )
            == 0
        )


async def test_concurrent_submissions_create_one_run_and_dispatch_once(monkeypatch):
    tenant, _, _, request = await fixture_run(monkeypatch)
    key = str(uuid.uuid4())
    payload = CreateResearchRunRequest(
        question="Compare live evidence", reportRequirements=[], idempotencyKey=key
    )
    barrier = asyncio.Barrier(4)

    async def submit():
        await barrier.wait()
        return await api.create_research_run(payload, request)

    results = await asyncio.gather(*(submit() for _ in range(4)), return_exceptions=True)
    assert all(isinstance(item, dict) for item in results), [
        type(item).__name__ for item in results
    ]
    assert len({item["runId"] for item in results}) == 1
    async with tenant_session(str(tenant)) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RuntimeJob)
                .where(RuntimeJob.tenant_id == tenant, RuntimeJob.run_id == results[0]["runId"])
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ResearchRun)
                .where(ResearchRun.tenant_id == tenant, ResearchRun.idempotency_key == key)
            )
            == 1
        )


@pytest.mark.parametrize("change", ["question", "requirements", "budget"])
async def test_reused_key_with_changed_request_returns_conflict(monkeypatch, change):
    _, _, _, request = await fixture_run(monkeypatch)
    key = str(uuid.uuid4())
    fields = dict(question="Compare live evidence", reportRequirements=[], idempotencyKey=key)
    await api.create_research_run(CreateResearchRunRequest(**fields), request)
    if change == "question":
        fields["question"] = "Compare different evidence"
    if change == "requirements":
        fields["reportRequirements"] = ["Include limitations"]
    if change == "budget":
        fields["budgetOverrides"] = {"maxSearchCalls": 6}
    with pytest.raises(HTTPException) as conflict:
        await api.create_research_run(CreateResearchRunRequest(**fields), request)
    assert conflict.value.status_code == 409


async def test_gap_investigation_cannot_be_overwritten_by_second_request(monkeypatch):
    tenant, _, run, request = await fixture_run(monkeypatch)
    async with tenant_session(str(tenant)) as session:
        report = Report(
            id=uuid.uuid4(),
            tenant_id=tenant,
            run_id=run,
            version=1,
            markdown="Fixture report",
            published=True,
        )
        session.add(report)
        await session.flush()
        parent = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        parent.status, parent.report_id = "completed", report.id
        gap = ResearchGap(
            id=uuid.uuid4(),
            tenant_id=tenant,
            run_id=run,
            description="Missing evidence",
            materiality="high",
            status="open",
            target_query="Find evidence",
            details={"reportId": str(report.id)},
        )
        session.add(gap)
        gap_id = gap.id
    body = FollowupRequest(
        question="Investigate missing evidence", gapId=gap_id, idempotencyKey=str(uuid.uuid4())
    )
    first = await api.followup_research_run(run, body, request)
    replay = await api.followup_research_run(run, body, request)
    assert replay["runId"] == first["runId"]
    with pytest.raises(HTTPException) as changed_gap:
        await api.followup_research_run(run, body.model_copy(update={"gap_id": None}), request)
    assert changed_gap.value.status_code == 409
    with pytest.raises(HTTPException) as conflict:
        await api.followup_research_run(
            run,
            body.model_copy(
                update={
                    "idempotency_key": str(uuid.uuid4()),
                }
            ),
            request,
        )
    assert conflict.value.status_code == 409
    async with tenant_session(str(tenant)) as session:
        gap = await session.scalar(select(ResearchGap).where(ResearchGap.id == gap_id))
        assert gap.details["followupRunId"] == first["runId"]


async def test_sse_reconnect_drains_all_terminal_replay_pages(monkeypatch):
    tenant, _, run, _ = await fixture_run(monkeypatch)
    async with tenant_session(str(tenant)) as session:
        for index in range(300):
            await EventOutbox(session, tenant).append(
                run_id=run, event_type="fixture.event", payload={"label": str(index)}
            )
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        row.status = "failed"
    request = SimpleNamespace(
        headers={"last-event-id": "40"}, is_disconnected=AsyncMock(return_value=False)
    )
    results = [item async for item in api.stream_research_run_events(run, request, after=0)]
    assert [item.id for item in results] == [str(index) for index in range(41, 301)]
    import httpx

    from research_api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        response = await client.get(
            f"/research/runs/{run}/events?after=0", headers={"last-event-id": "40"}
        )
    assert response.status_code == 200
    payloads = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert all(isinstance(payload, dict) for payload in payloads)
    assert [payload["sequence"] for payload in payloads] == list(range(41, 301))


async def test_invalid_sse_cursor_is_rejected(monkeypatch):
    _, _, run, _ = await fixture_run(monkeypatch)
    request = SimpleNamespace(
        headers={"last-event-id": "invalid"}, is_disconnected=AsyncMock(return_value=False)
    )
    with pytest.raises(HTTPException) as invalid:
        _ = [item async for item in api.stream_research_run_events(run, request, after=0)]
    assert invalid.value.status_code == 422


@pytest.mark.parametrize("state,cancel", [("writing", True), ("failed", False)])
async def test_synthesizer_completion_cannot_overwrite_cancel_or_failure(
    monkeypatch, state, cancel
):
    tenant, _, run, _ = await fixture_run(monkeypatch)
    task = await start_node(tenant, run, "synthesizer")
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        report = Report(
            id=uuid.uuid4(),
            tenant_id=tenant,
            run_id=run,
            version=1,
            markdown="Fixture",
            published=True,
        )
        session.add(report)
        await session.flush()
        row.report_id, row.status = report.id, state
        if cancel:
            row.cancellation_requested_at = datetime.now(UTC)
    await finish_node(tenant, run, task, "completed")
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        assert row.status == state
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RunEvent)
                .where(
                    RunEvent.tenant_id == tenant,
                    RunEvent.run_id == run,
                    RunEvent.event_type == "run.completed",
                )
            )
            == 0
        )
