"""Explicit-mode graph behavior on loopback PostgreSQL; paid IO is replaced."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from research_api.config import Settings
from research_api.db.models import Report, ResearchRun
from research_api.db.session import tenant_session
from research_api.graph import builder, collection
from research_api.mode_policy import MODE_POLICY_VERSION, resolve_mode_budget
from research_api.repositories.runs import RunRepository
from tests.integration.test_reliability_runtime import seed

pytestmark = pytest.mark.integration


async def test_explicit_deep_evergreen_empty_collection_is_honest_report(monkeypatch):
    tenant, user, _ = await seed()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="What is durable execution?",
            mode="deep",
            mode_policy_version=MODE_POLICY_VERSION,
            budget=resolve_mode_budget("deep"),
        )
        run_id = run.id
    planner = AsyncMock(return_value=builder._heuristic_plan("Durable execution", 1))
    monkeypatch.setattr(builder, "_plan_with_openai", planner)
    invocations = []

    class EmptyIngestor:
        def __init__(self, **kwargs):
            pass

        async def ingest(self, **kwargs):
            invocations.append(kwargs)
            return []

    monkeypatch.setattr(collection, "TavilyEvidenceIngestor", EmptyIngestor)
    writer = AsyncMock(side_effect=AssertionError("empty evidence must not call a writer"))
    monkeypatch.setattr(builder, "_synthesize_with_openai", writer)
    await builder.run_graph(
        Settings(_env_file=None, OPENAI_API_KEY="fixture", TAVILY_API_KEY="fixture"),
        run_id=run_id,
        tenant_id=tenant,
        user_id=user,
        question="What is durable execution?",
    )
    assert planner.await_count == 1
    assert invocations and all(not call["quick_mode"] for call in invocations)
    assert writer.await_count == 0
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        report = await session.scalar(select(Report).where(Report.run_id == run_id))
        assert run.status == "completed"
        assert run.mode == report.document["mode"] == "deep"
        assert report.document["quality"]["status"] == "insufficient_evidence"
        assert report.document["quality"]["verifiedFindings"] == 0
