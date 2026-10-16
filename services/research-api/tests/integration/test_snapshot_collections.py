"""Local-only equivalence, bounds, isolation and comparative timing; all seeds roll back."""

import os
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest
from psycopg import AsyncCursor
from psycopg.errors import UndefinedColumn
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from research_api import snapshots
from research_api.db.models import (
    NodeExecution,
    ProviderCall,
    ProviderCallReservation,
    Report,
    ResearchGap,
    ResearchPlan,
    ResearchRun,
    RunEvent,
    Source,
    SubQuestion,
    SubQuestionAttempt,
    Tenant,
    User,
)
from research_api.snapshots import SnapshotCollections, load_collections

pytestmark = pytest.mark.integration

# Independent baseline of the API's existing ORM SELECTs.
COLLECTIONS = (
    ("sources", Source, Source.retrieved_at.desc(), 200),
    ("questions", SubQuestion, SubQuestion.created_at, 16),
    ("nodes", NodeExecution, NodeExecution.started_at, 60),
    ("attempts", SubQuestionAttempt, SubQuestionAttempt.started_at, 32),
    ("gaps", ResearchGap, ResearchGap.created_at, 40),
    ("versions", Report, Report.version.desc(), 20),
    ("calls", ProviderCall, ProviderCall.started_at, 100),
    ("events", RunEvent, RunEvent.event_sequence.desc(), 40),
)


async def sequential(session, tenant, run):
    result = {}
    for name, model, order, limit in COLLECTIONS:
        result[name] = list(
            await session.scalars(
                select(model)
                .where(model.tenant_id == tenant, model.run_id == run)
                .order_by(order)
                .limit(limit)
            )
        )
    return SnapshotCollections(**result)


def values(record):
    return {column.key: getattr(record, column.key) for column in inspect(type(record)).columns}


async def seed(session, tenant, run, *, create_tenant=True):
    user, plan, question = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )
    if create_tenant:
        await session.execute(insert(Tenant).values(id=tenant, name="Snapshot fixture"))
    await session.execute(
        insert(User).values(id=user, tenant_id=tenant, external_subject=str(user))
    )
    common = {"tenant_id": tenant, "run_id": run}
    await session.execute(
        insert(ResearchRun).values(
            id=run,
            tenant_id=tenant,
            user_id=user,
            original_question="Fixture",
            normalized_question="Fixture",
            thread_id=str(run),
        )
    )
    await session.execute(
        insert(ResearchPlan).values(
            id=plan,
            **common,
            plan_version=1,
            plan={},
        )
    )
    await session.execute(
        insert(SubQuestion),
        [
            dict(
                id=question if i == 0 else uuid4(),
                **common,
                plan_id=plan,
                question=f"Question {i}",
                payload={},
                created_at=now + timedelta(seconds=i),
            )
            for i in range(18)
        ],
    )
    for _, model, _, limit in COLLECTIONS:
        if model is SubQuestion:
            continue
        records = []
        for i in range(limit + 2):
            timestamp = now + timedelta(seconds=i)
            row = dict(id=uuid4(), **common)
            if model is Source:
                row.update(
                    canonical_url=f"https://example.test/{i}",
                    title=f"Source {i}",
                    provider="fixture",
                    source_class="primary",
                    retrieved_at=timestamp,
                    content_hash=f"{i:064x}",
                    artifact_ref="fixture",
                    quality_score=Decimal("0.7500"),
                    discovery_paths=[{"query": "fixture"}],
                    content_signature=[],
                )
            elif model is NodeExecution:
                row.update(
                    node_id=f"node-{i}",
                    attempt=1,
                    output_hash=f"{i:064x}",
                    status="completed",
                    started_at=timestamp,
                )
            elif model is SubQuestionAttempt:
                row.update(
                    sub_question_id=question,
                    attempt=i + 1,
                    status="completed",
                    started_at=timestamp,
                )
            elif model is ResearchGap:
                row.update(
                    description=f"Gap {i}",
                    materiality="high",
                    details={"index": i},
                    created_at=timestamp,
                )
            elif model is Report:
                row.update(
                    version=i + 1, markdown=f"Report {i}", published=True, created_at=timestamp
                )
            elif model is ProviderCall:
                reservation = uuid4()
                await session.execute(
                    insert(ProviderCallReservation).values(
                        id=reservation,
                        **common,
                        provider="fixture",
                        operation="search",
                        request_fingerprint=str(i),
                        reserved_search_calls=1,
                        reserved_estimated_cost_usd=Decimal("0.001"),
                    )
                )
                row.update(
                    reservation_id=reservation,
                    provider="fixture",
                    operation="search",
                    request_fingerprint=str(i),
                    request_schema_version="1",
                    provider_usage={"tokens": i},
                    started_at=timestamp,
                )
            elif model is RunEvent:
                row.update(
                    event_sequence=i + 1,
                    event_type="fixture",
                    payload={"index": i},
                    occurred_at=timestamp,
                )
            records.append(row)
        await session.execute(insert(model), records)


@pytest.fixture
async def seeded_session():
    # Shared conftest rejects any non-loopback URL, including environment overrides.
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    tenant, run, other_tenant, other_run, same_tenant_run = [
                        uuid4() for _ in range(5)
                    ]
                    await seed(session, tenant, run)
                    await seed(session, tenant, same_tenant_run, create_tenant=False)
                    await seed(session, other_tenant, other_run)
                    await session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant, true)"),
                        {"tenant": str(tenant)},
                    )
                    await session.execute(text("SET LOCAL ROLE research_app"))
                    yield session, tenant, run, other_tenant, other_run
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def test_pipeline_matches_orm_bounds_types_rls_and_transaction(seeded_session):
    session, tenant, run, other_tenant, other_run = seeded_session
    before = await sequential(session, tenant, run)
    identity_map = dict(session.identity_map)
    pending = Source(id=uuid4(), tenant_id=tenant, run_id=run)
    session.add(pending)  # Deliberately incomplete: raw reads must never autoflush it.
    after = await load_collections(session, tenant, run)
    for name, _model, _, limit in COLLECTIONS:
        old, new = getattr(before, name), getattr(after, name)
        assert len(new) == limit
        assert [values(record) for record in new] == [values(record) for record in old]
        assert all(inspect(record).transient for record in new)
        assert all(record.tenant_id == tenant and record.run_id == run for record in new)
    assert dict(session.identity_map) == identity_map
    assert pending in session.new
    session.expunge(pending)
    assert isinstance(after.sources[0].quality_score, Decimal)
    assert isinstance(after.sources[0].retrieved_at, datetime)
    assert isinstance(after.sources[0].id, type(run))
    for target_tenant, target_run in [
        (tenant, other_run),
        (other_tenant, run),
        (other_tenant, other_run),
        (tenant, uuid4()),
    ]:
        empty = await load_collections(session, target_tenant, target_run)
        assert all(not getattr(empty, field.name) for field in fields(empty))
    # The borrowed connection and transaction remain usable, with the same RLS context.
    assert await session.scalar(text("SELECT current_setting('app.tenant_id')")) == str(tenant)
    assert await session.scalar(text("SELECT current_user")) == "research_app"


async def test_local_before_after_timing(seeded_session):
    session, tenant, run, *_ = seeded_session
    measurements = {"sequential": [], "pipeline": []}
    # Warm both paths; alternate order to reduce cache/order bias. No latency threshold
    # on loopback: this measures local work, not hosted network RTT.
    for index in range(12):
        loaders = [("sequential", sequential), ("pipeline", load_collections)]
        if index % 2:
            loaders.reverse()
        for name, loader in loaders:
            started = perf_counter()
            result = await loader(session, tenant, run)
            elapsed = (perf_counter() - started) * 1000
            assert len(result.sources) == 200
            if index >= 2:
                measurements[name].append(elapsed)
    print(
        "local collection median ms: "
        + ", ".join(f"{name}={median(samples):.3f}" for name, samples in measurements.items())
    )


async def test_real_pipeline_error_closes_cursors_and_owner_can_recover(
    seeded_session, monkeypatch, caplog
):
    session, tenant, run, *_ = seeded_session
    closed = []
    original_close = AsyncCursor.close

    async def record_close(cursor):
        await original_close(cursor)
        closed.append(cursor)

    monkeypatch.setattr(AsyncCursor, "close", record_close)
    queries = list(snapshots._QUERIES)
    queries[3] = queries[3].replace("SELECT *", "SELECT missing_snapshot_fixture_column")
    monkeypatch.setattr(snapshots, "_QUERIES", tuple(queries))
    # SQLAlchemy owns recovery; the loader must propagate the native driver error.
    with pytest.raises(UndefinedColumn):
        async with session.begin_nested():
            # Exclude SQLAlchemy's SAVEPOINT cursor from the tracked loader cursors.
            closed.clear()
            await load_collections(session, tenant, run)
    assert len(closed) >= 8
    assert all(cursor.closed for cursor in closed)
    assert "missing_snapshot_fixture_column" not in caplog.text
    assert str(tenant) not in caplog.text
    assert str(run) not in caplog.text
    monkeypatch.undo()
    assert len((await load_collections(session, tenant, run)).sources) == 200
