"""Pure checks plus opt-in checks against an already-migrated disposable database.

No migrations or provider calls run here. To run database checks after the lead's
GO, provide MODE_ASSESSMENT_TEST_DATABASE_URL pointing at a loopback database
named mode_assessment_test_* migrated through 0015, with a principal able to
SET ROLE research_app. Never point this suite at the shared application database.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api.db.assessments import MANIFEST_MAX_BYTES, RESULT_MAX_BYTES, ResearchAssessment
from research_api.db.models import Base, ResearchPlan, ResearchRun, Tenant, User
from research_api.repositories.assessments import (
    AssessmentManifestMismatch,
    AssessmentRepository,
    AssessmentResultMismatch,
    _json_object,
    validate_manifest,
)


def manifest():
    return {
        "policy_snapshot": {"mode": "focused", "version": "test-v1"},
        "sources": [
            {
                "source_id": str(uuid.uuid4()),
                "hash": "a" * 64,
                "artifact_ref": "s3://fixture/source",
                "title": "Selected evidence",
                "url": "https://example.test/evidence",
                "selected_context": "Bounded excerpt",
            }
        ],
    }


def migration():
    path = Path(__file__).parents[2] / (
        "src/research_api/db/migrations/versions/0015_mode_assessments.py"
    )
    spec = importlib.util.spec_from_file_location("assessment_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_is_detached_and_rejects_raw_bodies_and_unbounded_context():
    original = manifest()
    copied = validate_manifest(original)
    original["sources"][0]["title"] = "Changed by caller"
    assert copied["sources"][0]["title"] == "Selected evidence"
    for key in ("raw_content", "body", "full_text", "content", "html"):
        with pytest.raises(ValueError, match="source bodies"):
            validate_manifest({"sources": [{key: "private source body"}]})
    with pytest.raises(ValueError, match="8192 characters"):
        validate_manifest({"selected_context": "é" * 8193})
    assert validate_manifest({"selected_context_parts": ["界" * 8000] * 3})
    with pytest.raises(ValueError, match="byte limit"):
        validate_manifest({"selected_context": ["x" * 16384] * 17})


@pytest.mark.parametrize("value", [[], None, {"score": float("nan")}, {"x": object()}])
def test_payloads_must_be_finite_json_objects(value):
    with pytest.raises(ValueError):
        _json_object(value, RESULT_MAX_BYTES)


def test_json_sizes_count_utf8_and_boundaries():
    # jsonb::text for this object has nine overhead bytes.
    assert _json_object({"x": "a" * (MANIFEST_MAX_BYTES - 9)}, MANIFEST_MAX_BYTES)
    with pytest.raises(ValueError, match="byte limit"):
        _json_object({"x": "é" * (MANIFEST_MAX_BYTES // 2)}, MANIFEST_MAX_BYTES)
    with pytest.raises(ValueError, match="byte limit"):
        _json_object({"x": "a" * RESULT_MAX_BYTES}, RESULT_MAX_BYTES)


def test_migration_contract_and_fresh_metadata():
    module = migration()
    assert module.revision == "0015" and module.down_revision == "0014"
    with patch.object(module, "op") as operation:
        module.upgrade()
    sql = "\n".join(call.args[0] for call in operation.execute.call_args_list)
    for fragment in (
        "FORCE ROW LEVEL SECURITY",
        "REFERENCES public.research_plans(tenant_id, run_id, id)",
        "octet_length(manifest::text) <= 262144",
        "octet_length(result::text) <= 524288",
        "to_jsonb(NEW) - 'result'",
        "NEW.result IS DISTINCT FROM OLD.result",
        "GRANT SELECT, INSERT, UPDATE",
        "['anon', 'authenticated', 'research_app']",
        "document->>'version' IN ('1', '2')",
        "octet_length(document::text) <= 524288",
    ):
        assert fragment in sql
    # Every FK in the isolated mapping resolves without changing models.py.
    assert ResearchAssessment.__table__ in Base.metadata.sorted_tables
    constraints = ResearchPlan.__table__.constraints
    assert any(c.name == "uq_research_plans_tenant_run_id" for c in constraints)
    with pytest.raises(RuntimeError, match="provenance"):
        module.downgrade()


async def test_repository_returns_authoritative_rows_and_rejects_replay_mismatch():
    tenant, run, plan, assessment = (uuid.uuid4() for _ in range(4))
    saved = manifest()
    row = SimpleNamespace(
        id=assessment, evidence_key="a" * 64, manifest=saved, result={"accepted": True}
    )
    session = AsyncMock()
    session.scalar.return_value = row
    repo = AssessmentRepository(session, tenant)
    assert await repo.get_or_create(run, plan, "a" * 64, saved) is row
    with pytest.raises(AssessmentManifestMismatch):
        await repo.get_or_create(run, plan, "b" * 64, saved)
    with pytest.raises(AssessmentManifestMismatch):
        await repo.get_or_create(run, plan, "a" * 64, {"policy_snapshot": {"mode": "deep"}})
    assert await repo.complete(assessment, {"accepted": True}) is row
    with pytest.raises(AssessmentResultMismatch):
        await repo.complete(assessment, {"accepted": 1})
    session.scalar.return_value = None
    with pytest.raises(LookupError):
        await repo.complete(assessment, {})
    with pytest.raises(LookupError):
        await repo.get_or_create(run, plan, "key", saved)
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("key", ["", "a" * 65, None])
async def test_invalid_identity_fails_before_sql(key):
    session = AsyncMock()
    with pytest.raises(ValueError, match="evidence_key"):
        await AssessmentRepository(session, uuid.uuid4()).get_or_create(
            uuid.uuid4(), uuid.uuid4(), key, manifest()
        )
    session.execute.assert_not_awaited()


@pytest.fixture
async def db():
    url = os.getenv("MODE_ASSESSMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires explicitly configured disposable database migrated through 0015")
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or not parsed.path.removeprefix("/").startswith("mode_assessment_test_")
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail("assessment database must be disposable and on loopback")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0015"
            )
        yield factory
    finally:
        await engine.dispose()


@asynccontextmanager
async def scoped(factory, tenant):
    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL ROLE research_app"))
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
        )
        yield session


async def seed(factory):
    tenant, user, run, plan = (uuid.uuid4() for _ in range(4))
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
        )
        session.add(Tenant(id=tenant, name="Disposable assessments"))
        await session.flush()
        session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
        await session.flush()
        session.add(
            ResearchRun(
                id=run,
                tenant_id=tenant,
                user_id=user,
                original_question="Assessment test",
                normalized_question="Assessment test",
                thread_id=str(run),
            )
        )
        await session.flush()
        session.add(ResearchPlan(id=plan, tenant_id=tenant, run_id=run, plan_version=1, plan={}))
    return tenant, run, plan


@pytest.mark.integration
async def test_concurrent_creation_completion_and_restart_replay(db):
    tenant, run, plan = await seed(db)
    saved = manifest()

    async def create():
        async with scoped(db, tenant) as session:
            return (
                await AssessmentRepository(session, tenant).get_or_create(
                    run, plan, "a" * 64, saved
                )
            ).id

    ids = await asyncio.wait_for(asyncio.gather(*(create() for _ in range(6))), timeout=15)
    assert len(set(ids)) == 1

    async def complete(result):
        async with scoped(db, tenant) as session:
            return (await AssessmentRepository(session, tenant).complete(ids[0], result)).result

    results = await asyncio.wait_for(
        asyncio.gather(*(complete({"verdict": "supported"}) for _ in range(6))), timeout=15
    )
    assert results == [{"verdict": "supported"}] * 6
    assert await create() == ids[0]
    with pytest.raises(AssessmentResultMismatch):
        await complete({"verdict": "different"})
    async with scoped(db, tenant) as session:
        repo = AssessmentRepository(session, tenant)
        with pytest.raises(AssessmentManifestMismatch):
            await repo.get_or_create(run, plan, "a" * 64, {"policy_snapshot": {"mode": "deep"}})


@pytest.mark.integration
async def test_competing_results_choose_one_authoritative_winner(db):
    tenant, run, plan = await seed(db)
    async with scoped(db, tenant) as session:
        row = await AssessmentRepository(session, tenant).get_or_create(
            run, plan, "race", manifest()
        )
        identity = row.id

    async def finish(index):
        async with scoped(db, tenant) as session:
            return await AssessmentRepository(session, tenant).complete(identity, {"winner": index})

    results = await asyncio.wait_for(
        asyncio.gather(*(finish(i) for i in range(4)), return_exceptions=True), timeout=15
    )
    assert sum(isinstance(row, ResearchAssessment) for row in results) == 1
    assert sum(isinstance(row, AssessmentResultMismatch) for row in results) == 3


@pytest.mark.integration
async def test_concurrent_evidence_keys_cannot_fork_a_plan(db):
    tenant, run, plan = await seed(db)
    saved = manifest()

    async def create(index):
        async with scoped(db, tenant) as session:
            return await AssessmentRepository(session, tenant).get_or_create(
                run, plan, str(index), saved
            )

    results = await asyncio.wait_for(
        asyncio.gather(*(create(i) for i in range(4)), return_exceptions=True), timeout=15
    )
    assert sum(isinstance(row, ResearchAssessment) for row in results) == 1
    assert sum(isinstance(row, AssessmentManifestMismatch) for row in results) == 3


@pytest.mark.integration
async def test_rls_and_composite_fk_reject_cross_tenant_and_cross_run(db):
    tenant, run, plan = await seed(db)
    other_tenant, other_run, other_plan = await seed(db)
    async with scoped(db, tenant) as session:
        row = await AssessmentRepository(session, tenant).get_or_create(
            run, plan, "scope", manifest()
        )
        identity = row.id
    async with scoped(db, other_tenant) as session:
        assert (
            await session.scalar(
                select(ResearchAssessment).where(ResearchAssessment.id == identity)
            )
            is None
        )
        with pytest.raises(LookupError):
            await AssessmentRepository(session, other_tenant).complete(identity, {})
    for scoped_tenant, run_id, plan_id in (
        (tenant, run, other_plan),
        (tenant, other_run, plan),
        (other_tenant, run, plan),
    ):
        with pytest.raises(IntegrityError):
            async with scoped(db, scoped_tenant) as session:
                await AssessmentRepository(session, scoped_tenant).get_or_create(
                    run_id, plan_id, "invalid-scope", manifest()
                )
    # A same-tenant plan from a different run must also fail the three-column FK.
    async with scoped(db, tenant) as session:
        user = await session.scalar(select(User.id))
        second_run = ResearchRun(
            tenant_id=tenant,
            user_id=user,
            original_question="Second",
            normalized_question="Second",
            thread_id=str(uuid.uuid4()),
        )
        session.add(second_run)
        await session.flush()
        second_run_id = second_run.id
    with pytest.raises(IntegrityError):
        async with scoped(db, tenant) as session:
            await AssessmentRepository(session, tenant).get_or_create(
                second_run_id, plan, "wrong-run", manifest()
            )


@pytest.mark.integration
async def test_sql_bypass_cannot_mutate_manifest_identity_or_completed_result(db):
    tenant, run, plan = await seed(db)
    async with scoped(db, tenant) as session:
        repo = AssessmentRepository(session, tenant)
        row = await repo.get_or_create(run, plan, "immutable", manifest())
        identity = row.id
        await repo.complete(identity, {"ok": True})
    assignments = (
        "manifest = '{}'::jsonb",
        "evidence_key = 'changed'",
        "id = gen_random_uuid()",
        "tenant_id = gen_random_uuid()",
        "run_id = gen_random_uuid()",
        "plan_id = gen_random_uuid()",
        "created_at = now() + interval '1 second'",
        "result = NULL",
        "result = CAST(:changed_result AS jsonb)",
    )
    for assignment in assignments:
        with pytest.raises(DBAPIError):
            async with scoped(db, tenant) as session:
                await session.execute(
                    # Assignment comes only from the fixed adversarial cases above.
                    text(f"UPDATE research_assessments SET {assignment} WHERE id = :id"),  # noqa: S608
                    {"id": identity, "changed_result": '{"ok": false}'},
                )
    # Exact JSONB replay is accepted by the database trigger, including key order.
    async with scoped(db, tenant) as session:
        await session.execute(
            text("UPDATE research_assessments SET result = CAST(:result AS jsonb) WHERE id = :id"),
            {"id": identity, "result": '{"ok": true}'},
        )
    with pytest.raises(DBAPIError):
        async with scoped(db, tenant) as session:
            await session.execute(
                text("DELETE FROM research_assessments WHERE id=:id"), {"id": identity}
            )


@pytest.mark.integration
async def test_sql_checks_and_privileges(db):
    tenant, run, plan = await seed(db)
    for field, value in (("manifest", {"x": "a" * MANIFEST_MAX_BYTES}), ("manifest", [])):
        with pytest.raises(IntegrityError):
            async with scoped(db, tenant) as session:
                session.add(
                    ResearchAssessment(
                        tenant_id=tenant,
                        run_id=run,
                        plan_id=plan,
                        evidence_key=str(uuid.uuid4()),
                        **{field: value},
                    )
                )
                await session.flush()
    async with scoped(db, tenant) as session:
        row = await AssessmentRepository(session, tenant).get_or_create(
            run, plan, "size", manifest()
        )
        identity = row.id
    for result_sql in ("'[]'::jsonb", "jsonb_build_object('x', repeat('a', 524288))"):
        with pytest.raises(IntegrityError):
            async with scoped(db, tenant) as session:
                await session.execute(
                    # Expression comes only from the fixed size/type cases above.
                    text(f"UPDATE research_assessments SET result={result_sql} WHERE id=:id"),  # noqa: S608
                    {"id": identity},
                )
    async with db() as session:
        flags = (
            await session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid='research_assessments'::regclass"
                )
            )
        ).one()
        assert flags.relrowsecurity and flags.relforcerowsecurity
        for role in ("anon", "authenticated", "research_app"):
            if not await session.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}
            ):
                continue
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                granted = await session.scalar(
                    text("SELECT has_table_privilege(:role, 'research_assessments', :privilege)"),
                    {"role": role, "privilege": privilege},
                )
                assert granted == (role == "research_app" and privilege != "DELETE")
