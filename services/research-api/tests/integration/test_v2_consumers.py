"""Immutable V1/V2 consumer integration on loopback PostgreSQL; no paid calls.

Reuse the existing owner/RLS/share/export fixture and canonical hash convention.
Only test-owned report UUIDs are added to its cleanup list. Graph execution and
criterion assessment are covered separately; these tests exercise publication
and actual HTTP readers over validated, persisted report snapshots.
"""

import hashlib
import os
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_report_comparison_api import _report_hash
from test_report_comparison_api import comparisons as comparisons

from research_api import api
from research_api.db.models import Report, ReportExport, ReportShare, ResearchRun, Source
from research_api.graph import builder
from research_api.mode_composer import compose_report
from research_api.report_document import validate_report_document

pytestmark = pytest.mark.integration


@pytest.fixture
async def v2_consumers(comparisons, monkeypatch):
    client, report_ids, caller = comparisons
    for name in ("DATABASE_URL", "TEST_DATABASE_ADMIN_URL"):
        assert urlsplit(os.environ[name]).hostname in {"localhost", "127.0.0.1", "::1"}
    paid = AsyncMock(side_effect=AssertionError("Consumer reads must never call a paid model"))
    monkeypatch.setattr(builder, "_model_response", paid)
    monkeypatch.setattr(api, "_caller", caller)
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def snapshot(report_id):
        async with sessions() as session:
            report = await session.get(Report, report_id)
            return {
                "id": report.id,
                "run_id": report.run_id,
                "tenant_id": report.tenant_id,
                "version": report.version,
                "markdown": report.markdown,
                "document": deepcopy(report.document),
                "published": report.published,
                "published_at": report.published_at,
                "content_hash": report.content_hash,
            }

    legacy = await snapshot(report_ids[0])

    async def publish(version, *, source_index=1):
        original = await snapshot(report_ids[source_index])
        document = deepcopy(original["document"])
        dimension_id, criterion_id = str(uuid.uuid4()), str(uuid.uuid4())
        document.update(
            version=2,
            assessmentVersion="coverage-ledger-v1",
            runId=str(original["run_id"]),
            planId=str(uuid.uuid4()),
            assessmentId=str(uuid.uuid4()),
            modePolicyVersion="research-mode-policy-v1",
            dimensions=[
                {
                    "id": dimension_id,
                    "label": "Compare available evidence",
                    "requirementIds": ["question"],
                    "status": "evidence_found",
                    "claimIds": [document["findings"][0]["id"]],
                    "reason": "Collection provenance alone cannot certify coverage.",
                    "basis": "not_assessed",
                    "criteria": [
                        {
                            "id": criterion_id,
                            "outcome": "unknown",
                            "claimIds": [],
                            "basis": "not_assessed",
                            "reason": "No criterion review has established this outcome.",
                        }
                    ],
                }
            ],
            requirementOutcomes=[
                {
                    "id": "question",
                    "outcome": "not_assessed",
                    "dimensionIds": [dimension_id],
                    "claimIds": [],
                    "reason": "Requirement satisfaction has not been assessed.",
                }
            ],
            comparisons=[],
            sourceIndependence={
                "status": "unknown",
                "reason": "Content relationships do not establish independence.",
            },
        )
        document["findings"][0]["text"] = f"Selected V2 finding for report version {version}"
        document = validate_report_document(document)
        source_ids = [uuid.UUID(key) for key in document["findings"][0]["sourceIds"]]
        async with sessions() as session, session.begin():
            sources = list(await session.scalars(select(Source).where(Source.id.in_(source_ids))))
            markdown = compose_report(
                document,
                sources=[(str(row.id), row.title, row.canonical_url) for row in sources],
            )
            report_id = uuid.uuid4()
            report_ids.append(report_id)  # Parent fixture owns scoped cleanup, even on failure.
            report = Report(
                id=report_id,
                tenant_id=original["tenant_id"],
                run_id=original["run_id"],
                version=version,
                markdown=markdown,
                document=document,
                published=False,
            )
            session.add(report)
            await session.flush()
            assert report.content_hash is None and report.published_at is None
            report.content_hash = _report_hash(markdown, document)
            report.published_at = datetime.now(UTC)
            report.published = True
            run = await session.get(ResearchRun, original["run_id"])
            run.report_id = report_id
            await session.flush()
        return await snapshot(report_id)

    try:
        selected = await publish(5)
        yield SimpleNamespace(
            client=client,
            sessions=sessions,
            snapshot=snapshot,
            publish=publish,
            legacy=legacy,
            selected=selected,
            ids=report_ids,
            caller=caller,
        )
    finally:
        paid.assert_not_awaited()
        await engine.dispose()


async def test_v2_publication_hash_covers_complete_document_and_survives_readback(v2_consumers):
    harness = v2_consumers
    report = harness.selected
    assert report["published"] and report["published_at"] is not None
    assert report["document"]["version"] == 2
    assert validate_report_document(report["document"]) == report["document"]
    assert report["content_hash"] == _report_hash(report["markdown"], report["document"])
    changed = deepcopy(report["document"])
    changed["assessmentId"] = str(uuid.uuid4())
    assert _report_hash(report["markdown"], changed) != report["content_hash"]
    assert await harness.snapshot(report["id"]) == report


@pytest.mark.parametrize("field", ["document", "markdown", "content_hash", "published"])
async def test_database_freezes_v2_document_markdown_hash_and_publication(v2_consumers, field):
    harness = v2_consumers
    value = {
        "document": {**harness.selected["document"], "assessmentId": str(uuid.uuid4())},
        "markdown": "must not replace this publication",
        "content_hash": "0" * 64,
        "published": False,
    }[field]
    async with harness.sessions() as session:
        with pytest.raises(DBAPIError, match="published report versions are immutable"):
            await session.execute(
                Report.__table__.update()
                .where(Report.id == harness.selected["id"])
                .values(**{field: value})
            )
            await session.commit()
        await session.rollback()
    assert await harness.snapshot(harness.selected["id"]) == harness.selected


@pytest.mark.parametrize("left_kind", ["v1", "v2"])
async def test_compare_pins_v1_and_v2_versions_after_newer_publication(v2_consumers, left_kind):
    harness = v2_consumers
    left = harness.legacy if left_kind == "v1" else harness.selected
    newer = await harness.publish(6, source_index=0)
    response = await harness.client.post(
        "/research/reports/compare",
        json={"leftReportId": str(left["id"]), "rightReportId": str(newer["id"])},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["left"]["id"] == str(left["id"])
    assert result["left"]["version"] == left["version"]
    assert result["right"]["version"] == 6
    assert result["findingsAvailable"] is True
    assert [row["text"] for row in result["removed"]] == [left["document"]["findings"][0]["text"]]
    assert [row["text"] for row in result["added"]] == [newer["document"]["findings"][0]["text"]]
    assert result["sources"]["left"] == result["sources"]["right"] == 1
    assert await harness.snapshot(left["id"]) == left
    assert await harness.snapshot(newer["id"]) == newer


async def test_compare_markdown_legacy_and_v2_does_not_invent_findings(v2_consumers):
    harness = v2_consumers
    response = await harness.client.post(
        "/research/reports/compare",
        json={"leftReportId": str(harness.ids[2]), "rightReportId": str(harness.selected["id"])},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["left"]["quality"] == "not_assessed"
    assert result["right"]["quality"] == "partial"
    assert result["findingsAvailable"] is False
    assert result["added"] == result["removed"] == result["retained"] == []


async def test_v1_v2_comparison_and_listing_remain_exact_after_new_version(v2_consumers):
    harness = v2_consumers
    pair = {
        "leftReportId": str(harness.legacy["id"]),
        "rightReportId": str(harness.selected["id"]),
    }
    before = await harness.client.post("/research/reports/compare", json=pair)
    assert before.status_code == 200, before.text
    newer = await harness.publish(6, source_index=0)
    after = await harness.client.post("/research/reports/compare", json=pair)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
    assert after.json()["right"]["version"] == 5  # Report version, not document format 2.
    listing = await harness.client.get("/research/reports")
    assert listing.status_code == 200, listing.text
    by_id = {row["id"]: row for row in listing.json()["reports"]}
    for report in (harness.legacy, harness.selected, newer):
        metadata = by_id[str(report["id"])]
        assert metadata["structured"] is True
        assert metadata["quality"] == "partial"
        assert metadata["version"] == report["version"]
    assert by_id[str(harness.ids[2])]["quality"] == "not_assessed"
    assert by_id[str(harness.ids[2])]["structured"] is False
    assert await harness.snapshot(harness.legacy["id"]) == harness.legacy
    assert await harness.snapshot(harness.selected["id"]) == harness.selected


@pytest.mark.parametrize("document_version", [1, 2])
@pytest.mark.parametrize("export_format", ["markdown", "bibtex"])
async def test_share_and_export_stay_pinned_when_latest_version_changes(
    v2_consumers, document_version, export_format
):
    harness = v2_consumers
    report = harness.legacy if document_version == 1 else harness.selected
    root = f"/research/reports/{report['id']}"
    created_share = await harness.client.post(root + "/shares", json={"expiresInHours": 24})
    assert created_share.status_code == 200, created_share.text
    share = created_share.json()
    token = share["sharePath"].split("share=", 1)[1]
    created_export = await harness.client.post(root + "/exports", json={"format": export_format})
    assert created_export.status_code == 200, created_export.text
    export = created_export.json()
    before = await harness.client.get(export["downloadPath"])
    assert before.status_code == 200, before.text
    assert export["reportId"] == str(report["id"])
    assert export["reportVersion"] == report["version"]
    assert export["sha256"] == hashlib.sha256(before.content).hexdigest()
    assert export["sizeBytes"] == len(before.content)
    if export_format == "markdown":
        assert before.text == report["markdown"]
    else:
        source_index = 0 if document_version == 1 else 1
        assert f"https://example.test/{source_index}" in before.text
        assert "@misc{" in before.text

    newer = await harness.publish(6, source_index=1 if document_version == 1 else 0)
    current = await api.get_research_run(report["run_id"])
    assert current["report"]["id"] == str(newer["id"])
    selected = await api.get_research_run(report["run_id"], report_version=report["version"])
    assert selected["report"]["id"] == str(report["id"])
    assert selected["report"]["document"] == report["document"]
    assert selected["report"]["answerQuality"] == "partial"
    public = await harness.client.get("/s", headers={"Authorization": f"ResearchShare {token}"})
    assert public.status_code == 200, public.text
    assert public.json()["version"] == report["version"]
    assert public.json()["document"] == report["document"]
    assert public.json()["markdown"] == report["markdown"]
    assert public.headers["cache-control"] == "private, no-store"
    after = await harness.client.get(export["downloadPath"])
    assert after.status_code == 200 and after.content == before.content
    assert after.headers["cache-control"] == "private, no-store"
    repeated = await harness.client.post(root + "/exports", json={"format": export_format})
    assert repeated.status_code == 200 and repeated.json() == export
    async with harness.sessions() as session:
        stored_export = await session.get(ReportExport, uuid.UUID(export["id"]))
        stored_share = await session.get(ReportShare, uuid.UUID(share["id"]))
        assert stored_export.report_id == stored_share.report_id == report["id"]
        assert stored_export.document_hash == report["content_hash"]
    assert await harness.snapshot(report["id"]) == report

    revoked = await harness.client.post(root + f"/shares/{share['id']}/revoke", json={})
    assert revoked.status_code == 200, revoked.text
    denied = await harness.client.get("/s", headers={"Authorization": f"ResearchShare {token}"})
    assert denied.status_code == 404
