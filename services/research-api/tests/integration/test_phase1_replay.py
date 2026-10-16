"""Graph admission against local PostgreSQL; no graph/provider dispatch occurs."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import jobs
from research_api.config import Settings
from research_api.db import session as db_session
from research_api.db.models import (
    Budget,
    DispatchRegistry,
    ResearchRun,
    RunEvent,
    RuntimeJob,
    Tenant,
    UsageLedger,
    User,
)
from research_api.repositories.runs import RunRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def queued_run(monkeypatch):
    # conftest validates loopback URLs while preserving development/CI ports.
    settings = Settings(_env_file=None)
    admin = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    app = create_async_engine(os.environ["DATABASE_URL"])
    monkeypatch.setattr(
        db_session, "session_factory", async_sessionmaker(app, expire_on_commit=False)
    )
    tenant, user = uuid.uuid4(), uuid.uuid4()
    try:
        async with async_sessionmaker(admin)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Phase1 replay fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
        async with db_session.tenant_session(str(tenant)) as session:
            run, _ = await RunRepository(session, tenant).create_once(
                user_id=user,
                question="Compare evidence-backed research approaches",
                report_requirements=["Compare operational risks"],
            )
            await jobs.enqueue(session, run, settings)
        yield tenant, run.id, settings
    finally:
        # Remove only this fixture's tenant and the rows created by these tests.
        async with async_sessionmaker(admin)() as session, session.begin():
            for model in (
                RunEvent,
                RuntimeJob,
                Budget,
                UsageLedger,
                ResearchRun,
                DispatchRegistry,
                User,
            ):
                await session.execute(delete(model).where(model.tenant_id == tenant))
            await session.execute(delete(Tenant).where(Tenant.id == tenant))
        await app.dispose()
        await admin.dispose()


@pytest.mark.parametrize(
    "version,requirements",
    [("research-v3", []), ("research-v4", []), ("research-v4", ["Compare risks"])],
)
@pytest.mark.parametrize("expired", [False, True])
async def test_compatible_graph_claim_preserves_identity_and_exclusive_lease(
    queued_run, version, requirements, expired
):
    tenant, run_id, settings = queued_run
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        run.report_requirements = requirements
        job = await session.get(RuntimeJob, run_id)
        job.graph_version = version
        if expired:
            run.status = "researching"
            job.state = "running"
            job.owner_id = uuid.uuid4()
            job.generation = 3
            job.attempts = 2
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    owner = uuid.uuid4()
    fence = await jobs.claim(tenant, owner, settings)
    assert fence is not None and fence.run_id == run_id and fence.owner_id == owner
    assert await jobs.claim(tenant, uuid.uuid4(), settings) is None
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        assert job.graph_version == version
        assert job.state == "running" and job.owner_id == owner
        assert job.generation == fence.generation == (4 if expired else 1)
        assert job.attempts == (3 if expired else 1)
        assert job.active_ms == (settings.WORKER_LEASE_SECONDS * 1000 if expired else 0)
        assert run.report_requirements == requirements and run.error_code is None


@pytest.mark.parametrize(
    "version,requirements",
    [
        ("research-v3", ["Compare risks"]),
        ("research-v3", [""]),
        ("research-v2", []),
        ("unknown", []),
    ],
)
@pytest.mark.parametrize("expired", [False, True])
async def test_incompatible_graph_fails_closed_once_without_claim_or_version_upgrade(
    queued_run, version, requirements, expired
):
    tenant, run_id, settings = queued_run
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        run.report_requirements = requirements
        job = await session.get(RuntimeJob, run_id)
        job.graph_version = version
        if expired:
            run.status = "researching"
            job.state = "running"
            job.owner_id = uuid.uuid4()
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    for _ in range(2):
        assert await jobs.claim(tenant, uuid.uuid4(), settings) is None
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        assert run.status == job.state == "failed"
        assert run.error_code == "graph_version_incompatible"
        assert job.graph_version == version and job.generation == job.attempts == 0
        assert job.active_ms == 0 and job.owner_id is None and job.lease_expires_at is None
        events = list(await session.scalars(select(RunEvent).where(RunEvent.run_id == run_id)))
        assert len(events) == 1 and events[0].event_type == "run.failed"
        assert events[0].payload["retryable"] is False
        assert events[0].payload["errorCode"] == "graph_version_incompatible"


@pytest.mark.parametrize("version", ["research-v3", "research-v4", "unknown"])
@pytest.mark.parametrize("expired", [False, True])
async def test_cancellation_precedes_graph_incompatibility_and_recovery_limit(
    queued_run, version, expired
):
    tenant, run_id, settings = queued_run
    cancelled_at = datetime.now(UTC)
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        run.cancellation_requested_at = cancelled_at
        job = await session.get(RuntimeJob, run_id)
        job.graph_version = version
        job.attempts = 5
        if expired:
            run.status = "researching"
            job.state = "running"
            job.owner_id = uuid.uuid4()
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    for _ in range(2):
        assert await jobs.claim(tenant, uuid.uuid4(), settings) is None
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        assert run.status == job.state == "cancelled"
        assert run.cancelled_at == cancelled_at and run.error_code is None
        assert job.graph_version == version and job.attempts == 5 and job.generation == 0
        assert job.owner_id is None and job.lease_expires_at is None
        events = list(await session.scalars(select(RunEvent).where(RunEvent.run_id == run_id)))
        assert len(events) == 1 and events[0].event_type == "run.cancelled"


@pytest.mark.parametrize(
    "version,requirements", [("research-v3", []), ("research-v4", ["Compare risks"])]
)
async def test_compatible_graph_does_not_reset_recovery_limit(queued_run, version, requirements):
    tenant, run_id, settings = queued_run
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        run.report_requirements = requirements
        job = await session.get(RuntimeJob, run_id)
        job.graph_version = version
        job.attempts = 5
    assert await jobs.claim(tenant, uuid.uuid4(), settings) is None
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        assert run.status == job.state == "failed" and run.error_code == "recovery_limit"
        assert job.attempts == 5 and job.generation == 0


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_terminal_run_is_never_reclaimed_or_reclassified(queued_run, status):
    tenant, run_id, settings = queued_run
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        run.status = status
        job = await session.get(RuntimeJob, run_id)
        job.graph_version = "research-v3"
    assert await jobs.claim(tenant, uuid.uuid4(), settings) is None
    async with db_session.tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        job = await session.get(RuntimeJob, run_id)
        assert run.status == job.state == status and run.error_code is None
        assert job.attempts == job.generation == 0


async def test_new_jobs_are_pinned_to_v4(queued_run):
    tenant, run_id, _ = queued_run
    async with db_session.tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run_id)
        assert job.graph_version == jobs.GRAPH_VERSION == "research-v4"
