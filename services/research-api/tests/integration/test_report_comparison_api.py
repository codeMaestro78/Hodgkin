"""Owner authorization and immutable-version comparison on loopback PostgreSQL."""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import delete, insert, null, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import comparison_api, sharing_exports_api
from research_api.auth import Caller
from research_api.db.models import Report, ResearchRun, Source, Tenant, User
from research_api.main import app
from research_api.report_document import build_report_document

pytestmark = pytest.mark.integration


def _report_hash(markdown: str, document: dict | None) -> str:
    canonical = json.dumps(
        {"markdown": markdown, "document": document},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@pytest.fixture
async def comparisons(monkeypatch):
    tenant, foreign_tenant, owner, other, outsider = [uuid.uuid4() for _ in range(5)]
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    report_ids = []
    run_ids = []
    source_ids = []
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Tenant(id=tenant, name="Comparison fixture"),
                Tenant(id=foreign_tenant, name="Other tenant"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                User(id=user, tenant_id=t, external_subject=str(user))
                for t, user in [(tenant, owner), (tenant, other), (foreign_tenant, outsider)]
            ]
        )
        await session.flush()
        # Two exact versions, a legacy version, another user's report, a foreign
        # tenant's report, and an unpublished report.
        for i, (t, user, version, published, legacy) in enumerate(
            [
                (tenant, owner, 1, True, False),
                (tenant, owner, 2, True, False),
                (tenant, owner, 3, True, True),
                (tenant, other, 1, True, False),
                (foreign_tenant, outsider, 1, True, False),
                (tenant, owner, 4, False, False),
            ]
        ):
            run_id = run_ids[0] if i in (1, 2, 5) else uuid.uuid4()
            if run_id not in run_ids:
                run_ids.append(run_id)
                session.add(
                    ResearchRun(
                        id=run_id,
                        tenant_id=t,
                        user_id=user,
                        status="completed",
                        original_question="Compare reports",
                        normalized_question="Compare reports",
                        thread_id=str(run_id),
                    )
                )
                await session.flush()
            source_id, claim_id, report_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            report_ids.append(report_id)
            source_ids.append(source_id)
            session.add(
                Source(
                    id=source_id,
                    tenant_id=t,
                    run_id=run_id,
                    canonical_url=f"https://example.test/{i}",
                    title="Evidence",
                    provider="tavily",
                    source_class="primary",
                    retrieved_at=datetime.now(UTC),
                    content_hash=str(i) * 64,
                    artifact_ref="fixture",
                )
            )
            document = (
                None
                if legacy
                else build_report_document(
                    question="Compare reports",
                    max_search_calls=6,
                    requirements=[],
                    findings=[
                        {
                            "id": str(claim_id),
                            "text": "Earlier finding" if i == 0 else "Later finding",
                            "section": "comparison",
                            "citationIds": [str(uuid.uuid4())],
                            "sourceIds": [str(source_id)],
                            "subQuestionId": str(run_id),
                            "requirementIndices": [],
                        }
                    ],
                    questions=[{"id": str(run_id), "question": "Find evidence"}],
                    excluded=0,
                )
            )
            markdown = f"Report {i}"
            session.add(
                Report(
                    id=report_id,
                    tenant_id=t,
                    run_id=run_id,
                    version=version,
                    markdown=markdown,
                    document=null() if legacy else document,
                    published=published,
                    published_at=datetime.now(UTC) if published else None,
                    content_hash=(
                        _report_hash(markdown, None if legacy else document) if published else None
                    ),
                )
            )
    caller = AsyncMock(return_value=Caller(tenant_id=tenant, user_id=owner))
    monkeypatch.setattr(comparison_api, "authenticated_caller", caller)
    monkeypatch.setattr(sharing_exports_api, "authenticated_caller", caller)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, report_ids, caller
    finally:
        async with session_factory() as session, session.begin():
            from research_api.db.models import ReportExport, ReportShare

            await session.execute(delete(ReportShare).where(ReportShare.report_id.in_(report_ids)))
            await session.execute(
                delete(ReportExport).where(ReportExport.report_id.in_(report_ids))
            )
            await session.execute(delete(Report).where(Report.id.in_(report_ids)))
            await session.execute(delete(Source).where(Source.id.in_(source_ids)))
            await session.execute(delete(ResearchRun).where(ResearchRun.id.in_(run_ids)))
            await session.execute(delete(User).where(User.id.in_([owner, other, outsider])))
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant, foreign_tenant])))
        await engine.dispose()


async def test_compare_selected_versions_and_legacy_without_mutation(comparisons):
    client, ids, _ = comparisons
    response = await client.post(
        "/research/reports/compare",
        json={"leftReportId": str(ids[0]), "rightReportId": str(ids[1])},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["left"]["version"] == 1 and body["right"]["version"] == 2
    assert [item["text"] for item in body["removed"]] == ["Earlier finding"]
    assert [item["text"] for item in body["added"]] == ["Later finding"]
    response = await client.post(
        "/research/reports/compare",
        json={"leftReportId": str(ids[2]), "rightReportId": str(ids[1])},
    )
    assert response.status_code == 200
    assert response.json()["left"]["quality"] == "not_assessed"
    assert not response.json()["findingsAvailable"]
    assert not response.json()["added"]


@pytest.mark.parametrize("index", [3, 4, 5])
async def test_denies_other_owner_foreign_tenant_and_unpublished(comparisons, index):
    client, ids, _ = comparisons
    response = await client.post(
        "/research/reports/compare",
        json={"leftReportId": str(ids[0]), "rightReportId": str(ids[index])},
    )
    assert response.status_code == 404
    assert str(ids[0]) not in response.text


async def test_listing_is_owner_scoped_and_keyset_paginated(comparisons):
    client, ids, _ = comparisons
    first = await client.get("/research/reports?limit=2")
    assert first.status_code == 200, first.text
    second = await client.get(f"/research/reports?limit=2&after={first.json()['nextCursor']}")
    listed = [r["id"] for page in (first, second) for r in page.json()["reports"]]
    assert set(listed) == set(map(str, ids[:3]))
    assert len(listed) == 3
    assert second.json()["nextCursor"] is None
    invalid = await client.post(
        "/research/reports/compare",
        json={"leftReportId": "bad", "rightReportId": str(ids[0]), "tenantId": str(uuid.uuid4())},
    )
    assert invalid.status_code == 422


async def test_identical_report_ids_are_rejected(comparisons):
    client, ids, _ = comparisons
    response = await client.post(
        "/research/reports/compare",
        json={"leftReportId": str(ids[0]), "rightReportId": str(ids[0])},
    )
    assert response.status_code == 422
    assert "different report versions" in response.text


async def test_share_is_token_only_and_revocation_is_immediate(comparisons):
    client, ids, _ = comparisons
    created = await client.post(f"/research/reports/{ids[0]}/shares", json={"expiresInHours": 24})
    assert created.status_code == 200, created.text
    payload = created.json()
    token = payload["sharePath"].split("share=", 1)[1]
    assert token not in created.text.replace(payload["sharePath"], "")
    public = await client.get("/s", headers={"Authorization": f"ResearchShare {token}"})
    assert public.status_code == 200, public.text
    assert public.json()["version"] == 1
    assert public.headers["cache-control"] == "private, no-store"
    revoked = await client.post(
        f"/research/reports/{ids[0]}/shares/{payload['id']}/revoke", json={}
    )
    assert revoked.status_code == 200, revoked.text
    inaccessible = await client.get("/s", headers={"Authorization": f"ResearchShare {token}"})
    assert inaccessible.status_code == 404


async def test_export_pins_report_and_download_is_authenticated(comparisons):
    client, ids, caller = comparisons
    created = await client.post(f"/research/reports/{ids[0]}/exports", json={"format": "markdown"})
    assert created.status_code == 200, created.text
    export = created.json()
    assert export["reportId"] == str(ids[0])
    downloaded = await client.get(export["downloadPath"])
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.text == "Report 0"
    assert downloaded.headers["cache-control"] == "private, no-store"
    caller.return_value = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    unauthorized = await client.get(export["downloadPath"])
    assert unauthorized.status_code == 404


async def test_database_rejects_mutation_of_published_report(comparisons):
    _, ids, _ = comparisons
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="published report versions are immutable"):
                await connection.execute(
                    Report.__table__.update().where(Report.id == ids[0]).values(markdown="tampered")
                )
                await connection.commit()
            await connection.rollback()
    finally:
        await engine.dispose()


async def test_legacy_writer_insert_remains_compatible_and_immutable(comparisons):
    _, ids, _ = comparisons
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with engine.connect() as connection:
            fixture = (
                await connection.execute(
                    select(Report.tenant_id, Report.run_id).where(Report.id == ids[0])
                )
            ).one()
        legacy_id = uuid.uuid4()
        ids.append(legacy_id)
        async with engine.begin() as connection:
            await connection.execute(
                insert(Report).values(
                    id=legacy_id,
                    tenant_id=fixture.tenant_id,
                    run_id=fixture.run_id,
                    version=99,
                    markdown="legacy-compatible publication",
                    published=True,
                )
            )
        with pytest.raises(DBAPIError, match="published report versions are immutable"):
            async with engine.begin() as connection:
                await connection.execute(
                    Report.__table__.update()
                    .where(Report.id == legacy_id)
                    .values(markdown="must stay unchanged")
                )
    finally:
        await engine.dispose()
