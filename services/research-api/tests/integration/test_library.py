"""Exercise migrations, forced RLS and HTTP contracts in disposable local databases.

No application database migrations or paid/provider boundaries are invoked. The
root conftest rejects non-loopback URLs before these fixtures can run.
"""

import asyncio
import importlib
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import library_api
from research_api.auth import Caller
from research_api.db import session as db_session
from research_api.db.models import Report, ResearchRun, Source, Tenant, User

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=["fresh", "upgrade"])
def database(request):
    admin_url = make_url(os.environ["TEST_DATABASE_ADMIN_URL"])
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = "research_library_test_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    owner_url = admin_url.set(database=name)
    engine = create_engine(owner_url)
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                for version in (
                    "0001_authoritative_core",
                    "0002_run_idempotency",
                    "0003_supabase_accounts",
                    "0004_auth_function_grants",
                    "0005_evidence_reliability",
                    "0006_extraction_admission",
                    "0007_durable_runtime",
                    "0008_structured_reports",
                ):
                    importlib.import_module(
                        f"research_api.db.migrations.versions.{version}"
                    ).upgrade()
                if request.param == "upgrade":
                    # 0001 uses current metadata. Remove just our new tables to
                    # represent an existing 0008 installation before upgrading.
                    connection.exec_driver_sql("DROP TABLE library_items")
                    connection.exec_driver_sql("DROP TABLE projects")
                importlib.import_module(
                    "research_api.db.migrations.versions.0009_library"
                ).upgrade()
        yield owner_url, make_url(os.environ["DATABASE_URL"]).set(database=name)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()


@pytest.fixture
async def fixture(database, monkeypatch):
    owner_url, runtime_url = database
    owner_engine = create_async_engine(owner_url)
    runtime_engine = create_async_engine(runtime_url)
    statements = []

    @event.listens_for(runtime_engine.sync_engine, "before_cursor_execute")
    def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    factory = async_sessionmaker(runtime_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "session_factory", factory)
    tenant, other_tenant, user, colleague, outsider = (uuid.uuid4() for _ in range(5))
    run, other_run, foreign_run = (uuid.uuid4() for _ in range(3))
    report, report2, draft, source, other_source = (uuid.uuid4() for _ in range(5))
    try:
        async with async_sessionmaker(owner_engine)() as session, session.begin():
            session.add_all(
                [
                    Tenant(id=tenant, name="library fixture"),
                    Tenant(id=other_tenant, name="foreign fixture"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    User(id=u, tenant_id=t, external_subject=str(u))
                    for t, u in [(tenant, user), (tenant, colleague), (other_tenant, outsider)]
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ResearchRun(
                        id=r,
                        tenant_id=t,
                        user_id=u,
                        thread_id=str(r),
                        original_question="Original 100%_question",
                        normalized_question="normalized",
                    )
                    for r, t, u in [
                        (run, tenant, user),
                        (other_run, tenant, colleague),
                        (foreign_run, other_tenant, outsider),
                    ]
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Report(
                        id=r,
                        tenant_id=tenant,
                        run_id=run,
                        version=v,
                        markdown="fixture",
                        published=p,
                        published_at=datetime.now(UTC) if p else None,
                        content_hash="0" * 64 if p else None,
                    )
                    for r, v, p in [(report, 1, True), (report2, 2, True), (draft, 3, False)]
                ]
            )
            session.add_all(
                [
                    Source(
                        id=s,
                        tenant_id=tenant,
                        run_id=r,
                        title="Source Alpha",
                        canonical_url="https://example.test/source",
                        provider="internal",
                        source_class="primary",
                        retrieved_at=datetime.now(UTC),
                        content_hash="a" * 64,
                        artifact_ref="fixture",
                    )
                    for s, r in [(source, run), (other_source, other_run)]
                ]
            )
        caller = Caller(tenant_id=tenant, user_id=user)
        auth = AsyncMock(return_value=caller)
        monkeypatch.setattr(library_api, "_caller", auth)
        app = FastAPI()
        app.include_router(library_api.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield {
                "client": client,
                "caller": caller,
                "auth": auth,
                "owner": owner_engine,
                "factory": factory,
                "report": report,
                "report2": report2,
                "draft": draft,
                "source": source,
                "other_source": other_source,
                "run": run,
                "colleague": Caller(tenant_id=tenant, user_id=colleague),
                "outsider": Caller(tenant_id=other_tenant, user_id=outsider),
                "statements": statements,
            }
    finally:
        await runtime_engine.dispose()
        await owner_engine.dispose()


async def test_save_organize_search_pagination_remove(fixture):
    f, client = fixture, fixture["client"]
    project = await client.post("/research/projects", json={"name": "  Folder  "})
    assert project.status_code == 200, project.text
    project = project.json()
    assert project["name"] == "Folder"
    assert (await client.get("/research/projects")).json()["projects"] == [project]
    saved = await client.post("/research/library/items", json={"reportId": str(f["report"])})
    assert saved.status_code == 200, saved.text
    item = saved.json()
    assert item["title"] == "Original 100%_question"
    assert item["reportVersion"] == 1 and item["sourceId"] is None and item["url"] is None
    organized = await client.post(
        f"/research/library/items/{item['id']}/organize",
        json={
            "projectId": project["id"],
            "tags": ["keep"],
            "notes": "Literal 30%_\\ marker",
        },
    )
    assert organized.status_code == 200, organized.text
    duplicate = await client.post("/research/library/items", json={"reportId": str(f["report"])})
    assert duplicate.json() == organized.json()
    second = await client.post("/research/library/items", json={"reportId": str(f["report2"])})
    assert second.json()["reportVersion"] == 2 and second.json()["id"] != item["id"]
    source = await client.post("/research/library/items", json={"sourceId": str(f["source"])})
    assert source.json()["title"] == "Source Alpha" and source.json()["kind"] == "source"
    assert source.json()["runId"] == str(f["run"])
    assert source.json()["url"] == "https://example.test/source"
    assert source.json()["reportVersion"] is None
    f["statements"].clear()
    assert (await client.get("/research/library/items")).status_code == 200
    reads = [sql for sql in f["statements"] if "FROM library_items" in sql]
    assert len(reads) == 1 and "JOIN sources" in reads[0] and "JOIN reports" in reads[0]
    for filters in [
        {"query": "literal 30%_\\"},
        {"tag": "keep"},
        {"projectId": project["id"], "kind": "report"},
    ]:
        found = (await client.get("/research/library/items", params=filters)).json()
        assert [x["id"] for x in found["items"]] == [item["id"]]
    assert (await client.get("/research/library/items", params={"query": "30x"})).json()[
        "items"
    ] == []
    ids, cursor = [], None
    while True:
        page = (
            await client.get(
                "/research/library/items",
                params={"limit": 1, **({"after": cursor} if cursor else {})},
            )
        ).json()
        ids.extend(x["id"] for x in page["items"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
    assert len(ids) == len(set(ids)) == 3 and ids == sorted(ids)
    removed = await client.post(f"/research/library/items/{item['id']}/remove")
    assert removed.json() == {"id": item["id"]}
    assert (await client.post(f"/research/library/items/{item['id']}/remove")).status_code == 404


async def test_validation_and_user_tenant_ownership(fixture):
    f, client = fixture, fixture["client"]
    report = str(f["report"])
    assert (
        await client.post(
            "/research/library/items",
            json={
                "reportId": report,
                "projectId": None,
            },
        )
    ).status_code == 422
    for payload in [
        {},
        {"reportId": report, "sourceId": str(f["source"])},
        {"reportId": "bad"},
        {"reportId": report, "tags": ["x"] * 11},
        {"reportId": report, "tags": ["x" * 41]},
        {"reportId": report, "notes": "x" * 2001},
    ]:
        assert (await client.post("/research/library/items", json=payload)).status_code == 422
    for name in ["   ", "x" * 101]:
        assert (await client.post("/research/projects", json={"name": name})).status_code == 422
    for params in [
        {"limit": 0},
        {"limit": 101},
        {"after": "bad"},
        {"query": "x" * 201},
        {"kind": "bad"},
        {"tag": "x" * 41},
    ]:
        assert (await client.get("/research/library/items", params=params)).status_code == 422
    for payload in [{"reportId": str(f["draft"])}, {"sourceId": str(f["other_source"])}]:
        assert (await client.post("/research/library/items", json=payload)).status_code == 404
    project = (await client.post("/research/projects", json={"name": "Private"})).json()
    item = (await client.post("/research/library/items", json={"reportId": report})).json()
    for caller in [f["colleague"], f["outsider"]]:
        f["auth"].return_value = caller
        assert (await client.get("/research/projects")).json() == {"projects": []}
        assert (await client.get("/research/library/items")).json()["items"] == []
        assert (
            await client.post("/research/library/items", json={"reportId": report})
        ).status_code == 404
        assert (
            await client.post("/research/library/items", json={"sourceId": str(f["source"])})
        ).status_code == 404
        assert (
            await client.post(f"/research/library/items/{item['id']}/remove")
        ).status_code == 404
        assert (
            await client.post(
                f"/research/library/items/{item['id']}/organize",
                json={"projectId": None, "tags": [], "notes": ""},
            )
        ).status_code == 404
        assert (
            await client.get("/research/library/items", params={"projectId": project["id"]})
        ).status_code == 404
    # A same-tenant colleague's project cannot be assigned by the original owner.
    f["auth"].return_value = f["colleague"]
    foreign_project = (await client.post("/research/projects", json={"name": "Other"})).json()
    f["auth"].return_value = f["caller"]
    assert (
        await client.post(
            f"/research/library/items/{item['id']}/organize",
            json={"projectId": foreign_project["id"], "tags": [], "notes": ""},
        )
    ).status_code == 404


async def test_concurrent_save_and_database_guards(fixture):
    f, client = fixture, fixture["client"]
    results = await asyncio.gather(
        *(
            client.post(
                "/research/library/items",
                json={
                    "sourceId": str(f["source"]),
                    "tags": ["concurrent"],
                },
            )
            for _ in range(6)
        )
    )
    assert all(response.status_code == 200 for response in results)
    ids = {response.json()["id"] for response in results}
    assert len(ids) == 1
    item_id = next(iter(ids))
    async with f["factory"]() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :id, true)"),
            {"id": str(f["caller"].tenant_id)},
        )
        assert (await session.execute(text("SELECT id FROM library_items"))).all() == []
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(f["colleague"].user_id)}
        )
        assert (await session.execute(text("SELECT id FROM library_items"))).all() == []
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(f["caller"].user_id)}
        )
        for statement in [
            "UPDATE library_items SET id=gen_random_uuid()",
            "UPDATE library_items SET source_id=gen_random_uuid()",
            "UPDATE library_items SET notes=repeat('x',2001)",
            "UPDATE library_items SET tags='[1]'::jsonb",
            "UPDATE library_items SET tags=jsonb_build_array(repeat('x',41))",
            "UPDATE library_items SET project_id=gen_random_uuid()",
        ]:
            async with session.begin_nested() as savepoint:
                with pytest.raises(DBAPIError):
                    await session.execute(text(statement))
                await savepoint.rollback()
        # User ownership is also enforced by RLS for direct target inserts.
        async with session.begin_nested() as savepoint:
            with pytest.raises(DBAPIError):
                await session.execute(
                    text("""INSERT INTO library_items
                    (id,tenant_id,user_id,source_id,tags,notes)
                    VALUES (gen_random_uuid(),:tenant,:user,:source,'[]','')"""),
                    {
                        "tenant": f["caller"].tenant_id,
                        "user": f["caller"].user_id,
                        "source": f["other_source"],
                    },
                )
            await savepoint.rollback()
        assert (
            await session.scalar(
                text("SELECT count(*) FROM library_items WHERE id=:id"), {"id": item_id}
            )
            == 1
        )
    async with f["owner"].connect() as connection:
        rows = (
            await connection.execute(
                text("""SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class WHERE relname IN ('projects','library_items')""")
            )
        ).all()
        assert len(rows) == 2 and all(row[1] and row[2] for row in rows)


async def test_composite_foreign_keys_xor_uniqueness_and_browser_grants(fixture):
    f, client = fixture, fixture["client"]
    f["auth"].return_value = f["colleague"]
    project = (await client.post("/research/projects", json={"name": "Colleague folder"})).json()
    f["auth"].return_value = f["caller"]
    saved = await client.post("/research/library/items", json={"reportId": str(f["report"])})
    assert saved.status_code == 200
    async with f["owner"].begin() as connection:
        # BYPASSRLS owner isolates FK/check/unique enforcement from RLS rejection.
        base = {
            "tenant": f["caller"].tenant_id,
            "user": f["caller"].user_id,
            "report": f["report2"],
            "source": None,
            "project": None,
        }
        invalid = [
            {"project": uuid.UUID(project["id"])},  # valid folder, wrong user
            {"report": None},  # neither target
            {"source": f["source"]},  # both targets
            {"tenant": f["outsider"].tenant_id, "user": f["outsider"].user_id},
            {"report": f["report"]},  # duplicate exact report save
        ]
        for changes in invalid:
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""INSERT INTO library_items
                        (id,tenant_id,user_id,report_id,source_id,project_id,tags,notes)
                        VALUES (gen_random_uuid(),:tenant,:user,:report,:source,:project,'[]','')
                    """),
                        base | changes,
                    )
        roles = (
            (
                await connection.execute(
                    text("""SELECT rolname FROM pg_roles
            WHERE rolname IN ('anon','authenticated')""")
                )
            )
            .scalars()
            .all()
        )
        for role in roles:
            for table in ("projects", "library_items"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not await connection.scalar(
                        text("SELECT has_table_privilege(:role,:table,:privilege)"),
                        {"role": role, "table": table, "privilege": privilege},
                    )
