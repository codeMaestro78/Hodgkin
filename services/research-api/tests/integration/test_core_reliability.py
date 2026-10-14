"""Local PostgreSQL, deterministic transports; no hosted DB or paid calls."""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import model_budget
from research_api.artifacts.store import InMemoryArtifactStore
from research_api.config import Settings
from research_api.db.models import (
    NodeExecution,
    ProviderCall,
    ProviderCallReservation,
    ResearchRun,
    RunEvent,
    Source,
    Tenant,
    UsageLedger,
    User,
)
from research_api.db.session import tenant_session
from research_api.graph import builder
from research_api.ingestion import TavilyEvidenceIngestor
from research_api.model_budget import model_response, model_run
from research_api.providers import tavily
from research_api.providers.tavily import TavilyAdapter, TavilyRequestError
from research_api.repositories.budgets import (
    BudgetExceededError,
    BudgetReservationRepository,
    InvalidReservationTransitionError,
    ReservationReplayError,
)
from research_api.repositories.runs import RunBudgetDefaults, RunRepository
from research_api.schemas.generated.provider_call import Outcome
from research_api.telemetry import dependency_run

pytestmark = pytest.mark.integration


async def seed(calls=12, input_tokens=100_000):
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Core reliability fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="Compare reliable evidence",
            budget=RunBudgetDefaults(max_search_calls=calls, max_input_tokens=input_tokens),
        )
        return tenant, run.id


def model_client(response=None, error=None):
    return SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                return_value=response
                or SimpleNamespace(
                    id="fixture-response", usage=SimpleNamespace(input_tokens=500, output_tokens=8)
                ),
                side_effect=error,
            )
        )
    )


async def ledger(tenant, run):
    async with tenant_session(str(tenant)) as session:
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        reservations = list(
            await session.scalars(
                select(ProviderCallReservation)
                .where(
                    ProviderCallReservation.run_id == run,
                )
                .order_by(ProviderCallReservation.attempt)
            )
        )
        calls = list(await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run)))
        assert all(call.outcome in {item.value for item in Outcome} for call in calls)
        return usage, reservations, calls


async def test_actual_usage_larger_than_input_heuristic_is_not_underreported():
    tenant, run = await seed()
    token = model_run.set((tenant, run))
    try:
        await model_response(model_client(), model="gpt-4o-mini", input="q", store=False)
    finally:
        model_run.reset(token)
    usage, reservations, calls = await ledger(tenant, run)
    assert (usage.input_tokens, usage.output_tokens, usage.search_calls) == (500, 8, 0)
    assert usage.estimated_cost_usd == Decimal("0.000080")
    assert usage.reserved_estimated_cost_usd == 0
    assert reservations[0].state == "consumed"
    assert calls[0].provider_usage["accounting"]["usageBasis"] == "provider-usage"


async def test_missing_usage_and_unknown_model_stay_explicitly_estimated():
    tenant, run = await seed()
    token = model_run.set((tenant, run))
    try:
        await model_response(
            model_client(SimpleNamespace(usage=None)), model="unreviewed", input="q"
        )
    finally:
        model_run.reset(token)
    usage, _, calls = await ledger(tenant, run)
    assert usage.output_tokens == 4096 and usage.input_tokens > 0
    assert usage.estimated_cost_usd == Decimal("0.10")
    assert calls[0].provider_usage["accounting"]["pricingVersion"] == "policy-estimate-v1"


async def test_actual_usage_over_budget_is_committed_before_failing_closed():
    tenant, run = await seed(input_tokens=300)
    token = model_run.set((tenant, run))
    try:
        with pytest.raises(BudgetExceededError, match="actual model usage"):
            await model_response(model_client(), model="gpt-4o-mini", input="q")
    finally:
        model_run.reset(token)
    usage, reservations, _ = await ledger(tenant, run)
    assert usage.input_tokens == 500 and reservations[0].state == "consumed"


async def test_token_rejection_rolls_back_reservation_and_never_dispatches():
    tenant, run = await seed(input_tokens=1)
    client = model_client()
    token = model_run.set((tenant, run))
    try:
        with pytest.raises(BudgetExceededError, match="token budget"):
            await model_response(client, model="gpt-4o-mini", input="q")
    finally:
        model_run.reset(token)
    usage, reservations, calls = await ledger(tenant, run)
    assert not reservations and not calls
    assert usage.input_tokens == 0 and usage.reserved_estimated_cost_usd == 0
    client.responses.create.assert_not_called()


async def test_concurrent_identical_model_attempt_dispatches_once():
    tenant, run = await seed()
    client = model_client()
    token = model_run.set((tenant, run))
    try:
        outcomes = await asyncio.gather(
            *(model_response(client, model="gpt-4o-mini", input="q") for _ in range(4)),
            return_exceptions=True,
        )
    finally:
        model_run.reset(token)
    assert sum(isinstance(item, ReservationReplayError) for item in outcomes) == 3
    assert client.responses.create.await_count == 1
    usage, reservations, _ = await ledger(tenant, run)
    assert len(reservations) == 1 and usage.input_tokens == 500


@pytest.mark.parametrize("fail", [False, True])
async def test_parent_owned_client_is_shared_by_graph_child_tasks_and_closed(monkeypatch, fail):
    tenant, run = await seed()
    settings = Settings(OPENAI_API_KEY="fixture")
    client = SimpleNamespace(close=AsyncMock())
    factory = __import__("unittest.mock", fromlist=["Mock"]).Mock(return_value=client)
    dispatch = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(builder, "AsyncOpenAI", factory)
    monkeypatch.setattr(builder, "model_response", dispatch)

    class Graph:
        async def ainvoke(self, *_args):
            await asyncio.gather(
                *(
                    builder._model_response(settings, model="fixture", input=f"node-{index}")
                    for index in range(2)
                )
            )
            assert dependency_run.get() == run
            if fail:
                raise RuntimeError("fixture failure")

    monkeypatch.setattr(builder, "build_graph", lambda _: Graph())
    await builder.run_graph(
        settings, run_id=run, tenant_id=tenant, user_id=uuid.uuid4(), question="fixture"
    )
    assert factory.call_count == 1 and factory.call_args.kwargs["max_retries"] == 0
    assert factory.call_args.kwargs["timeout"] == 30
    assert all(call.args[0] is client for call in dispatch.call_args_list)
    client.close.assert_awaited_once()
    assert builder.model_client.get() is None and dependency_run.get() is None


async def test_provider_supplied_usage_cannot_override_internal_accounting():
    tenant, run = await seed()
    async with tenant_session(str(tenant)) as session:
        repository = BudgetReservationRepository(session, tenant)
        reservation = await repository.reserve(
            run_id=run,
            provider="tavily",
            operation="search",
            request_fingerprint="provider-usage",
            estimated_cost_usd=Decimal("0.008"),
        )
        reservation_id = reservation.id
        session.add(
            ProviderCall(
                tenant_id=tenant,
                run_id=run,
                reservation_id=reservation_id,
                provider="tavily",
                operation="search",
                request_fingerprint="provider-usage",
                request_schema_version="fixture",
                outcome="succeeded",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                provider_usage={
                    "accounting": {
                        "reservedInputTokens": 1000,
                        "inputTokens": 0,
                        "costUsd": "0",
                    }
                },
            )
        )
        await repository.transition(reservation_id, new_state="uncertain")
    async with tenant_session(str(tenant)) as session:
        await BudgetReservationRepository(session, tenant).reconcile_from_receipt(reservation_id)
    usage, _, _ = await ledger(tenant, run)
    assert usage.input_tokens == 0 and usage.estimated_cost_usd == Decimal("0.008")
    assert usage.search_calls == 1


@pytest.mark.parametrize("always_reject", [False, True])
async def test_real_sdk_has_one_retry_owner_and_at_most_three_accounted_attempts(
    monkeypatch,
    always_reject,
):
    tenant, run = await seed()
    monkeypatch.setattr(model_budget, "retry_delay", AsyncMock())
    requests = 0

    def respond(request):
        nonlocal requests
        requests += 1
        if always_reject or requests < 3:
            return httpx2.Response(
                429, json={"error": {"message": "Rate limited", "type": "rate_limit"}}
            )
        return httpx2.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4o-mini",
                "status": "completed",
                "output": [],
                "usage": {"input_tokens": 5, "output_tokens": 8, "total_tokens": 13},
            },
        )

    token = model_run.set((tenant, run))
    try:
        async with AsyncOpenAI(
            api_key="fixture",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        ) as client:
            if always_reject:
                with pytest.raises(Exception) as error:
                    await model_response(client, model="gpt-4o-mini", input="q")
                assert error.value.status_code == 429
            else:
                await model_response(client, model="gpt-4o-mini", input="q")
    finally:
        model_run.reset(token)
    usage, reservations, calls = await ledger(tenant, run)
    assert requests == 3 and len(calls) == 3
    assert [item.attempt for item in reservations] == [1, 2, 3]
    assert [item.state for item in reservations] == (
        ["released", "released", "released"]
        if always_reject
        else ["released", "released", "consumed"]
    )
    assert usage.reserved_estimated_cost_usd == 0
    assert usage.output_tokens == (0 if always_reject else 8)


@pytest.mark.parametrize("kind", ["timeout", "cancel", "500", "400"])
async def test_model_failure_settles_conservatively_without_unsafe_retry(kind):
    tenant, run = await seed()

    class Failure(Exception):
        status_code = int(kind) if kind.isdigit() else None

    error = (
        asyncio.CancelledError()
        if kind == "cancel"
        else httpx.ReadTimeout("private")
        if kind == "timeout"
        else Failure()
    )
    client = model_client(error=error)
    token = model_run.set((tenant, run))
    try:
        with pytest.raises(type(error)):
            await model_response(client, model="gpt-4o-mini", input="q")
    finally:
        model_run.reset(token)
    usage, reservations, calls = await ledger(tenant, run)
    expected = "released" if kind == "400" else "uncertain"
    assert reservations[0].state == expected
    assert calls[0].outcome == ("failed" if expected == "released" else "uncertain")
    assert client.responses.create.await_count == 1
    assert (usage.reserved_estimated_cost_usd > 0) is (expected == "uncertain")
    assert (usage.input_tokens > 0) is (expected == "uncertain")


@pytest.mark.parametrize("provider", ["openai", "tavily"])
async def test_persisted_cancellation_during_backoff_prevents_another_attempt(
    monkeypatch, provider
):
    tenant, run = await seed()

    async def cancel_during_backoff(_attempt):
        async with tenant_session(str(tenant)) as session:
            row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
            row.cancellation_requested_at = datetime.now(UTC)

    if provider == "openai":

        class RateLimited(Exception):
            status_code = 429

        client = model_client(error=RateLimited())
        monkeypatch.setattr(model_budget, "retry_delay", cancel_during_backoff)
        token = model_run.set((tenant, run))
        try:
            with pytest.raises(asyncio.CancelledError):
                await model_response(client, model="gpt-4o-mini", input="q")
        finally:
            model_run.reset(token)
        assert client.responses.create.await_count == 1
    else:
        count = 0

        def respond(request):
            nonlocal count
            count += 1
            raise httpx.ConnectError("not dispatched", request=request)

        monkeypatch.setattr(tavily, "retry_delay", cancel_during_backoff)
        async with httpx.AsyncClient(
            base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
        ) as client:
            ingestor = TavilyEvidenceIngestor(
                adapter=TavilyAdapter(api_key="fixture", client=client),
                artifact_store=InMemoryArtifactStore(),
            )
            with pytest.raises(asyncio.CancelledError):
                await ingestor.ingest(tenant_id=tenant, run_id=run, sub_question_id=None, query="q")
        assert count == 1
    usage, reservations, calls = await ledger(tenant, run)
    assert len(reservations) == len(calls) == 1 and reservations[0].state == "released"
    assert usage.reserved_estimated_cost_usd == usage.reserved_search_calls == 0


async def test_duplicate_evidence_at_full_ceiling_merges_provenance_without_new_source():
    tenant, run = await seed(6)
    first_done = asyncio.Event()

    async def respond(request):
        payload = json.loads(request.content)
        query = payload["query"]
        if request.url.path == "/search":
            if query == "second":
                await first_done.wait()
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": f"https://example.test/shared/{index}?utm_source={query}"}
                        for index in range(2)
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": url, "raw_content": "Shared evidence"} for url in payload["urls"]
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )

        async def collect_first():
            result = await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="first", quick_mode=True
            )
            first_done.set()
            return result

        first, second = await asyncio.gather(
            collect_first(),
            ingestor.ingest(
                tenant_id=tenant,
                run_id=run,
                sub_question_id=None,
                query="second",
                quick_mode=True,
            ),
        )
    assert set(first) == set(second) and len(second) == 2
    async with tenant_session(str(tenant)) as session:
        sources = list(await session.scalars(select(Source).where(Source.run_id == run)))
    assert len(sources) == 2
    assert all(len(source.discovery_paths) == 2 for source in sources)


async def test_graph_finishes_persisted_cancellation_during_model_backoff(monkeypatch):
    tenant, run = await seed()

    class RateLimited(Exception):
        status_code = 429

    client = model_client(error=RateLimited())
    client.close = AsyncMock()
    settings = Settings(OPENAI_API_KEY="fixture")
    monkeypatch.setattr(builder, "AsyncOpenAI", lambda **_: client)

    async def cancel_during_backoff(_attempt):
        async with tenant_session(str(tenant)) as session:
            row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
            row.cancellation_requested_at = datetime.now(UTC)

    monkeypatch.setattr(model_budget, "retry_delay", cancel_during_backoff)

    await builder.run_graph(
        settings, run_id=run, tenant_id=tenant, user_id=uuid.uuid4(), question="fixture"
    )
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        events = list(await session.scalars(select(RunEvent).where(RunEvent.run_id == run)))
        nodes = list(
            await session.scalars(select(NodeExecution).where(NodeExecution.run_id == run))
        )
    assert row.status == "cancelled" and row.cancelled_at is not None
    assert sum(item.event_type == "run.cancelled" for item in events) == 1
    assert any(node.node_id == "planner" and node.status == "cancelled" for node in nodes)
    usage, reservations, _ = await ledger(tenant, run)
    assert reservations[0].state == "released" and usage.reserved_estimated_cost_usd == 0
    client.responses.create.assert_awaited_once()
    client.close.assert_awaited_once()


async def test_cancellation_cleanup_cannot_regress_an_already_completed_run():
    tenant, run = await seed()
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        row.status = "completed"
        row.cancellation_requested_at = datetime.now(UTC)
    assert await builder._cancel_if_requested(tenant_id=tenant, run_id=run)
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
        assert row.status == "completed"


async def test_uncertain_reconciliation_requires_receipt_and_is_idempotent_and_tenant_scoped():
    tenant, run = await seed()
    async with tenant_session(str(tenant)) as session:
        repository = BudgetReservationRepository(session, tenant)
        reservation = await repository.reserve(
            run_id=run,
            provider="internal",
            operation="model",
            request_fingerprint="reconcile",
            estimated_cost_usd=Decimal("0.10"),
            search_calls=0,
            input_tokens=1000,
            output_tokens=4096,
        )
        reservation_id = reservation.id
        session.add(
            ProviderCall(
                tenant_id=tenant,
                run_id=run,
                reservation_id=reservation_id,
                provider="internal",
                operation="model",
                request_fingerprint="reconcile",
                request_schema_version="fixture",
                outcome="uncertain",
                started_at=datetime.now(UTC),
                provider_usage={
                    "accounting": {"reservedInputTokens": 1000, "reservedOutputTokens": 4096}
                },
            )
        )
        await repository.transition(reservation_id, new_state="uncertain")
    with pytest.raises(InvalidReservationTransitionError):
        async with tenant_session(str(tenant)) as session:
            await BudgetReservationRepository(session, tenant).reconcile_from_receipt(
                reservation_id
            )
    async with tenant_session(str(tenant)) as session:
        call = await session.scalar(
            select(ProviderCall).where(ProviderCall.reservation_id == reservation_id)
        )
        call.outcome, call.completed_at = "succeeded", datetime.now(UTC)
        call.provider_usage = {
            "accounting": {
                "reservedInputTokens": 1000,
                "reservedOutputTokens": 4096,
                "inputTokens": 5,
                "outputTokens": 8,
                "costUsd": "0.000006",
            }
        }
    for _ in range(2):
        async with tenant_session(str(tenant)) as session:
            await BudgetReservationRepository(session, tenant).reconcile_from_receipt(
                reservation_id
            )
    usage, reservations, _ = await ledger(tenant, run)
    assert usage.reserved_estimated_cost_usd == 0
    assert usage.estimated_cost_usd == Decimal("0.000006")
    assert (usage.input_tokens, usage.output_tokens) == (5, 8)
    assert reservations[0].state == "consumed"
    with pytest.raises(LookupError):
        async with tenant_session(str(uuid.uuid4())) as session:
            await BudgetReservationRepository(session, uuid.uuid4()).reconcile_from_receipt(
                reservation_id
            )


def tavily_transport(*, fail_source=False):
    def respond(request):
        payload = json.loads(request.content)
        if request.url.path == "/search":
            tag = payload["query"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": f"https://example.test/{tag}/{index}", "title": "Evidence"}
                        for index in range(6)
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "raw_content": (
                            "bad artifact" if fail_source and index == 0 else "Evidence " + url
                        ),
                    }
                    for index, url in enumerate(payload["urls"])
                ]
                + [{"url": "file:///invalid", "raw_content": "Rejected"}]
            },
        )

    return httpx.MockTransport(respond)


@pytest.mark.parametrize("ceiling,quick", [(6, False), (12, False), (20, False), (6, True)])
async def test_concurrent_ingestion_cannot_overshoot_persisted_source_ceiling(ceiling, quick):
    tenant, run = await seed(ceiling)
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=tavily_transport()
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
                    query=f"task-{index}",
                    max_results=6,
                    quick_mode=quick,
                )
                for index in range(min(ceiling // 2, 4))
            )
        )
    async with tenant_session(str(tenant)) as session:
        count = await session.scalar(
            select(func.count()).select_from(Source).where(Source.run_id == run)
        )
        events = list(await session.scalars(select(RunEvent).where(RunEvent.run_id == run)))
    assert count == (2 if quick else ceiling)
    assert len({item for result in results for item in result}) == count
    assert sorted(event.event_sequence for event in events) == list(range(1, count + 1))


async def test_partial_artifact_failure_preserves_healthy_sources_and_paid_calls():
    tenant, run = await seed()

    class Store(InMemoryArtifactStore):
        async def put(self, **kwargs):
            if kwargs["media_type"] == "application/json" or kwargs["content"] == b"bad artifact":
                raise OSError("storage unavailable")
            return await super().put(**kwargs)

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=tavily_transport(fail_source=True)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client), artifact_store=Store()
        )
        result = await ingestor.ingest(
            tenant_id=tenant, run_id=run, sub_question_id=None, query="partial"
        )
    usage, reservations, calls = await ledger(tenant, run)
    assert len(result) == 5 and usage.search_calls == 2
    assert all(item.state == "consumed" for item in reservations)
    assert all(item.outcome == "succeeded" and not item.response_artifact_ref for item in calls)


async def test_concurrent_identical_ingestion_does_not_repeat_search_or_extraction():
    tenant, run = await seed()
    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=tavily_transport()
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        results = await asyncio.gather(
            *(
                ingestor.ingest(tenant_id=tenant, run_id=run, sub_question_id=None, query="same")
                for _ in range(3)
            ),
            return_exceptions=True,
        )
    assert sum(isinstance(item, ReservationReplayError) for item in results) == 2
    usage, reservations, calls = await ledger(tenant, run)
    assert usage.search_calls == len(reservations) == len(calls) == 2


async def test_cancellation_after_search_prevents_extraction_and_source_events():
    tenant, run = await seed()
    requests = []

    async def respond(request):
        requests.append(request.url.path)
        async with tenant_session(str(tenant)) as session:
            row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run))
            row.cancellation_requested_at = datetime.now(UTC)
        return httpx.Response(200, json={"results": [{"url": "https://example.test/a"}]})

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(asyncio.CancelledError):
            await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="cancel"
            )
    usage, reservations, _ = await ledger(tenant, run)
    assert requests == ["/search"] and usage.search_calls == 1
    assert reservations[0].state == "consumed"
    async with tenant_session(str(tenant)) as session:
        assert not list(await session.scalars(select(RunEvent).where(RunEvent.run_id == run)))


@pytest.mark.parametrize("kind", ["cancel", "json", "timeout"])
async def test_ingestion_response_failures_do_not_leave_pending_reservations(kind):
    tenant, run = await seed()

    def respond(request):
        if kind == "cancel":
            raise asyncio.CancelledError
        if kind == "timeout":
            raise httpx.ReadTimeout("private", request=request)
        return httpx.Response(200, text="invalid JSON")

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client),
            artifact_store=InMemoryArtifactStore(),
        )
        with pytest.raises(asyncio.CancelledError if kind == "cancel" else TavilyRequestError):
            await ingestor.ingest(
                tenant_id=tenant, run_id=run, sub_question_id=None, query="failure"
            )
    usage, reservations, calls = await ledger(tenant, run)
    assert reservations[0].state == ("consumed" if kind == "json" else "uncertain")
    assert calls[0].outcome != "pending"
    assert (usage.reserved_search_calls == 1) is (kind != "json")
