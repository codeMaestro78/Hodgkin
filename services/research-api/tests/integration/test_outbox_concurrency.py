"""Exercise the FK-lock upgrade that occurs when parallel research tasks start."""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api.config import Settings
from research_api.db.models import (
    ResearchPlan,
    RunEvent,
    SubQuestion,
    SubQuestionAttempt,
    Tenant,
    User,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.graph import builder
from research_api.repositories.runs import RunRepository


async def seed():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Outbox fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(user_id=user, question="Fixture")
        return tenant, run.id


@pytest.mark.integration
async def test_parallel_task_start_preserves_order_without_fk_upgrade_deadlock():
    tenant, run = await seed()
    questions = [uuid.uuid4() for _ in range(3)]
    async with tenant_session(str(tenant)) as session:
        plan = ResearchPlan(id=uuid.uuid4(), tenant_id=tenant, run_id=run, plan_version=1, plan={})
        session.add(plan)
        await session.flush()
        for question in questions:
            session.add(
                SubQuestion(
                    id=question,
                    tenant_id=tenant,
                    run_id=run,
                    plan_id=plan.id,
                    question="Fixture question",
                    status="pending",
                    payload={},
                )
            )
    barrier = asyncio.Barrier(3)

    async def start(question):
        async with tenant_session(str(tenant)) as session:
            attempt = SubQuestionAttempt(
                id=uuid.uuid4(),
                tenant_id=tenant,
                run_id=run,
                sub_question_id=question,
                attempt=1,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(attempt)
            await session.flush()  # All callers now hold FK KEY SHARE locks.
            await barrier.wait()
            await EventOutbox(session, tenant).append(
                run_id=run,
                event_type="task.state",
                payload={
                    "taskId": str(attempt.id),
                    "nodeId": "research_task",
                    "status": "running",
                    "attempt": 1,
                    "label": "Started",
                },
            )

    async with asyncio.timeout(10):
        await asyncio.gather(*(start(question) for question in questions))
    async with tenant_session(str(tenant)) as session:
        sequences = list(
            await session.scalars(
                select(RunEvent.event_sequence)
                .where(
                    RunEvent.tenant_id == tenant,
                    RunEvent.run_id == run,
                )
                .order_by(RunEvent.event_sequence)
            )
        )
    assert sequences == [1, 2, 3]


@pytest.mark.integration
async def test_real_worker_starts_parallel_attempts_with_local_db(monkeypatch):
    tenant, run = await seed()
    questions = [uuid.uuid4() for _ in range(3)]
    async with tenant_session(str(tenant)) as session:
        plan = ResearchPlan(id=uuid.uuid4(), tenant_id=tenant, run_id=run, plan_version=1, plan={})
        session.add(plan)
        await session.flush()
        for question in questions:
            session.add(
                SubQuestion(
                    id=question,
                    tenant_id=tenant,
                    run_id=run,
                    plan_id=plan.id,
                    question="Fixture question",
                    payload={},
                )
            )
    ingest = AsyncMock(return_value=[])
    monkeypatch.setattr(builder, "S3ArtifactStore", lambda **_kwargs: object())
    close = AsyncMock()
    monkeypatch.setattr(builder, "TavilyAdapter", lambda **_kwargs: SimpleNamespace(aclose=close))
    monkeypatch.setattr(
        builder, "TavilyEvidenceIngestor", lambda **_kwargs: SimpleNamespace(ingest=ingest)
    )
    worker = (
        builder.build_graph(Settings(TAVILY_API_KEY="fixture")).nodes["research_worker"].bound.afunc
    )
    async with asyncio.timeout(10):
        await worker(
            {
                "tenant_id": str(tenant),
                "run_id": str(run),
                "sub_question_ids": [str(q) for q in questions],
                "quick_mode": False,
            }
        )
    assert ingest.await_count == 3
    close.assert_awaited_once()
    async with tenant_session(str(tenant)) as session:
        attempts = list(
            await session.scalars(
                select(SubQuestionAttempt).where(
                    SubQuestionAttempt.tenant_id == tenant, SubQuestionAttempt.run_id == run
                )
            )
        )
    assert len(attempts) == 3
    assert all(attempt.status == "failed" for attempt in attempts)  # Empty evidence is not success.
