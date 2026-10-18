"""Matched deterministic discovery; real local PG, no paid/provider network calls."""

import json
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from research_api import api, jobs
from research_api.artifacts.store import InMemoryArtifactStore
from research_api.config import Settings
from research_api.db.models import ExtractionSlot, ProviderCall, ResearchRun, Source, UsageLedger
from research_api.db.session import tenant_session
from research_api.graph import builder
from research_api.graph.builder import _exact_span
from research_api.ingestion import ProviderRecoveryNeededError, TavilyEvidenceIngestor
from research_api.providers.openalex import OpenAlexAdapter
from research_api.providers.serper import SerperAdapter
from research_api.providers.tavily import TavilyAdapter
from tests.integration.test_extraction_admission import seed

pytestmark = pytest.mark.integration
EVIDENCE = "Kafka stores ordered events within a partition."
SNIPPET = "Invented marketing claim: unlimited ledger throughput."


@asynccontextmanager
async def fixture_ingestor(provider, store=None):
    calls = []
    store = store or InMemoryArtifactStore()

    async def respond(request):
        calls.append((request.url.host, request.url.path))
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "meta": {"count": 12, "cost_usd": 0.0003},
                    "results": [
                        {
                            "id": f"https://openalex.org/W{i}",
                            "doi": f"https://doi.org/10.1234/work-{i}",
                            "title": (
                                f"Kafka durability study {i}" if i < 3 else "Audit procedure study"
                            ),
                            "publication_year": 2024,
                            "type": "article",
                            "authorships": [],
                            "primary_location": {"source": {"display_name": "Test Journal"}},
                            "best_oa_location": {
                                "landing_page_url": f"https://evidence.test/{i}",
                                "pdf_url": None,
                            },
                            "locations": [],
                            "open_access": {"is_oa": True},
                            "abstract_inverted_index": (
                                {"Kafka": [0], "durability": [1], "is": [2], "relevant": [3]}
                                if i < 3
                                else {"audit": [0], "procedures": [1]}
                            ),
                        }
                        for i in range(1, 4)
                    ],
                },
            )
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "google.serper.dev":
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "link": f"https://evidence.test/{i}",
                            "title": f"Source {i}",
                            "snippet": SNIPPET,
                        }
                        for i in range(3)
                    ]
                },
            )
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": f"https://evidence.test/{i}",
                            "title": f"Source {i}",
                            "content": SNIPPET,
                        }
                        for i in range(3)
                    ]
                },
            )
        return httpx.Response(
            200, json={"results": [{"url": url, "raw_content": EVIDENCE} for url in body["urls"]]}
        )

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com",
        transport=httpx.MockTransport(respond),
    ) as client:
        discovery = SerperAdapter("fixture", client=client) if provider == "serper" else None
        academic = (
            OpenAlexAdapter(api_key="fixture", client=client) if provider == "openalex" else None
        )
        yield (
            TavilyEvidenceIngestor(
                adapter=TavilyAdapter(api_key="fixture", client=client),
                artifact_store=store,
                discovery_adapter=discovery,
                academic_adapter=academic,
            ),
            calls,
            store,
        )


@pytest.mark.parametrize("provider", ["tavily", "serper", "openalex"])
async def test_matched_evidence_quota_and_restart_replay(provider, monkeypatch):
    tenant, run = await seed(6)
    args = dict(
        tenant_id=tenant,
        run_id=run,
        sub_question_id=None,
        query="Kafka durability",
        max_results=2,
        source_classes=["academic"] if provider == "openalex" else [],
    )
    async with fixture_ingestor(provider) as (ingestor, calls, store):
        ids = await ingestor.ingest(**args)
        assert len(ids) == 2
        assert len(calls) == 2  # One discovery + one extract, not per-candidate search.
    # Fresh adapter/session objects, shared durable artifact storage.
    async with fixture_ingestor(provider, store) as (restarted, new_calls, _):
        assert set(await restarted.ingest(**args)) == set(ids)
        assert new_calls == []
    async with tenant_session(str(tenant)) as session:
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        assert usage.search_calls == 2 and usage.reserved_search_calls == 0
        expected_cost = {
            "serper": Decimal("0.009"),
            "openalex": Decimal("0.0083"),
            "tavily": Decimal("0.016"),
        }[provider]
        assert usage.estimated_cost_usd == expected_cost
        sources = list(await session.scalars(select(Source).where(Source.run_id == run)))
        receipts = list(
            await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run))
        )
        assert {(r.provider, r.operation) for r in receipts} == {
            (provider, "search"),
            ("tavily", "extract"),
        }
        search = next(r for r in receipts if r.operation == "search")
        expected_retrieval = {
            "tavily": {
                # Tavily's adapter returns only the requested max_results; it
                # does not expose its upstream candidate pool.
                "discovered": 2,
                "shortlisted": 2,
                "excluded": 0,
                "duplicateWork": None,
                "duplicateUrl": 0,
                "unavailable": None,
                "policy": None,
            },
            "serper": {
                "discovered": 3,
                "shortlisted": 2,
                "excluded": 1,
                "duplicateWork": None,
                "duplicateUrl": 0,
                "unavailable": None,
                "policy": "serper-order-v1",
            },
            "openalex": {
                "discovered": 3,
                "shortlisted": 2,
                "excluded": 1,
                "duplicateWork": 0,
                "duplicateUrl": 0,
                "unavailable": 0,
                "policy": "academic-lexical-topk-v1",
            },
        }[provider]
        assert search.provider_usage["retrieval"] == expected_retrieval
        receipt = json.loads(
            await store.get_for_verification(artifact_ref=search.response_artifact_ref)
        )
        if provider in {"serper", "openalex"}:
            assert len(receipt["discovery_candidates"]) == 3
            assert len(receipt["results"]) == 2
            assert receipt["shortlist_policy"] == (
                "serper-order-v1" if provider == "serper" else "academic-lexical-topk-v1"
            )
            assert all(r["content"] == "" for r in receipt["results"])
        if provider == "openalex":
            assert receipt["usage"]["candidate_records_returned"] == 3
            assert receipt["usage"]["index_total_count"] == 12
            assert any(
                row.get("exclusion_reason") == "no_relevance_overlap"
                for row in receipt["discovery_candidates"]
            )
            assert all(source.provider == "openalex" for source in sources)
            assert all(source.source_class == "academic" for source in sources)
        for source in sources:
            text = (await store.get_for_verification(artifact_ref=source.artifact_ref)).decode()
            assert _exact_span(text, EVIDENCE) is not None
            assert _exact_span(text, SNIPPET) is None

        run_record = await session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == tenant,
                ResearchRun.id == run,
            )
        )
        assert run_record is not None
        run_user = run_record.user_id
    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(return_value=SimpleNamespace(tenant_id=tenant, user_id=run_user)),
    )
    projection = await api.get_research_run(run)
    accounting = projection["insights"]["retrievalAccounting"]
    assert accounting["schemaVersion"] == "1.2"
    assert accounting["extractionCalls"] == 1
    assert accounting["extractionOutcomes"]["succeeded"] == 1
    assert accounting["extractedSources"] == 2
    assert accounting["citedInVerifiedFinding"] == 0
    assert accounting["answerUsefulness"] == "not_assessed"
    assert accounting["dimensionRelevance"] == "not_assessed"
    assert accounting["sourceIndependence"] == "not_assessed"


async def test_missing_shortlist_receipt_blocks_extraction_without_refund():
    tenant, run = await seed(6)
    store = InMemoryArtifactStore()
    store.put = AsyncMock(side_effect=OSError("fixture storage unavailable"))
    async with fixture_ingestor("serper", store) as (ingestor, calls, _):
        for _ in range(2):
            with pytest.raises(ProviderRecoveryNeededError, match="receipt missing"):
                await ingestor.ingest(
                    tenant_id=tenant,
                    run_id=run,
                    sub_question_id=None,
                    query="Kafka durability",
                    max_results=2,
                )
        assert calls == [("google.serper.dev", "/search")]
    async with tenant_session(str(tenant)) as session:
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        assert usage.search_calls == 1
        assert usage.estimated_cost_usd == Decimal("0.001")
        assert not list(
            await session.scalars(select(ExtractionSlot).where(ExtractionSlot.run_id == run))
        )


@pytest.mark.parametrize("provider", ["serper", "openalex"])
async def test_discovery_receipts_are_tenant_scoped(provider):
    tenant, run = await seed(6)
    other, _ = await seed(6)
    async with fixture_ingestor(provider) as (ingestor, calls, _):
        await ingestor.ingest(
            tenant_id=tenant,
            run_id=run,
            sub_question_id=None,
            query="Kafka durability",
            max_results=2,
            source_classes=["academic"] if provider == "openalex" else [],
        )
        request = (
            OpenAlexAdapter.search_request(query="Kafka durability", per_page=10, selection_limit=2)
            if provider == "openalex"
            else SerperAdapter.search_request(query="Kafka durability", max_results=2)
        )
        assert await ingestor._replay_response(tenant_id=other, run_id=run, request=request) is None
        assert len(calls) == 2


@pytest.mark.parametrize("enabled,saved", [(False, False), (True, False), (True, True)])
async def test_new_graph_inputs_pin_route_and_saved_graph_is_not_reinitialized(
    monkeypatch, enabled, saved
):
    tenant, run = await seed(6)
    graph = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(builder, "build_graph", lambda *_args, **_kwargs: graph)
    saver = SimpleNamespace(
        config=lambda: {"configurable": {"thread_id": f"{tenant}:{run}"}},
        aget_tuple=AsyncMock(return_value=SimpleNamespace(pending_writes=[]) if saved else None),
    )
    await builder.run_graph(
        Settings(_env_file=None, SERPER_DISCOVERY_ENABLED=enabled, SERPER_API_KEY="fixture"),
        tenant_id=tenant,
        run_id=run,
        user_id=uuid.uuid4(),
        question="Kafka durability",
        checkpointer=saver,
    )
    invocation = graph.ainvoke.call_args.args[0]
    if saved:
        assert invocation is None  # Do not replace the saved route after a flag change.
    else:
        assert invocation["discovery_provider"] == ("serper" if enabled else "tavily")


@pytest.mark.parametrize("enabled", [False, True])
async def test_enqueued_route_survives_flag_change_before_first_checkpoint(monkeypatch, enabled):
    tenant, run_id = await seed(6)
    from research_api.db.models import ResearchRun, RuntimeJob

    settings = Settings(_env_file=None, SERPER_DISCOVERY_ENABLED=enabled, SERPER_API_KEY="fixture")
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        await jobs.enqueue(session, run, settings)
    async with tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run_id)
        assert job.graph_version == (jobs.SERPER_GRAPH_VERSION if enabled else jobs.GRAPH_VERSION)
    changed = settings.model_copy(update={"SERPER_DISCOVERY_ENABLED": not enabled})
    assert await jobs.claim(tenant, uuid.uuid4(), changed) is not None
    graph = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(builder, "build_graph", lambda *_args, **_kwargs: graph)
    saver = SimpleNamespace(
        config=lambda: {"configurable": {"thread_id": f"{tenant}:{run_id}"}},
        aget_tuple=AsyncMock(return_value=None),
    )
    await builder.run_graph(
        changed,
        tenant_id=tenant,
        run_id=run_id,
        user_id=uuid.uuid4(),
        question="Kafka durability",
        checkpointer=saver,
    )
    assert graph.ainvoke.call_args.args[0]["discovery_provider"] == (
        "serper" if enabled else "tavily"
    )


async def test_enqueued_openalex_capability_is_pinned_before_first_checkpoint(monkeypatch):
    tenant, run_id = await seed(6)
    from research_api.db.models import ResearchRun, RuntimeJob

    settings = Settings(_env_file=None, OPENALEX_DISCOVERY_ENABLED=True)
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        await jobs.enqueue(session, run, settings)
    async with tenant_session(str(tenant)) as session:
        job = await session.get(RuntimeJob, run_id)
        assert job.graph_version == jobs.OPENALEX_GRAPH_VERSION

    graph = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(builder, "build_graph", lambda *_args, **_kwargs: graph)
    saver = SimpleNamespace(
        config=lambda: {"configurable": {"thread_id": f"{tenant}:{run_id}"}},
        aget_tuple=AsyncMock(return_value=None),
    )
    await builder.run_graph(
        settings,
        tenant_id=tenant,
        run_id=run_id,
        user_id=uuid.uuid4(),
        question="Kafka durability",
        checkpointer=saver,
    )
    invocation = graph.ainvoke.call_args.args[0]
    assert invocation["openalex_discovery_enabled"] is True
