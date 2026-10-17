"""Regression: one busy registry must not block another tenant's real claim."""

import asyncio
import os
import uuid
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import dispatcher, jobs
from research_api.config import Settings
from research_api.db.models import (
    Budget,
    DispatchRegistry,
    ResearchRun,
    RuntimeJob,
    Tenant,
    UsageLedger,
    User,
)
from research_api.db.session import engine, tenant_session
from research_api.repositories.runs import RunRepository


@pytest.mark.integration
async def test_busy_registry_does_not_block_later_tenant_execution(monkeypatch):
    # Fail closed before any connection or fixture write, including cleanup.
    urls = [engine.url, make_url(os.environ["TEST_DATABASE_ADMIN_URL"])]
    for url in urls:
        assert url.drivername == "postgresql+psycopg"
        assert url.host in {"localhost", "127.0.0.1", "::1"}
        assert not url.query
    assert (urls[0].host, urls[0].port, urls[0].database) == (
        urls[1].host,
        urls[1].port,
        urls[1].database,
    )
    assert os.environ["APP_ENV"] == "test"

    settings = Settings(WORKER_CONCURRENCY=2)
    tenants = [uuid.uuid4(), uuid.uuid4()]
    users = [uuid.uuid4(), uuid.uuid4()]
    runs = []
    completed = {tenant: asyncio.Event() for tenant in tenants}
    executions = []
    admin = create_async_engine(urls[1])
    admin_sessions = async_sessionmaker(admin)
    loop_task = None

    async def execute(fence, _settings, _pool):
        # Completion means this local execution stub returned, not graph completion.
        executions.append(fence)
        completed[fence.tenant_id].set()

    monkeypatch.setattr(jobs, "discover", AsyncMock(return_value=tenants))
    monkeypatch.setattr(dispatcher, "execute", execute)
    try:
        async with admin_sessions() as session, session.begin():
            for tenant, user in zip(tenants, users, strict=True):
                session.add(Tenant(id=tenant, name="Dispatcher HOL characterization"))
                session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
        for tenant, user in zip(tenants, users, strict=True):
            async with tenant_session(str(tenant)) as session:
                run = await RunRepository(session, tenant).create(
                    user_id=user, question="Characterize local dispatcher ordering"
                )
                await jobs.enqueue(session, run, settings)
                runs.append(run.id)

        # Hold A throughout the observation, and throughout B's progress gate.
        async with tenant_session(str(tenants[0])) as holder:
            await jobs.lock_registry(holder, tenants[0])
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            loop_task = asyncio.create_task(dispatcher.dispatch_loop(settings, pool=None))
            blocked_pid = None
            async with asyncio.timeout(10):
                async with admin.connect() as observer:
                    # Refresh pg_stat_activity on each poll; a transaction snapshot
                    # can otherwise hide the newly opened claim connection.
                    await observer.execution_options(isolation_level="AUTOCOMMIT")
                    while True:
                        blocked_pid = await observer.scalar(
                            text(
                                "SELECT a.pid FROM pg_stat_activity a "
                                "WHERE a.datname = current_database() "
                                "AND :holder = ANY(pg_blocking_pids(a.pid)) "
                                "LIMIT 1"
                            ),
                            {"holder": holder_pid},
                        )
                        if completed[tenants[1]].is_set() or blocked_pid is not None:
                            break
                        if loop_task.done():
                            await loop_task
                            pytest.fail("dispatcher exited before its claim blocked")
                        await asyncio.sleep(0.01)

            # Release is forbidden until B executes. The event is the success
            # signal; an observed database wait explains the baseline failure.
            try:
                async with asyncio.timeout(3):
                    await completed[tenants[1]].wait()
            except TimeoutError:
                pytest.fail(
                    "tenant B did not execute while tenant A registry remained held; "
                    f"PostgreSQL observed claim blocked by holder: {blocked_pid is not None}"
                )
            assert [fence.tenant_id for fence in executions] == [tenants[1]]
            async with tenant_session(str(tenants[0])) as session:
                job = await session.scalar(select(RuntimeJob).where(RuntimeJob.run_id == runs[0]))
                assert job is not None
                assert (job.state, job.owner_id, job.generation, job.attempts) == (
                    "queued",
                    None,
                    0,
                    0,
                )

            # For the gate this read is still inside A's registry transaction.
            async with tenant_session(str(tenants[1])) as session:
                job = await session.scalar(select(RuntimeJob).where(RuntimeJob.run_id == runs[1]))
                assert job is not None
                assert job.state == "running" and job.generation == job.attempts == 1
                assert job.owner_id == executions[0].owner_id

        # Commit releases A; skipping must not lose or postpone that queued job.
        async with asyncio.timeout(10):
            await completed[tenants[0]].wait()
        assert [fence.tenant_id for fence in executions] == [tenants[1], tenants[0]]
        async with tenant_session(str(tenants[1])) as session:
            job = await session.scalar(select(RuntimeJob).where(RuntimeJob.run_id == runs[1]))
            assert job is not None
            assert job.state == "running" and job.generation == job.attempts == 1
            b_fence = next(fence for fence in executions if fence.tenant_id == tenants[1])
            assert job.owner_id == b_fence.owner_id
    finally:
        if loop_task is not None:
            loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await loop_task
        try:
            # Only UUID-scoped fixture rows; no schema, pool or application changes.
            async with admin_sessions() as session, session.begin():
                for model in (RuntimeJob, DispatchRegistry, UsageLedger, Budget, ResearchRun, User):
                    await session.execute(delete(model).where(model.tenant_id.in_(tenants)))
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenants)))
        finally:
            await admin.dispose()
