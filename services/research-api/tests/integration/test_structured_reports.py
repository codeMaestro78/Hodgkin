"""Phase 1 graph/report persistence on loopback PostgreSQL, with no paid calls.

Run after local migration 0008:
    uv run pytest tests/integration/test_structured_reports.py

The real writer and verifier orchestration run against deterministic model replies;
source ingestion/artifact reads and every model boundary are replaced locally.
"""

import json
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_reliability_runtime import seed

from research_api import api
from research_api.config import Settings
from research_api.db import models
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.graph import builder
from research_api.report_document import validate_report_document

pytestmark = pytest.mark.integration

QUESTION = "Compare evidence reliability"
REQUIREMENTS = ["Explain evidence preservation", "Quantify operational risks"]
QUOTE = "Exact source evidence is preserved."
SAFE = "Preserved evidence is inspectable."
UNSUPPORTED = "All operational risks have been eliminated."
NONEXACT = "A fabricated passage establishes complete safety."
UNKNOWN_SOURCE = "An unknown source proves the conclusion."


@pytest.fixture
async def report_harness(monkeypatch):
    # conftest enforces loopback before DB imports; check again before seed writes.
    for name in ("DATABASE_URL", "TEST_DATABASE_ADMIN_URL"):
        assert urlsplit(os.environ[name]).hostname in {"localhost", "127.0.0.1", "::1"}
    tenants = []
    settings = Settings(_env_file=None, OPENAI_API_KEY="fixture", TAVILY_API_KEY="fixture")
    # Even an accidental low-level SDK invocation must fail before opening a socket.
    sdk_create = AsyncMock(side_effect=AssertionError("Unexpected paid model invocation"))
    sdk = SimpleNamespace(responses=SimpleNamespace(create=sdk_create), close=AsyncMock())
    monkeypatch.setattr(builder, "AsyncOpenAI", Mock(return_value=sdk))

    async def arrange(*, supported=True, requirements=None, calls=6):
        tenant, user, run_id = await seed(calls)
        tenants.append(tenant)
        requirements = list(REQUIREMENTS if requirements is None else requirements)
        async with tenant_session(str(tenant)) as session:
            run = await session.get(models.ResearchRun, run_id)
            run.report_requirements = requirements
        planner = AsyncMock(
            return_value=builder.PlannerOutput(
                sub_questions=[
                    builder.PlannedQuestion(
                        question="Find original evidence",
                        rationale="Inspect preserved passages",
                        success_criteria=["Exact passages"],
                        source_classes=["primary"],
                    )
                ]
            )
        )
        monkeypatch.setattr(builder, "_plan_with_openai", planner)
        ingestions = []

        class Ingestor:
            def __init__(self, **_):
                pass

            async def ingest(self, **kwargs):
                ingestions.append(kwargs)
                async with tenant_session(str(tenant)) as session:
                    source = models.Source(
                        id=uuid.uuid4(),
                        tenant_id=tenant,
                        run_id=run_id,
                        sub_question_id=kwargs["sub_question_id"],
                        canonical_url="https://example.test/phase1-evidence",
                        title="Local fixture evidence",
                        provider="tavily",
                        source_class="primary",
                        retrieved_at=datetime.now(UTC),
                        content_hash="a" * 64,
                        artifact_ref="fixture",
                        discovery_paths=[],
                        content_signature=[],
                    )
                    session.add(source)
                    await session.flush()
                    return [source.id]

        monkeypatch.setattr(builder, "TavilyEvidenceIngestor", Ingestor)

        async def context(_settings, *, sources, **_):
            return [builder.SourceMaterial(source=sources[0], content=QUOTE)], "SOURCE [1] " + QUOTE

        monkeypatch.setattr(builder, "_read_source_context", context)
        candidates = []
        for text, quote, source_number, indices in (
            (SAFE, QUOTE, 1, [0, -1, 999]),
            (UNSUPPORTED, QUOTE, 1, [1]),
            (NONEXACT, "This passage does not exist in the artifact.", 1, [1]),
            (UNKNOWN_SOURCE, QUOTE, 20, [1]),
        ):
            candidate = dict(
                claim=text,
                section="mechanisms",
                caveats=[],
                citations=[dict(source_number=source_number, quote=quote)],
            )
            if requirements:
                candidate["requirement_indices"] = indices
            candidates.append(candidate)
        response = AsyncMock(
            return_value=SimpleNamespace(output_text=json.dumps({"claims": candidates}))
        )
        monkeypatch.setattr(builder, "_model_response", response)
        writer = AsyncMock(wraps=builder._synthesize_with_openai)
        monkeypatch.setattr(builder, "_synthesize_with_openai", writer)
        audit = AsyncMock(side_effect=AssertionError("Structured writer must not re-audit prose"))
        monkeypatch.setattr(builder, "_report_assertions", audit)

        async def reviews(_settings, *, claims):
            return [
                builder.SemanticReview(
                    claim_index=index,
                    citation_index=0,
                    verdict="supports" if supported and claim.claim == SAFE else "contradicts",
                    confidence=0.9,
                )
                for index, claim in enumerate(claims)
            ]

        semantic = AsyncMock(side_effect=reviews)
        monkeypatch.setattr(builder, "_semantic_reviews_with_openai", semantic)
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

        async def execute():
            await builder.run_graph(
                settings,
                run_id=run_id,
                tenant_id=tenant,
                user_id=user,
                question=QUESTION,
            )

        return SimpleNamespace(
            tenant=tenant,
            user=user,
            run_id=run_id,
            execute=execute,
            requirements=requirements,
            planner=planner,
            writer=writer,
            response=response,
            semantic=semantic,
            audit=audit,
            sdk_create=sdk_create,
            ingestions=ingestions,
        )

    try:
        yield arrange
    finally:
        # Scoped cleanup uses only UUIDs minted by this fixture, preserving parallel agents' data.
        admin = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
        try:
            async with async_sessionmaker(admin)() as session, session.begin():
                for tenant in tenants:
                    for model in (
                        models.Citation,
                        models.EvidenceClaim,
                        models.ResearchGap,
                        models.Report,
                        models.RunEvent,
                        models.NodeExecution,
                        models.SubQuestionAttempt,
                        models.Source,
                        models.SubQuestion,
                        models.ResearchPlan,
                        models.Budget,
                        models.UsageLedger,
                        models.ResearchRun,
                        models.DispatchRegistry,
                        models.User,
                    ):
                        await session.execute(delete(model).where(model.tenant_id == tenant))
                    await session.execute(delete(models.Tenant).where(models.Tenant.id == tenant))
        finally:
            await admin.dispose()


@pytest.mark.parametrize("calls", [6, 12, 20])
@pytest.mark.parametrize("supported", [True, False])
async def test_graph_persists_only_verified_findings_and_conservative_requirement_links(
    report_harness,
    supported,
    calls,
):
    harness = await report_harness(supported=supported, calls=calls)
    await harness.execute()
    async with tenant_session(str(harness.tenant)) as session:
        run = await session.get(models.ResearchRun, harness.run_id)
        assert run.status == "completed", run.error_code
        report = await session.get(models.Report, run.report_id)
        document = report.document
        assert validate_report_document(document) == document
        assert document["version"] == 1 and document["title"] == QUESTION
        assert document["quality"]["status"] == (
            "partial" if supported else "insufficient_evidence"
        )
        assert document["quality"]["verifiedFindings"] == int(supported)
        assert document["quality"]["excludedFindings"] == (3 if supported else 4)
        requirements = document["requirements"]
        assert [row["id"] for row in requirements] == [
            "question",
            "requirement-1",
            "requirement-2",
        ]
        assert [row["text"] for row in requirements] == [QUESTION, *REQUIREMENTS]
        assert requirements[0]["status"] == "unresolved"
        assert requirements[0]["claimIds"] == []
        assert requirements[1]["status"] == ("addressed" if supported else "unresolved")
        assert requirements[2]["status"] == "unresolved"
        assert requirements[2]["claimIds"] == []
        claims = list(
            await session.scalars(
                select(models.EvidenceClaim).where(
                    models.EvidenceClaim.run_id == harness.run_id,
                )
            )
        )
        assert len(claims) == 4  # Rejected candidates remain auditable.
        supported_ids = {str(claim.id) for claim in claims if claim.support == "supported"}
        assert {finding["id"] for finding in document["findings"]} == supported_ids
        assert requirements[1]["claimIds"] == sorted(supported_ids)
        for finding in document["findings"]:
            assert str(uuid.UUID(finding["id"])) == finding["id"]
            assert finding["text"] == SAFE and finding["section"] == "mechanisms"
            citations = list(
                await session.scalars(
                    select(models.Citation).where(
                        models.Citation.evidence_claim_id == uuid.UUID(finding["id"]),
                    )
                )
            )
            assert len(citations) == 1
            assert finding["citationIds"] == [str(citations[0].id)]
            assert finding["sourceIds"] == [str(citations[0].source_id)]
            assert citations[0].quote == QUOTE
            assert citations[0].verification["exactSpan"]["verified"] is True
            assert citations[0].verification["semanticSupport"]["verdict"] == "supports"
        for rows in (document["sections"], requirements, document["questionCoverage"]):
            assert all(set(row["claimIds"]) <= supported_ids for row in rows)
        assert (SAFE in report.markdown) is supported
        assert all(text not in report.markdown for text in (UNSUPPORTED, NONEXACT, UNKNOWN_SOURCE))
    snapshot = await api.get_research_run(harness.run_id)
    assert snapshot["originalQuestion"] == QUESTION
    assert snapshot["reportRequirements"] == REQUIREMENTS
    assert snapshot["report"]["document"] == document
    assert snapshot["report"]["answerQuality"] == document["quality"]["status"]
    assert harness.planner.await_count == harness.writer.await_count == 1
    assert all(requirement in harness.planner.call_args.args[1] for requirement in REQUIREMENTS)
    assert harness.writer.call_args.kwargs["question"] == QUESTION
    assert harness.writer.call_args.kwargs["report_requirements"] == REQUIREMENTS
    assert all(
        requirement in harness.response.call_args.kwargs["input"] for requirement in REQUIREMENTS
    )
    assert harness.response.await_count == harness.semantic.await_count == 1
    assert [claim.claim for claim in harness.semantic.call_args.kwargs["claims"]] == [
        SAFE,
        UNSUPPORTED,
    ]
    assert len(harness.ingestions) == 1
    harness.audit.assert_not_awaited()
    harness.sdk_create.assert_not_awaited()
    # Terminal replay must neither regenerate a document nor spend another model call.
    await harness.execute()
    replay = await api.get_research_run(harness.run_id)
    assert replay["report"] == snapshot["report"]
    assert harness.response.await_count == harness.writer.await_count == 1


async def test_empty_requirements_preserve_legacy_writer_call_signature(report_harness):
    harness = await report_harness(requirements=[])
    await harness.execute()
    snapshot = await api.get_research_run(harness.run_id)
    assert snapshot["status"] == "completed", snapshot["errorCode"]
    assert snapshot["reportRequirements"] == []
    assert harness.planner.call_args.args[1] == QUESTION
    assert "report_requirements" not in harness.writer.call_args.kwargs
    document = snapshot["report"]["document"]
    assert len(document["requirements"]) == 1
    assert document["requirements"][0]["id"] == "question"
    assert document["requirements"][0]["text"] == QUESTION
    assert document["requirements"][0]["status"] == "unresolved"
    assert document["quality"]["status"] == "partial"
    assert harness.response.await_count == 1
    harness.sdk_create.assert_not_awaited()


async def test_api_selected_version_uses_its_document_and_never_infers_legacy_quality(
    report_harness,
):
    harness = await report_harness()
    await harness.execute()
    structured = await api.get_research_run(harness.run_id, report_version=1)
    assert structured["report"]["document"]["findings"]  # Real supported claims exist.
    async with tenant_session(str(harness.tenant)) as session:
        legacy = models.Report(
            id=uuid.uuid4(),
            tenant_id=harness.tenant,
            run_id=harness.run_id,
            version=2,
            markdown="Legacy markdown with no structured assessment.",
            published=True,
        )
        session.add(legacy)
        await session.flush()
        # Legacy reports may have genuine claim checks: these cannot substitute
        # for a persisted structured document or establish answer completeness.
        original = await session.get(
            models.EvidenceClaim,
            uuid.UUID(structured["report"]["document"]["findings"][0]["id"]),
        )
        legacy_claim = models.EvidenceClaim(
            id=uuid.uuid4(),
            tenant_id=harness.tenant,
            run_id=harness.run_id,
            sub_question_id=original.sub_question_id,
            report_id=legacy.id,
            claim=original.claim,
            support=original.support,
            confidence=0,
            caveats=original.caveats,
            provenance=original.provenance,
        )
        session.add(legacy_claim)
        await session.flush()
        original_citation = await session.scalar(
            select(models.Citation).where(
                models.Citation.evidence_claim_id == original.id,
            )
        )
        session.add(
            models.Citation(
                id=uuid.uuid4(),
                tenant_id=harness.tenant,
                run_id=harness.run_id,
                evidence_claim_id=legacy_claim.id,
                source_id=original_citation.source_id,
                quote=original_citation.quote,
                locator=original_citation.locator,
                verification=original_citation.verification,
            )
        )
        run = await session.get(models.ResearchRun, harness.run_id)
        run.report_id = legacy.id
    for version in (None, 2):
        snapshot = await api.get_research_run(harness.run_id, report_version=version)
        assert snapshot["report"]["id"] == str(legacy.id)
        assert snapshot["report"]["version"] == 2
        assert snapshot["report"]["document"] is None
        assert snapshot["report"]["answerQuality"] == "not_assessed"
        assert len(snapshot["claimChecks"]) == 1
        assert snapshot["claimChecks"][0]["status"] == "supported"
    selected = await api.get_research_run(harness.run_id, report_version=1)
    assert selected["report"] == structured["report"]
    assert selected["report"]["answerQuality"] == "partial"
    with pytest.raises(HTTPException) as missing:
        await api.get_research_run(harness.run_id, report_version=3)
    assert missing.value.status_code == 404
    assert harness.response.await_count == 1
    harness.sdk_create.assert_not_awaited()


async def test_report_document_and_evidence_rollback_when_publication_event_fails(
    report_harness,
    monkeypatch,
):
    harness = await report_harness()
    original = EventOutbox.append
    rejected = []

    async def fail_publication(self, **kwargs):
        event = await original(self, **kwargs)
        if kwargs["run_id"] == harness.run_id and kwargs["event_type"] == "synthesis.completed":
            # Fail after the event flush, when the report/evidence writes also reached Postgres.
            rejected.append(event.event_id)
            raise RuntimeError("fixture publication failure after flush")
        return event

    monkeypatch.setattr(EventOutbox, "append", fail_publication)
    await harness.execute()
    assert len(rejected) == 1
    async with tenant_session(str(harness.tenant)) as session:
        run = await session.get(models.ResearchRun, harness.run_id)
        assert run.status == "failed" and run.error_code == "graph_execution_failed"
        assert run.report_id is None
        for model in (models.Report, models.EvidenceClaim, models.Citation, models.ResearchGap):
            assert not list(
                await session.scalars(select(model).where(model.run_id == harness.run_id))
            )
        events = list(
            await session.scalars(
                select(models.RunEvent).where(
                    models.RunEvent.run_id == harness.run_id,
                )
            )
        )
        assert all(event.event_type != "synthesis.completed" for event in events)
        assert any(event.event_type == "run.failed" for event in events)
        assert list(
            await session.scalars(
                select(models.Source).where(
                    models.Source.run_id == harness.run_id,
                )
            )
        )
    assert (await api.get_research_run(harness.run_id))["report"] is None
    assert harness.response.await_count == 1
    harness.sdk_create.assert_not_awaited()
