from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api.artifacts.store import InMemoryArtifactStore
from research_api.db.models import Budget, ProviderCall, ResearchRun, Source, Tenant, User
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.ingestion import TavilyEvidenceIngestor
from research_api.providers.tavily import TavilyAdapter
from research_api.repositories.budgets import BudgetExceededError, BudgetReservationRepository
from research_api.repositories.runs import RunBudgetDefaults, RunRepository

pytestmark = pytest.mark.integration

ADMIN_URL = os.getenv(
    "TEST_DATABASE_ADMIN_URL",
    "postgresql+psycopg://research_owner:research_owner@localhost:55432/research",
)


async def _seed_identity() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_URL)
    admin_sessions = async_sessionmaker(admin_engine, expire_on_commit=False)
    try:
        async with admin_sessions() as session, session.begin():
            session.add(Tenant(id=tenant_id, name=f"tenant-{tenant_id}"))
            session.add(User(id=user_id, tenant_id=tenant_id, external_subject=str(user_id)))
    finally:
        await admin_engine.dispose()
    return tenant_id, user_id


async def _create_run(
    tenant_id: uuid.UUID, user_id: uuid.UUID, *, max_search_calls: int = 12
) -> uuid.UUID:
    async with tenant_session(str(tenant_id)) as session:
        run = await RunRepository(session, tenant_id).create(
            user_id=user_id,
            question="What changed?",
            budget=RunBudgetDefaults(max_search_calls=max_search_calls),
        )
        return run.id


async def test_rls_hides_another_tenants_run() -> None:
    first_tenant, first_user = await _seed_identity()
    second_tenant, _ = await _seed_identity()
    run_id = await _create_run(first_tenant, first_user)

    async with tenant_session(str(second_tenant)) as session:
        hidden = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))

    assert hidden is None


async def test_foreign_keys_reject_cross_tenant_run_reference() -> None:
    first_tenant, first_user = await _seed_identity()
    second_tenant, _ = await _seed_identity()
    run_id = await _create_run(first_tenant, first_user)
    admin_engine = create_async_engine(ADMIN_URL)
    admin_sessions = async_sessionmaker(admin_engine, expire_on_commit=False)
    try:
        with pytest.raises(IntegrityError):
            async with admin_sessions() as session, session.begin():
                session.add(
                    Budget(
                        tenant_id=second_tenant,
                        run_id=run_id,
                        max_wall_clock_ms=1,
                        max_search_calls=1,
                        max_browser_sessions=0,
                        max_reflection_rounds=0,
                        max_input_tokens=1,
                        max_output_tokens=1,
                        max_estimated_cost_usd=Decimal("0"),
                    )
                )
    finally:
        await admin_engine.dispose()


async def test_budget_reservation_cannot_be_oversubscribed() -> None:
    tenant_id, user_id = await _seed_identity()
    run_id = await _create_run(tenant_id, user_id, max_search_calls=1)

    async def reserve(fingerprint: str) -> str:
        try:
            async with tenant_session(str(tenant_id)) as session:
                await BudgetReservationRepository(session, tenant_id).reserve(
                    run_id=run_id,
                    provider="tavily",
                    operation="search",
                    request_fingerprint=fingerprint,
                    estimated_cost_usd=Decimal("0.01"),
                )
            return "reserved"
        except BudgetExceededError:
            return "rejected"

    outcomes = await asyncio.gather(reserve("request-a"), reserve("request-b"))
    assert sorted(outcomes) == ["rejected", "reserved"]


async def test_outbox_sequences_are_monotonic_and_replayable() -> None:
    tenant_id, user_id = await _seed_identity()
    run_id = await _create_run(tenant_id, user_id)

    async def append(index: int) -> int:
        async with tenant_session(str(tenant_id)) as session:
            event = await EventOutbox(session, tenant_id).append(
                run_id=run_id, event_type="test.event", payload={"index": index}
            )
            return event.event_sequence

    sequences = await asyncio.gather(*(append(index) for index in range(5)))
    assert sorted(sequences) == [1, 2, 3, 4, 5]

    async with tenant_session(str(tenant_id)) as session:
        replay = await EventOutbox(session, tenant_id).replay_after(run_id=run_id, sequence=2)
    assert [event.event_sequence for event in replay] == [3, 4, 5]


async def test_tavily_ingestion_persists_source_provider_ledger_and_raw_response() -> None:
    tenant_id, user_id = await _seed_identity()
    run_id = await _create_run(tenant_id, user_id)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "request_id": "search-1",
                    "usage": {"credits": 1},
                    "results": [{"url": "https://example.com/article", "title": "Article"}],
                },
            )
        return httpx.Response(
            200,
            json={
                "request_id": "extract-1",
                "usage": {"credits": 1},
                "results": [
                    {"url": "https://example.com/article", "raw_content": "  Evidence text.  "}
                ],
            },
        )

    client = httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    )
    artifacts = InMemoryArtifactStore()
    ingestor = TavilyEvidenceIngestor(
        adapter=TavilyAdapter(api_key="fixture", client=client), artifact_store=artifacts
    )
    try:
        source_ids = await ingestor.ingest(
            tenant_id=tenant_id, run_id=run_id, sub_question_id=None, query="test query"
        )
    finally:
        await client.aclose()

    assert len(source_ids) == 1
    async with tenant_session(str(tenant_id)) as session:
        source = await session.scalar(select(Source).where(Source.id == source_ids[0]))
        calls = list(
            await session.scalars(
                select(ProviderCall)
                .where(ProviderCall.run_id == run_id)
                .order_by(ProviderCall.started_at)
            )
        )
    assert source is not None
    stored_evidence = await artifacts.get_for_verification(artifact_ref=source.artifact_ref)
    assert stored_evidence == b"Evidence text."
    assert [call.outcome for call in calls] == ["succeeded", "succeeded"]
    search_call = next(call for call in calls if call.operation == "search")
    extract_call = next(call for call in calls if call.operation == "extract")
    assert search_call.provider_usage == {
        "credits": 1,
        "retrieval": {
            "discovered": 1,
            "shortlisted": 1,
            "excluded": 0,
            "duplicateWork": None,
            "duplicateUrl": 0,
            "unavailable": None,
            "policy": None,
        },
    }
    assert extract_call.provider_usage == {"credits": 1}
    assert all(call.response_artifact_ref for call in calls)
