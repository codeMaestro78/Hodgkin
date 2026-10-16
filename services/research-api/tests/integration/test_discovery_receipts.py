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
from test_extraction_admission import seed

from research_api import jobs
from research_api.artifacts.store import InMemoryArtifactStore
from research_api.config import Settings
from research_api.db.models import ExtractionSlot, ProviderCall, Source, UsageLedger
from research_api.db.session import tenant_session
from research_api.graph import builder
from research_api.graph.builder import _exact_span
from research_api.ingestion import ProviderRecoveryNeededError, TavilyEvidenceIngestor
from research_api.providers.serper import SerperAdapter
from research_api.providers.tavily import TavilyAdapter

pytestmark = pytest.mark.integration
EVIDENCE = "Kafka stores ordered events within a partition."
SNIPPET = "Invented marketing claim: unlimited ledger throughput."


@asynccontextmanager
async def fixture_ingestor(provider, store=None):
    calls = []
    store = store or InMemoryArtifactStore()

    async def respond(request):
        calls.append((request.url.host, request.url.path))
        body = json.loads(request.content)
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
        yield (
            TavilyEvidenceIngestor(
                adapter=TavilyAdapter(api_key="fixture", client=client),
                artifact_store=store,
                discovery_adapter=discovery,
            ),
            calls,
            store,
        )


@pytest.mark.parametrize("provider", ["tavily", "serper"])
async def test_matched_evidence_quota_and_restart_replay(provider):
    tenant, run = await seed(6)
    args = dict(
        tenant_id=tenant, run_id=run, sub_question_id=None, query="Kafka durability", max_results=2
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
        assert usage.estimated_cost_usd == (
            Decimal("0.009") if provider == "serper" else Decimal("0.016")
        )
        sources = list(await session.scalars(select(Source).where(Source.run_id == run)))
        receipts = list(
            await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run))
        )
        assert {(r.provider, r.operation) for r in receipts} == {
            (provider, "search"),
            ("tavily", "extract"),
        }
        search = next(r for r in receipts if r.operation == "search")
        receipt = json.loads(
            await store.get_for_verification(artifact_ref=search.response_artifact_ref)
        )
        if provider == "serper":
            assert len(receipt["discovery_candidates"]) == 3
            assert len(receipt["results"]) == 2
            assert receipt["shortlist_policy"] == "serper-order-v1"
            assert all(r["content"] == "" for r in receipt["results"])
        for source in sources:
            text = (await store.get_for_verification(artifact_ref=source.artifact_ref)).decode()
            assert _exact_span(text, EVIDENCE) is not None
            assert _exact_span(text, SNIPPET) is None


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


async def test_discovery_receipts_are_tenant_scoped():
    tenant, run = await seed(6)
    other, _ = await seed(6)
    async with fixture_ingestor("serper") as (ingestor, calls, _):
        await ingestor.ingest(
            tenant_id=tenant,
            run_id=run,
            sub_question_id=None,
            query="Kafka durability",
            max_results=2,
        )
        request = SerperAdapter.search_request(query="Kafka durability", max_results=2)
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
