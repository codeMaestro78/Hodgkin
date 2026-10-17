"""Offline composition checks plus opt-in PostgreSQL checks AFTER lead GO and 0014.

Never applies migrations or creates schema. PostgreSQL data lives in one rolled
back transaction; no live providers or hosted services are contacted.
"""

import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from research_api.db.models import ResearchRun, Source, Tenant, User
from research_api.db.source_relationships import SourceIdentityRecord, SourceRelationship
from research_api.repositories.source_relationships import (
    SourceRelationshipRepository,
    persist_source_relationships,
)
from research_api.source_identity import map_source_identity

pytestmark = pytest.mark.integration


def source(tenant, run, **kwargs):
    return Source(
        id=uuid4(),
        tenant_id=tenant,
        run_id=run,
        canonical_url=f"https://example.test/{uuid4()}",
        title="Observed page",
        publisher=None,
        provider="tavily",
        source_class="unknown",
        retrieved_at=datetime.now(UTC),
        content_hash="a" * 64,
        artifact_ref="fixture",
        **kwargs,
    )


async def test_repository_scopes_read_and_uses_conflict_key_without_committing():
    tenant, run = uuid4(), uuid4()
    sources = [source(tenant, run), source(tenant, run)]
    inserted = Mock()
    inserted.all.return_value = ["same_content"]
    session = AsyncMock(spec=AsyncSession)
    session.scalars.side_effect = [sources, [], inserted]
    assert (
        await SourceRelationshipRepository(session, tenant).link_sources(
            run_id=run, source_ids=[s.id for s in sources]
        )
        == 1
    )
    read = session.scalars.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
    assert "sources.tenant_id =" in str(read) and "sources.run_id =" in str(read)
    assert tenant in read.params.values() and run in read.params.values()
    write = str(session.scalars.call_args_list[2].args[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (tenant_id, run_id, from_source_id, to_source_id, kind) DO NOTHING" in write
    session.commit.assert_not_awaited()


async def test_bounds_and_scope_fail_before_any_write():
    tenant, run, missing = uuid4(), uuid4(), uuid4()
    session = AsyncMock(spec=AsyncSession)
    repo = SourceRelationshipRepository(session, tenant)
    assert await repo.link_sources(run_id=run, source_ids=[]) == 0
    for ids in ([missing, missing], [uuid4() for _ in range(21)]):
        with pytest.raises(ValueError):
            await repo.link_sources(run_id=run, source_ids=ids)
    session.scalars.assert_not_awaited()
    session.scalars.return_value = []
    with pytest.raises(ValueError, match="tenant and run"):
        await repo.link_sources(run_id=run, source_ids=[missing])
    assert session.scalars.await_count == 1


async def test_run_entrypoint_bounds_reads_and_rejects_oversized_runs():
    tenant, run = uuid4(), uuid4()
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = [source(tenant, run) for _ in range(21)]
    with pytest.raises(ValueError, match="20"):
        await persist_source_relationships(session, tenant, run)
    statement = session.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "LIMIT" in str(statement) and 21 in statement.params.values()
    session.execute.assert_not_awaited()
    assert session.scalars.await_count == 1


async def test_identity_replay_uses_first_persisted_basis_and_never_updates_source():
    tenant, run = uuid4(), uuid4()
    sources = [source(tenant, run), source(tenant, run)]
    supplied = map_source_identity(
        canonical_url="https://doi.org/10.1234/replay",
        publisher="New publisher",
        publisher_basis={"basis": "structured_metadata", "evidence_ref": "fixture:new"},
    )
    records = [
        SourceIdentityRecord(
            tenant_id=tenant,
            run_id=run,
            source_id=s.id,
            work_id=None,
            publisher=None,
            metadata_basis={},
        )
        for s in sources
    ]
    inserted = Mock()
    inserted.all.return_value = ["same_content"]
    session = AsyncMock(spec=AsyncSession)
    session.scalars.side_effect = [sources, records, inserted]
    assert (
        await SourceRelationshipRepository(session, tenant).link_sources(
            run_id=run,
            source_ids=[s.id for s in sources],
            observed_identities={s.id: supplied for s in sources},
        )
        == 1
    )
    identity_sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (tenant_id, run_id, source_id) DO NOTHING" in identity_sql
    relationship_sql = (
        session.scalars.call_args_list[2].args[0].compile(dialect=postgresql.dialect())
    )
    assert "same_work" not in relationship_sql.params.values()
    assert "same_publisher" not in relationship_sql.params.values()
    assert all(s.publisher is None and s.source_class == "unknown" for s in sources)
    session.commit.assert_not_awaited()


def test_migration_security_statements_without_executing_ddl(monkeypatch):
    path = Path(__file__).parents[2] / (
        "src/research_api/db/migrations/versions/0014_source_relationships.py"
    )
    spec = importlib.util.spec_from_file_location("source_relationship_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operations = Mock()
    monkeypatch.setattr(module, "op", operations)
    create = Mock()
    monkeypatch.setattr(SourceRelationship.__table__, "create", create)
    monkeypatch.setattr(SourceIdentityRecord.__table__, "create", Mock())
    module.upgrade()
    sql = "\n".join(str(call.args[0]) for call in operations.execute.call_args_list)
    assert module.down_revision == "0013"
    assert "UNIQUE (tenant_id, run_id, id)" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "WITH CHECK" in sql and "app.tenant_id" in sql
    for role in ("PUBLIC", "anon", "authenticated", "research_app"):
        assert f"REVOKE ALL ON public.source_relationships FROM {role}" in sql
    assert "GRANT SELECT, INSERT, DELETE ON public.source_relationships TO research_app" in sql
    assert "UPDATE public.sources" not in sql
    assert "ADD COLUMN" not in sql
    assert "ALTER TABLE public.source_identities FORCE ROW LEVEL SECURITY" in sql
    create.assert_called_once()


def test_registered_composite_constraints_cover_both_endpoint_scopes():
    from sqlalchemy import ForeignKeyConstraint

    for table, endpoint in (
        (SourceRelationship.__table__, "from_source_id"),
        (SourceRelationship.__table__, "to_source_id"),
        (SourceIdentityRecord.__table__, "source_id"),
    ):
        fk = next(
            c
            for c in table.constraints
            if isinstance(c, ForeignKeyConstraint) and endpoint in c.column_keys
        )
        assert list(fk.column_keys) == ["tenant_id", "run_id", endpoint]
        assert [e.target_fullname for e in fk.elements] == [
            "sources.tenant_id",
            "sources.run_id",
            "sources.id",
        ]
    constraints = [c for c in Source.__table__.constraints if c.name == "uq_sources_tenant_run_id"]
    assert len(constraints) == 1
    assert list(constraints[0].columns.keys()) == ["tenant_id", "run_id", "id"]


@pytest.fixture
async def pg_session():
    if os.getenv("PHASE2_G_POSTGRES_GO") != "1":
        pytest.skip("held until lead GO, Phase 1 gate and separately applied local 0014")
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(
                    text("SELECT to_regclass('public.source_relationships') IS NOT NULL")
                ), "0014 must already be applied after lead GO"
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def seed(session):
    tenant, user, run, other_run = uuid4(), uuid4(), uuid4(), uuid4()
    await session.execute(
        text("SELECT set_config('app.tenant_id', :id, true)"), {"id": str(tenant)}
    )
    session.add(Tenant(id=tenant, name="Source relationship disposable fixture"))
    await session.flush()
    session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    await session.flush()
    for run_id in (run, other_run):
        session.add(
            ResearchRun(
                id=run_id,
                tenant_id=tenant,
                user_id=user,
                original_question="Fixture",
                normalized_question="Fixture",
                thread_id=str(run_id),
            )
        )
    await session.flush()
    sources = [source(tenant, run), source(tenant, run), source(tenant, other_run)]
    session.add_all(sources)
    await session.flush()
    await session.execute(text("SET LOCAL ROLE research_app"))
    return tenant, run, sources


async def test_postgres_replay_rls_and_forced_policy(pg_session):
    session = pg_session
    tenant, run, sources = await seed(session)
    repo = SourceRelationshipRepository(session, tenant)
    ids = [s.id for s in sources[:2]]
    assert await repo.link_sources(run_id=run, source_ids=ids) == 1
    assert await repo.link_sources(run_id=run, source_ids=list(reversed(ids))) == 0
    row = (await session.scalars(select(SourceRelationship))).one()
    assert row.kind == "same_content" and row.confidence == "observed"
    flags = (
        await session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid='public.source_relationships'::regclass"
            )
        )
    ).one()
    assert tuple(flags) == (True, True)
    for table in ("source_relationships", "source_identities"):
        for privilege in ("SELECT", "INSERT", "DELETE", "UPDATE"):
            allowed = await session.scalar(
                text("SELECT has_table_privilege('research_app', :table, :privilege)"),
                {"table": table, "privilege": privilege},
            )
            assert allowed == (privilege != "UPDATE")
        for role in ("anon", "authenticated"):
            exists = await session.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}
            )
            if exists:
                assert not await session.scalar(
                    text(
                        "SELECT has_table_privilege(:role, :table, 'SELECT,INSERT,UPDATE,DELETE')"
                    ),
                    {"role": role, "table": table},
                )
    for context in (str(uuid4()), ""):
        await session.execute(
            text("SELECT set_config('app.tenant_id', :id, true)"), {"id": context}
        )
        assert list(await session.scalars(select(SourceRelationship))) == []
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                session.add(
                    SourceRelationship(
                        tenant_id=tenant,
                        run_id=run,
                        from_source_id=min(ids),
                        to_source_id=max(ids),
                        kind="same_work",
                        basis={"test": True},
                    )
                )
                await session.flush()


@pytest.mark.parametrize("foreign_tenant", [False, True])
async def test_postgres_endpoint_fks_reject_wrong_run_or_tenant(pg_session, foreign_tenant):
    session = pg_session
    tenant, run, sources = await seed(session)
    if foreign_tenant:
        # Existing endpoints under another tenant must fail the composite FK,
        # even if the row itself passes RLS for the active tenant.
        tenant = uuid4()
        await session.execute(text("RESET ROLE"))
        await session.execute(
            text("SELECT set_config('app.tenant_id', :id, true)"), {"id": str(tenant)}
        )
        session.add(Tenant(id=tenant, name="Other fixture tenant"))
        await session.flush()
        await session.execute(text("SET LOCAL ROLE research_app"))
    endpoints = sorted([sources[0].id, sources[2].id])
    with pytest.raises(DBAPIError) as error:
        async with session.begin_nested():
            session.add(
                SourceRelationship(
                    tenant_id=tenant,
                    run_id=run,
                    from_source_id=endpoints[0],
                    to_source_id=endpoints[1],
                    kind="same_content",
                    basis={"test": True},
                )
            )
            await session.flush()
    assert error.value.orig.sqlstate == "23503"


async def test_postgres_observed_identity_persistence_and_replay(pg_session):
    session = pg_session
    tenant, run, sources = await seed(session)
    ids = [s.id for s in sources[:2]]
    identity = map_source_identity(
        canonical_url="https://doi.org/10.1234/observed",
        publisher="Verified Publisher",
        publisher_basis={"basis": "adapter_metadata", "evidence_ref": "fixture:publisher"},
    )
    repo = SourceRelationshipRepository(session, tenant)
    assert (
        await repo.link_sources(
            run_id=run, source_ids=ids, observed_identities={id_: identity for id_ in ids}
        )
        == 3
    )
    assert (
        await repo.link_sources(
            run_id=run,
            source_ids=list(reversed(ids)),
            observed_identities={
                id_: map_source_identity(canonical_url="https://other.test") for id_ in ids
            },
        )
        == 0
    )
    records = list(await session.scalars(select(SourceIdentityRecord)))
    assert len(records) == 2
    assert all(row.work_id == "doi:10.1234/observed" for row in records)
    assert all(s.publisher is None and s.source_class == "unknown" for s in sources)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :id, true)"), {"id": str(uuid4())}
    )
    assert list(await session.scalars(select(SourceIdentityRecord))) == []
    with pytest.raises(DBAPIError) as error:
        async with session.begin_nested():
            session.add(
                SourceIdentityRecord(
                    tenant_id=tenant,
                    run_id=run,
                    source_id=sources[2].id,
                    work_id=None,
                    publisher=None,
                    metadata_basis={},
                )
            )
            await session.flush()
    assert error.value.orig.sqlstate == "42501"
