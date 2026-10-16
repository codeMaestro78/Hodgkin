"""Committed PostgreSQL events must wake the actual SSE tail without polling delay."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from statistics import median
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import api
from research_api.db import session as sessions
from research_api.db.models import Budget, ResearchRun, RunEvent, Tenant, UsageLedger, User
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.events.wakeups import EventWakeups, event_wakeups
from research_api.repositories.runs import RunRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def research_run(monkeypatch):
    tenant, user = uuid.uuid4(), uuid.uuid4()
    admin = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    async with async_sessionmaker(admin)() as session, session.begin():
        session.add(Tenant(id=tenant, name="SSE wakeup fixture"))
        session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user, question="Compare recorded evidence"
        )
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
    try:
        yield tenant, run.id
    finally:
        async with async_sessionmaker(admin)() as session, session.begin():
            for model in (RunEvent, Budget, UsageLedger, ResearchRun, User, Tenant):
                column = model.id if model is Tenant else model.tenant_id
                await session.execute(delete(model).where(column == tenant))
        await admin.dispose()


@pytest.mark.parametrize("state", ["researching", "awaiting_approval"])
async def test_committed_event_preempts_sse_idle_poll(research_run, state):
    tenant, run = research_run
    async with tenant_session(str(tenant)) as session:
        (await session.get(ResearchRun, run)).status = state
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
    stream = api.stream_research_run_events(run, request, after=0)
    assert (await anext(stream)).comment == "keepalive"
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)  # Resume the generator into its idle wait.
    try:
        async with tenant_session(str(tenant)) as session:
            await EventOutbox(session, tenant).append(
                run_id=run, event_type="fixture.event", payload={"label": "Evidence ready"}
            )
        result = await asyncio.wait_for(waiting, timeout=0.35)
        assert result.id == "1"
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        await stream.aclose()


async def test_commit_to_sse_latency_sample(research_run):
    tenant, run = research_run
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
    stream = api.stream_research_run_events(run, request, after=0)
    await anext(stream)
    samples = []
    try:
        for index in range(10):
            waiting = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            async with tenant_session(str(tenant)) as session:
                await EventOutbox(session, tenant).append(
                    run_id=run, event_type="fixture.event", payload={"label": "Measured commit"}
                )
            started = monotonic()
            assert (await asyncio.wait_for(waiting, timeout=0.35)).id == str(index + 1)
            samples.append((monotonic() - started) * 1000)
        print(
            {
                "measurement": "local_postgres_commit_to_sse_ms",
                "samples": len(samples),
                "p50": round(median(samples), 2),
                "p95_nearest_rank": round(max(samples), 2),
            }
        )
    finally:
        await stream.aclose()


async def test_no_wakeup_before_commit_or_after_outer_rollback(research_run):
    tenant, run = research_run
    with event_wakeups.watch(tenant, run) as wake:
        with pytest.raises(ValueError, match="rollback fixture"):
            async with tenant_session(str(tenant)) as session:
                await EventOutbox(session, tenant).append(
                    run_id=run, event_type="fixture.event", payload={"label": "Never published"}
                )
                assert not wake.is_set()
                raise ValueError("rollback fixture")
        assert not wake.is_set()
        async with tenant_session(str(tenant)) as session:
            assert await EventOutbox(session, tenant).replay_after(run_id=run, sequence=0) == []


@pytest.mark.parametrize("outer_event", [False, True])
async def test_savepoint_rollback_does_not_publish_rolled_back_events(research_run, outer_event):
    tenant, run = research_run
    with event_wakeups.watch(tenant, run) as wake:
        async with tenant_session(str(tenant)) as session:
            if outer_event:
                await EventOutbox(session, tenant).append(
                    run_id=run, event_type="fixture.event", payload={"label": "Committed"}
                )
            with pytest.raises(ValueError, match="savepoint fixture"):
                async with session.begin_nested():
                    await EventOutbox(session, tenant).append(
                        run_id=run, event_type="fixture.event", payload={"label": "Rolled back"}
                    )
                    raise ValueError("savepoint fixture")
            assert not wake.is_set()
        assert wake.is_set() is outer_event


async def test_separate_hubs_deliver_committed_event_over_redis(research_run, monkeypatch):
    tenant, run = research_run
    writer, reader = EventWakeups(), EventWakeups()
    monkeypatch.setattr(sessions, "event_wakeups", writer)
    monkeypatch.setattr(api, "event_wakeups", reader)
    url = os.environ["TEST_REDIS_URL"]  # conftest rejects non-loopback targets.
    async with writer.transport(url), reader.transport(url):
        await asyncio.wait_for(reader.connected.wait(), timeout=3)
        request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
        stream = api.stream_research_run_events(run, request, after=0)
        assert (await anext(stream)).comment == "keepalive"
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        try:
            async with tenant_session(str(tenant)) as session:
                await EventOutbox(session, tenant).append(
                    run_id=run, event_type="fixture.event", payload={"label": "Remote commit"}
                )
            assert (await asyncio.wait_for(waiting, timeout=0.35)).id == "1"
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            await stream.aclose()


async def test_missed_hint_still_replays_postgres(research_run, monkeypatch):
    tenant, run = research_run
    # No Redis transport and a separate local hub deliberately miss every hint.
    monkeypatch.setattr(api, "event_wakeups", EventWakeups())
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
    stream = api.stream_research_run_events(run, request, after=0)
    assert (await anext(stream)).comment == "keepalive"
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    try:
        async with tenant_session(str(tenant)) as session:
            await EventOutbox(session, tenant).append(
                run_id=run, event_type="fixture.event", payload={"label": "Replay fallback"}
            )
        assert (await asyncio.wait_for(waiting, timeout=1.5)).id == "1"
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        await stream.aclose()


async def test_commit_between_read_and_wait_is_not_lost(research_run, monkeypatch):
    tenant, run = research_run
    reads = 0

    @asynccontextmanager
    async def commit_after_empty_read(scope):
        nonlocal reads
        reads += 1
        async with tenant_session(scope) as session:
            yield session
        if reads == 2:  # Ownership read first, then the empty replay query.
            async with tenant_session(str(tenant)) as session:
                await EventOutbox(session, tenant).append(
                    run_id=run, event_type="fixture.event", payload={"label": "Concurrent commit"}
                )

    monkeypatch.setattr(api, "tenant_session", commit_after_empty_read)
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
    stream = api.stream_research_run_events(run, request, after=0)
    try:
        assert (await anext(stream)).comment == "keepalive"
        assert (await asyncio.wait_for(anext(stream), timeout=0.35)).id == "1"
    finally:
        await stream.aclose()
