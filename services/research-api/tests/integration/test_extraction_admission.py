"""Real local database and deterministic transport, including pre-fetch concurrency."""

import asyncio
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api.accounting_ops import parser, reconcile, unresolved
from research_api.artifacts.store import InMemoryArtifactStore
from research_api.db.models import (
    ExtractionSlot,
    ProviderCall,
    ProviderCallReservation,
    ResearchRun,
    Source,
    Tenant,
    UsageLedger,
    User,
)
from research_api.db.session import tenant_session
from research_api.ingestion import TavilyEvidenceIngestor
from research_api.providers import tavily
from research_api.providers.tavily import TavilyAdapter, TavilyRequestError
from research_api.repositories.budgets import (
    BudgetExceededError,
    BudgetReservationRepository,
    InvalidReservationTransitionError,
)
from research_api.repositories.runs import RunBudgetDefaults, RunRepository

pytestmark = pytest.mark.integration


async def seed(ceiling=6):
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Admission test"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="Compare current evidence",
            budget=RunBudgetDefaults(max_search_calls=ceiling),
        )
        return tenant, run.id


def transport(extracted, mode="normal"):
    async def respond(request):
        payload = json.loads(request.content)
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": f"https://example.test/{payload['query']}/{index}"}
                        for index in range(6)
                    ]
                },
            )
        extracted.extend(payload["urls"])
        if mode == "timeout":
            raise httpx.ReadTimeout("ambiguous", request=request)
        if mode == "connect":
            # Handler reached here as a test transport only; production ConnectError
            # is before HTTP dispatch. Do not count these as fetched URLs.
            extracted.clear()
            raise httpx.ConnectError("not dispatched", request=request)
        await asyncio.sleep(0)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": url, "raw_content": "Evidence " + url} for url in payload["urls"]
                ]
                + [{"url": "https://example.test/unadmitted", "raw_content": "Do not accept"}]
            },
        )

    return httpx.MockTransport(respond)


@pytest.mark.parametrize("ceiling,quick", [(6, False), (12, False), (20, False), (6, True)])
async def test_fetches_not_just_storage_are_bounded_under_parallel_ingestion(ceiling, quick):
    tenant, run = await seed(ceiling)
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        results = await asyncio.gather(
            *(
                ingestor.ingest(
                    tenant_id=tenant,
                    run_id=run,
                    sub_question_id=None,
                    query=f"worker-{index}",
                    max_results=6,
                    quick_mode=quick,
                )
                for index in range(min(4, ceiling // 2))
            )
        )
    cap = 2 if quick else ceiling
    assert len(extracted) == len(set(extracted)) == cap
    assert sum(len(result) for result in results) == cap
    async with tenant_session(str(tenant)) as session:
        slots = list(
            await session.scalars(select(ExtractionSlot).where(ExtractionSlot.run_id == run))
        )
        sources = list(await session.scalars(select(Source).where(Source.run_id == run)))
    assert len(slots) == len(sources) == cap
    assert all(slot.state == "consumed" and slot.reservation_id for slot in slots)
    assert all(source.canonical_url in extracted for source in sources)


async def test_ambiguous_extraction_retains_quota_and_blocks_a_different_batch():
    tenant, run = await seed()
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted, "timeout")
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(TavilyRequestError):
            await ingestor.ingest(tenant_id=tenant, run_id=run, sub_question_id=None, query="first")
        assert (
            await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="second"
            )
            == []
        )
    assert len(extracted) == 6
    pending = await unresolved(tenant, run)
    assert len(pending) == 1 and not pending[0].receipt_available
    with pytest.raises(InvalidReservationTransitionError):
        await reconcile(tenant, run, pending[0].id)
    async with tenant_session(str(tenant)) as session:
        slots = list(
            await session.scalars(select(ExtractionSlot).where(ExtractionSlot.run_id == run))
        )
    assert len(slots) == 6 and all(slot.state == "uncertain" for slot in slots)


async def test_known_pre_dispatch_failure_releases_slots_for_new_query(monkeypatch):
    tenant, run = await seed()
    monkeypatch.setattr(tavily, "retry_delay", AsyncMock())
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted, "connect")
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(TavilyRequestError):
            await ingestor.ingest(tenant_id=tenant, run_id=run, sub_question_id=None, query="first")
    async with tenant_session(str(tenant)) as session:
        assert set(
            await session.scalars(select(ExtractionSlot.state).where(ExtractionSlot.run_id == run))
        ) == {"released"}
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        result = await ingestor.ingest(
            tenant_id=tenant, run_id=run, sub_question_id=None, query="second"
        )
    assert len(extracted) == len(result) == 6
    assert not await unresolved(tenant, run)


async def test_cancellation_at_extract_gate_releases_committed_slots_without_fetch():
    tenant, run = await seed()
    extracted = []

    class Adapter(TavilyAdapter):
        async def extract(self, request, **kwargs):
            async with tenant_session(str(tenant)) as session:
                row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
                row.cancellation_requested_at = datetime.now(UTC)
            return await super().extract(request, **kwargs)

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=Adapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(asyncio.CancelledError):
            await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="cancel"
            )
    assert not extracted
    async with tenant_session(str(tenant)) as session:
        slots = list(
            await session.scalars(select(ExtractionSlot).where(ExtractionSlot.run_id == run))
        )
    assert slots and all(slot.state == "released" for slot in slots)


async def test_existing_evidence_is_reused_without_reextracting_or_resetting_retrieval_time():
    tenant, run = await seed()
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        first = await ingestor.ingest(
            tenant_id=tenant, run_id=run, sub_question_id=None, query="shared"
        )
    async with tenant_session(str(tenant)) as session:
        dates = {
            source.id: source.retrieved_at
            for source in await session.scalars(select(Source).where(Source.run_id == run))
        }

    # Different query fingerprint, identical discovered pages.
    def respond(request):
        assert request.url.path == "/search"
        return httpx.Response(200, json={"results": [{"url": url} for url in extracted]})

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        second = await ingestor.ingest(
            tenant_id=tenant, run_id=run, sub_question_id=None, query="different"
        )
    assert set(first) == set(second) and len(extracted) == 6
    async with tenant_session(str(tenant)) as session:
        assert {
            source.id: source.retrieved_at
            for source in await session.scalars(select(Source).where(Source.run_id == run))
        } == dates


async def test_slot_rows_and_operations_are_tenant_and_run_scoped():
    tenant, run = await seed()
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted, "timeout")
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(TavilyRequestError):
            await ingestor.ingest(tenant_id=tenant, run_id=run, sub_question_id=None, query="scope")
    pending = await unresolved(tenant, run)
    assert pending
    other, other_run = await seed()
    async with tenant_session(str(other)) as session:
        assert not list(
            await session.scalars(select(ExtractionSlot).where(ExtractionSlot.run_id == run))
        )
    assert not await unresolved(other, run)
    with pytest.raises(LookupError):
        await reconcile(other, run, pending[0].id)
    with pytest.raises(LookupError):
        await reconcile(tenant, other_run, pending[0].id)
    with pytest.raises(SystemExit):
        parser().parse_args(
            ["reconcile", "--tenant-id", str(tenant), "--run-id", str(run), "--cost", "0"]
        )


async def test_budget_rejection_rolls_back_new_slots_and_does_not_extract():
    tenant, run = await seed(1)
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(BudgetExceededError):
            await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="budget"
            )
    assert not extracted
    async with tenant_session(str(tenant)) as session:
        assert not list(
            await session.scalars(select(ExtractionSlot).where(ExtractionSlot.run_id == run))
        )
    assert not await unresolved(tenant, run)


async def test_remaining_quota_trims_the_request_before_dispatch():
    tenant, run = await seed()
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        first = await ingestor.ingest(
            tenant_id=tenant, run_id=run, sub_question_id=None, query="first", max_results=4
        )
        second = await ingestor.ingest(
            tenant_id=tenant, run_id=run, sub_question_id=None, query="second", max_results=6
        )
    assert len(first) == 4 and len(second) == 2 and len(extracted) == 6


async def test_pending_same_urls_are_not_extracted_again_by_another_worker():
    tenant, run = await seed()
    started, finish = asyncio.Event(), asyncio.Event()
    extracted = []

    async def respond(request):
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={"results": [{"url": f"https://example.test/shared/{i}"} for i in range(6)]},
            )
        urls = json.loads(request.content)["urls"]
        extracted.extend(urls)
        started.set()
        await finish.wait()
        return httpx.Response(
            200, json={"results": [{"url": url, "raw_content": "Evidence"} for url in urls]}
        )

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        first = asyncio.create_task(
            ingestor.ingest(tenant_id=tenant, run_id=run, sub_question_id=None, query="first")
        )
        try:
            await asyncio.wait_for(started.wait(), 2)
            second = await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="second"
            )
            assert second == []  # A sibling owns these URLs; do not fail or refetch them.
        finally:
            finish.set()
        assert len(await first) == len(extracted) == 6


async def test_persisted_quick_question_cannot_be_overridden_by_caller_flag():
    tenant, run = await seed()
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        row.original_question = "What is HTTP?"
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        result = await ingestor.ingest(
            tenant_id=tenant, run_id=run, sub_question_id=None, query="quick", quick_mode=False
        )
    assert len(extracted) == len(result) == 2


async def test_fresh_worker_can_extract_new_urls_while_sibling_owns_overlap():
    tenant, run = await seed(ceiling=12)
    started, release = asyncio.Event(), asyncio.Event()
    fetched = []

    async def respond(request):
        data = json.loads(request.content)
        if request.url.path == "/search":
            indices = [0, 1, 2] if data["query"] == "first" else [0, 3, 4]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": f"https://example.test/{i}", "title": f"Source {i}"}
                        for i in indices
                    ]
                },
            )
        urls = data["urls"]
        fetched.extend(urls)
        if "https://example.test/0" in urls:
            started.set()
            await release.wait()
        return httpx.Response(
            200, json={"results": [{"url": url, "raw_content": "Evidence " + url} for url in urls]}
        )

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        first = asyncio.create_task(
            ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="first", max_results=3
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 2)
            second = await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="second", max_results=3
            )
            assert len(second) == 2
        finally:
            release.set()
        assert len(await first) == 3
        assert len(fetched) == len(set(fetched)) == 5


async def test_composite_foreign_key_rejects_a_reservation_from_another_run():
    tenant, run = await seed()
    async with tenant_session(str(tenant)) as session:
        user = await session.scalar(select(User.id).where(User.tenant_id == tenant))
        other_run = await RunRepository(session, tenant).create(
            user_id=user, question="Different run"
        )
        reservation = await BudgetReservationRepository(session, tenant).reserve(
            run_id=run,
            provider="tavily",
            operation="extract",
            request_fingerprint="cross-run-fixture",
            estimated_cost_usd=__import__("decimal").Decimal("0.008"),
        )
        reservation_id, other_run_id = reservation.id, other_run.id
    with pytest.raises(IntegrityError):
        async with tenant_session(str(tenant)) as session:
            session.add(
                ExtractionSlot(
                    tenant_id=tenant,
                    run_id=other_run_id,
                    reservation_id=reservation_id,
                    canonical_url="https://example.test/scope",
                    url_fingerprint=hashlib.sha256(b"https://example.test/scope").hexdigest(),
                )
            )
            await session.flush()


async def test_operator_reconciliation_consumes_uncertain_slots_without_freeing_quota():
    tenant, run = await seed()
    extracted = []
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=transport(extracted, "timeout")
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(TavilyRequestError):
            await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="uncertain"
            )
    pending = await unresolved(tenant, run)
    assert len(pending) == 1
    # Simulate receipt arrival through a trusted server process, not operator input.
    async with tenant_session(str(tenant)) as session:
        call = await session.scalar(
            select(ProviderCall).where(ProviderCall.reservation_id == pending[0].id)
        )
        call.outcome, call.completed_at = "succeeded", datetime.now(UTC)
    assert (await unresolved(tenant, run))[0].receipt_available
    assert (
        await asyncio.gather(*(reconcile(tenant, run, pending[0].id) for _ in range(4)))
        == ["consumed"] * 4
    )
    assert not await unresolved(tenant, run)
    async with tenant_session(str(tenant)) as session:
        assert set(
            await session.scalars(select(ExtractionSlot.state).where(ExtractionSlot.run_id == run))
        ) == {"consumed"}
        row = (
            await session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid='extraction_slots'::regclass"
                )
            )
        ).one()
        assert row.relrowsecurity and row.relforcerowsecurity
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        assert usage.search_calls == 2 and usage.reserved_search_calls == 0
        assert usage.estimated_cost_usd == Decimal("0.016")
        assert usage.reserved_estimated_cost_usd == 0


async def test_reconciliation_refreshes_deliberately_stale_orm_state_under_lock():
    tenant, run = await seed()
    async with tenant_session(str(tenant)) as session:
        repository = BudgetReservationRepository(session, tenant)
        reservation = await repository.reserve(
            run_id=run,
            provider="tavily",
            operation="extract",
            request_fingerprint="stale-receipt-fixture",
            estimated_cost_usd=Decimal("0.008"),
        )
        reservation_id = reservation.id
        session.add(
            ProviderCall(
                tenant_id=tenant,
                run_id=run,
                reservation_id=reservation_id,
                provider="tavily",
                operation="extract",
                request_fingerprint="stale-receipt-fixture",
                request_schema_version="fixture",
                outcome="succeeded",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        await repository.transition(reservation_id, new_state="uncertain")
    async with tenant_session(str(tenant)) as stale_session:
        stale_row = await stale_session.scalar(
            select(ProviderCallReservation).where(
                ProviderCallReservation.id == reservation_id,
            )
        )
        assert stale_row.state == "uncertain"
        assert await reconcile(tenant, run, reservation_id) == "consumed"
        # The identity map is deliberately stale until the locked query refreshes it.
        assert stale_row.state == "uncertain"
        result = await BudgetReservationRepository(stale_session, tenant).reconcile_from_receipt(
            reservation_id
        )
        assert result.state == "consumed"
    async with tenant_session(str(tenant)) as session:
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        assert usage.search_calls == 1 and usage.reserved_search_calls == 0
        assert usage.estimated_cost_usd == Decimal("0.008")
        assert usage.reserved_estimated_cost_usd == 0
