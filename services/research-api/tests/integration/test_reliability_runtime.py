"""Actual local persistence/graph with deterministic model and provider boundaries."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import api
from research_api.config import Settings
from research_api.db.models import (
    Citation,
    EvidenceClaim,
    NodeExecution,
    Report,
    ResearchGap,
    ResearchRun,
    RunEvent,
    Source,
    SubQuestionAttempt,
    Tenant,
    UsageLedger,
    User,
)
from research_api.db.session import tenant_session
from research_api.execution import finish_node, start_node
from research_api.graph import builder
from research_api.model_budget import model_response, model_run
from research_api.repositories.budgets import BudgetExceededError
from research_api.repositories.runs import RunBudgetDefaults, RunRepository
from research_api.schemas.generated.followup_request import FollowupRequest

pytestmark = pytest.mark.integration


async def seed():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(
        "postgresql+psycopg://research_owner:research_owner@localhost:55432/research"
    )
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Reliability fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="Compare evidence reliability",
            budget=RunBudgetDefaults(max_search_calls=6),
        )
        return tenant, user, run.id


@pytest.mark.parametrize("supported", [True, False])
async def test_report_audit_retains_conflicts_but_publishes_only_supported_assertions(
    monkeypatch, supported
):
    tenant, user, run_id = await seed()
    quote = "Exact source evidence."
    safe = "Preserved evidence is inspectable."
    disputed = "All claims are always correct."
    question = builder.PlannedQuestion(
        question="Find original evidence",
        rationale="Test evidence",
        success_criteria=["Exact passages"],
        source_classes=["primary"],
    )
    monkeypatch.setattr(
        builder,
        "_plan_with_openai",
        AsyncMock(return_value=builder.PlannerOutput(sub_questions=[question])),
    )

    class Ingestor:
        def __init__(self, **_):
            pass

        async def ingest(self, **kwargs):
            async with tenant_session(str(tenant)) as session:
                source = Source(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    run_id=run_id,
                    sub_question_id=kwargs["sub_question_id"],
                    canonical_url="https://example.test/evidence",
                    title="Evidence",
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

    async def context(_settings, *, sources):
        return [builder.SourceMaterial(source=sources[0], content=quote)], "SOURCE [1] " + quote

    monkeypatch.setattr(builder, "_read_source_context", context)
    citation = builder.CitationDraft(source_number=1, quote=quote)
    monkeypatch.setattr(
        builder,
        "_synthesize_with_openai",
        AsyncMock(
            return_value=builder.SynthesisOutput(
                answer_markdown=f"## Findings\n{safe}\n{disputed}",
                claims=[builder.ClaimDraft(claim=safe, citations=[citation], caveats=[])],
            )
        ),
    )
    monkeypatch.setattr(
        builder,
        "_report_assertions",
        AsyncMock(
            return_value=builder.ReportAssertions(
                claims=[
                    builder.ReportAssertion(claim=safe, citations=[citation], caveats=[]),
                    builder.ReportAssertion(claim=disputed, citations=[citation], caveats=[]),
                ]
            )
        ),
    )

    async def reviews(_settings, *, claims):
        return [
            builder.SemanticReview(
                claim_index=index,
                citation_index=0,
                verdict="supports" if claim.claim == safe and supported else "contradicts",
                confidence=0.9,
            )
            for index, claim in enumerate(claims)
        ]

    monkeypatch.setattr(builder, "_semantic_reviews_with_openai", reviews)
    await builder.run_graph(
        Settings(TAVILY_API_KEY="fixture", OPENAI_API_KEY="fixture"),
        run_id=run_id,
        tenant_id=tenant,
        user_id=user,
        question="Compare evidence reliability",
    )
    async with tenant_session(str(tenant)) as session:
        run = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))
        assert run.status == "completed"
        report = await session.scalar(select(Report).where(Report.run_id == run_id))
        assert disputed not in report.markdown
        assert (safe in report.markdown) is supported
        if not supported:
            assert "No factual findings were published" in report.markdown
        claims = list(
            await session.scalars(select(EvidenceClaim).where(EvidenceClaim.run_id == run_id))
        )
        assert {item.support for item in claims} == (
            {"supported", "contradicted"} if supported else {"contradicted"}
        )
        assert all(item.report_id == report.id for item in claims)
        assert list(await session.scalars(select(ResearchGap).where(ResearchGap.run_id == run_id)))
        assert (
            len(list(await session.scalars(select(Citation).where(Citation.run_id == run_id)))) == 2
        )
        attempts = list(
            await session.scalars(
                select(SubQuestionAttempt).where(SubQuestionAttempt.run_id == run_id)
            )
        )
        assert attempts and all(
            item.status == "completed" and item.completed_at for item in attempts
        )
        nodes = list(
            await session.scalars(select(NodeExecution).where(NodeExecution.run_id == run_id))
        )
        assert nodes and all(item.status == "completed" and item.completed_at for item in nodes)
        events = list(
            await session.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.event_sequence)
            )
        )
        assert events[-1].event_type == "run.completed"
        assert len({event.event_sequence for event in events}) == len(events)
    async with tenant_session(str(uuid.uuid4())) as session:
        assert not list(
            await session.scalars(select(EvidenceClaim).where(EvidenceClaim.run_id == run_id))
        )


async def test_task_terminal_transition_is_idempotent_and_does_not_allow_regression():
    tenant, _, run = await seed()
    task = await start_node(tenant, run, "planner")
    await finish_node(tenant, run, task, "completed")
    await finish_node(tenant, run, task, "failed")
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(NodeExecution).where(NodeExecution.id == task))
        assert row.status == "completed"
        events = list(await session.scalars(select(RunEvent).where(RunEvent.run_id == run)))
        assert len(events) == 2
    with pytest.raises(ValueError):
        await finish_node(tenant, run, task, "running")


async def test_model_reservations_do_not_spend_search_budget_or_redispatch_terminal_calls():
    tenant, _, run = await seed()
    token = model_run.set((tenant, run))
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(usage=SimpleNamespace(input_tokens=5, output_tokens=8))
            )
        )
    )
    try:
        await model_response(client, model="fixture", input="public evidence", store=False)
        with pytest.raises(BudgetExceededError):
            await model_response(client, model="fixture", input="public evidence", store=False)
        assert client.responses.create.await_count == 1
        assert client.responses.create.call_args.kwargs["max_output_tokens"] == 4096
        async with tenant_session(str(tenant)) as session:
            usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
            assert usage.search_calls == 0 and usage.input_tokens == 5 and usage.output_tokens == 8
    finally:
        model_run.reset(token)


async def test_followup_is_owned_idempotent_and_preserves_parent_report(monkeypatch):
    tenant, user, run = await seed()
    async with tenant_session(str(tenant)) as session:
        report = Report(
            id=uuid.uuid4(),
            tenant_id=tenant,
            run_id=run,
            version=1,
            markdown="Preserved original conclusion.",
            published=True,
        )
        session.add(report)
        await session.flush()
        parent = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        parent.status, parent.report_id = "completed", report.id
        parent_report_id = report.id
        newer = Report(
            id=uuid.uuid4(),
            tenant_id=tenant,
            run_id=run,
            version=2,
            markdown="Newer report remains separate.",
            published=True,
        )
        session.add(newer)
        await session.flush()
        parent.report_id = newer.id
    caller = SimpleNamespace(tenant_id=tenant, user_id=user)
    monkeypatch.setattr(api, "_caller", AsyncMock(return_value=caller))
    monkeypatch.setattr(api, "run_graph", AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_tasks=set())))
    body = FollowupRequest(
        question="Investigate contradictory evidence",
        idempotencyKey=str(uuid.uuid4()),
        reportVersion=1,
    )
    first = await api.followup_research_run(run, body, request)
    second = await api.followup_research_run(run, body, request)
    assert first["runId"] == second["runId"]
    snapshot = await api.get_research_run(run, report_version=1)
    assert snapshot["report"]["version"] == 1
    with pytest.raises(HTTPException) as missing:
        await api.get_research_run(run, report_version=3)
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as reused:
        await api.followup_research_run(
            run,
            FollowupRequest(
                question=body.question, idempotencyKey=body.idempotency_key, reportVersion=2
            ),
            request,
        )
    assert reused.value.status_code == 409
    if request.app.state.background_tasks:
        import asyncio

        await asyncio.gather(*request.app.state.background_tasks)
    async with tenant_session(str(tenant)) as session:
        original = await session.scalar(select(Report).where(Report.id == parent_report_id))
        fresh = await session.scalar(
            select(ResearchRun).where(ResearchRun.id == uuid.UUID(first["runId"]))
        )
        assert original.markdown == "Preserved original conclusion."
        assert fresh.parent_report_id == parent_report_id
        assert not list(await session.scalars(select(Source).where(Source.run_id == fresh.id)))
    caller.user_id = uuid.uuid4()
    with pytest.raises(HTTPException) as failure:
        await api.followup_research_run(run, body, request)
    assert failure.value.status_code == 404
