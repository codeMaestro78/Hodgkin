"""Real loopback PostgreSQL; provider transport and artifact storage never use the network."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import ingestion
from research_api.artifacts.store import InMemoryArtifactStore
from research_api.db import session as db_session
from research_api.db.models import (
    Budget,
    ExtractionSlot,
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
from research_api.events.outbox import EventOutbox
from research_api.ingestion import (
    ProviderRecoveryNeededError,
    TavilyEvidenceIngestor,
    _PreparedSource,
)
from research_api.providers.tavily import TavilyAdapter
from research_api.repositories.runs import RunBudgetDefaults, RunRepository
from research_api.repositories.sources import SourceRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def run_context():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Ingestion persistence test"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
        async with tenant_session(str(tenant)) as session:
            run = await RunRepository(session, tenant).create(
                user_id=user,
                question="Compare evidence from multiple sources",
                budget=RunBudgetDefaults(max_search_calls=20),
            )
            run_id = run.id
        yield tenant, run_id
    finally:
        # Delete only this fixture's tenant records, in FK dependency order.
        async with async_sessionmaker(engine)() as session, session.begin():
            for model in (
                RunEvent,
                Source,
                ExtractionSlot,
                ProviderCall,
                ProviderCallReservation,
                UsageLedger,
                Budget,
                ResearchRun,
                User,
            ):
                await session.execute(delete(model).where(model.tenant_id == tenant))
            await session.execute(delete(Tenant).where(Tenant.id == tenant))
        await engine.dispose()


@asynccontextmanager
async def mock_ingestor(count=6, store=None, extra_results=False):
    fetched = []

    def respond(request):
        import json

        payload = json.loads(request.content)
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": f"https://example.test/{index}", "title": f"Source {index}"}
                        for index in range(count)
                    ]
                },
            )
        fetched.extend(payload["urls"])
        results = [{"url": url, "raw_content": "Evidence " + url} for url in payload["urls"]]
        if extra_results:
            results += [results[0], {"url": "https://example.test/unadmitted", "raw_content": "X"}]
        return httpx.Response(200, json={"results": results})

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        adapter = TavilyAdapter(api_key="fixture", client=client)
        if count > 6:
            # Synthetic larger batches exercise the local transaction bound;
            # the production adapter's six-result dispatch cap is untouched.
            original_request = adapter.search_request

            def search_request(**kwargs):
                request = original_request(**kwargs)
                request.payload["max_results"] = count
                return request

            adapter.search_request = search_request
        yield (
            TavilyEvidenceIngestor(
                adapter=adapter,
                artifact_store=store or InMemoryArtifactStore(),
            ),
            fetched,
        )


async def ingest(ingestor, context, query="fixture", **kwargs):
    tenant, run = context
    return await ingestor.ingest(
        tenant_id=tenant, run_id=run, sub_question_id=None, query=query, **kwargs
    )


async def durable(context):
    tenant, run = context
    async with tenant_session(str(tenant)) as session:
        sources = list(await session.scalars(select(Source).where(Source.run_id == run)))
        events = list(
            await session.scalars(
                select(RunEvent).where(RunEvent.run_id == run).order_by(RunEvent.event_sequence)
            )
        )
        slots = list(
            await session.scalars(select(ExtractionSlot).where(ExtractionSlot.run_id == run))
        )
        reservations = list(
            await session.scalars(
                select(ProviderCallReservation).where(ProviderCallReservation.run_id == run)
            )
        )
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        calls = list(await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run)))
    return sources, events, slots, reservations, usage, calls


def assert_paid(snapshot, fetched_count):
    _, _, slots, reservations, usage, calls = snapshot
    assert len(slots) == fetched_count
    assert all(slot.state == "consumed" for slot in slots)
    assert len(reservations) == len(calls) == 2
    assert all(reservation.state == "consumed" for reservation in reservations)
    assert all(call.outcome == "succeeded" for call in calls)
    assert usage.search_calls == 2
    assert usage.reserved_search_calls == 0
    assert usage.estimated_cost_usd == Decimal("0.016")


@pytest.mark.parametrize("failure", ["source", "event"])
async def test_integrity_failure_rolls_back_only_one_source_and_event(
    run_context, monkeypatch, failure
):
    original_upsert, original_append = SourceRepository.upsert, EventOutbox.append
    first_event = None

    async def upsert(self, **kwargs):
        if kwargs["canonical_url"].endswith("/1") and failure == "source":
            # A real FK violation leaves PostgreSQL aborted until savepoint rollback.
            kwargs["sub_question_id"] = uuid.uuid4()
        return await original_upsert(self, **kwargs)

    async def append(self, **kwargs):
        nonlocal first_event
        if kwargs["payload"]["source"]["canonicalUrl"].endswith("/1") and failure == "event":
            kwargs["event_id"] = first_event
        result = await original_append(self, **kwargs)
        first_event = first_event or result.event_id
        return result

    monkeypatch.setattr(SourceRepository, "upsert", upsert)
    monkeypatch.setattr(EventOutbox, "append", append)
    async with mock_ingestor(extra_results=True) as (ingestor, fetched):
        ids = await ingest(ingestor, run_context)
    snapshot = await durable(run_context)
    sources, events, *_ = snapshot
    assert len(ids) == len(sources) == len(events) == 5
    assert set(ids) == {source.id for source in sources}
    assert all(not source.canonical_url.endswith("/1") for source in sources)
    assert [entry.event_sequence for entry in events] == list(range(1, 6))
    assert {entry.payload["source"]["id"] for entry in events} == {str(id_) for id_ in ids}
    assert len(fetched) == 6
    assert_paid(snapshot, 6)


@pytest.mark.parametrize("failure", ["storage", "cancel_artifact", "cancel_metadata", "db"])
async def test_failure_and_cancellation_preserve_paid_settlement(run_context, monkeypatch, failure):
    class Store(InMemoryArtifactStore):
        async def put(self, **kwargs):
            if kwargs["media_type"].startswith("text/") and kwargs["content"].endswith(b"/1"):
                if failure == "storage":
                    raise OSError("fixture artifact failure")
                if failure == "cancel_artifact":
                    raise asyncio.CancelledError
            return await super().put(**kwargs)

    original = SourceRepository.upsert

    async def upsert(self, **kwargs):
        if kwargs["canonical_url"].endswith("/1"):
            if failure == "cancel_metadata":
                raise asyncio.CancelledError
            if failure == "db":
                raise ConnectionError("fixture database disconnect")
        return await original(self, **kwargs)

    monkeypatch.setattr(SourceRepository, "upsert", upsert)
    async with mock_ingestor(store=Store()) as (ingestor, fetched):
        if failure == "storage":
            assert len(await ingest(ingestor, run_context)) == 5
        else:
            with pytest.raises(ConnectionError if failure == "db" else asyncio.CancelledError):
                await ingest(ingestor, run_context)
    snapshot = await durable(run_context)
    assert len(snapshot[0]) == len(snapshot[1]) == (5 if failure == "storage" else 0)
    assert len(fetched) == 6
    assert_paid(snapshot, 6)


async def test_metadata_commit_failure_returns_no_ids(run_context, monkeypatch):
    original = ingestion.tenant_session

    @asynccontextmanager
    async def fail_commit(tenant):
        async with original(tenant) as session:
            yield session
            # A failure leaving the transaction must roll back the whole batch.
            raise ConnectionError("fixture commit failure")

    async with mock_ingestor() as (ingestor, _):
        original_persist = ingestor._persist_sources

        async def persist(**kwargs):
            with monkeypatch.context() as patch:
                patch.setattr(ingestion, "tenant_session", fail_commit)
                return await original_persist(**kwargs)

        monkeypatch.setattr(ingestor, "_persist_sources", persist)
        with pytest.raises(ConnectionError):
            await ingest(ingestor, run_context)
    snapshot = await durable(run_context)
    assert snapshot[0] == snapshot[1] == []
    assert_paid(snapshot, 6)


async def test_cached_discovery_integrity_failure_is_isolated(run_context, monkeypatch):
    original = SourceRepository.upsert
    async with mock_ingestor() as (ingestor, fetched):
        assert len(await ingest(ingestor, run_context)) == 6

        async def upsert(self, **kwargs):
            source = await original(self, **kwargs)
            if kwargs["canonical_url"].endswith("/1"):
                source.title = None  # Real NOT NULL error on the cached update.
            return source

        monkeypatch.setattr(SourceRepository, "upsert", upsert)
        assert len(await ingest(ingestor, run_context, query="cached")) == 5
        assert len(fetched) == 6  # No extraction/refetch after discovery failure.
    sources, events, slots, reservations, usage, _ = await durable(run_context)
    assert len(sources) == len(events) == len(slots) == 6
    assert all(source.title is not None for source in sources)
    assert all(slot.state == "consumed" for slot in slots)
    assert len(reservations) == 3 and all(row.state == "consumed" for row in reservations)
    assert usage.search_calls == 3


async def test_cancellation_after_committed_batch_preserves_only_that_batch(run_context):
    class Store(InMemoryArtifactStore):
        async def put(self, **kwargs):
            if kwargs["media_type"].startswith("text/") and kwargs["content"].endswith(b"/8"):
                raise asyncio.CancelledError
            return await super().put(**kwargs)

    async with mock_ingestor(count=10, store=Store()) as (ingestor, _):
        with pytest.raises(asyncio.CancelledError):
            await ingest(ingestor, run_context, max_results=10)
    snapshot = await durable(run_context)
    assert len(snapshot[0]) == len(snapshot[1]) == 8
    assert_paid(snapshot, 10)


@pytest.mark.parametrize("count", [6, 10])
async def test_bounded_batches_reduce_metadata_statements_and_keep_io_outside_transaction(
    run_context, monkeypatch, count
):
    statements, batch_sizes = [], []
    in_metadata = False

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if in_metadata:
            statements.append(statement)

    class Store(InMemoryArtifactStore):
        async def put(self, **kwargs):
            assert not in_metadata
            return await super().put(**kwargs)

    event.listen(db_session.engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with mock_ingestor(count=count, store=Store()) as (ingestor, _):
            original = ingestor._persist_sources

            async def persist(**kwargs):
                nonlocal in_metadata
                batch_sizes.append(len(kwargs["prepared"]))
                in_metadata = True
                try:
                    return await original(**kwargs)
                finally:
                    in_metadata = False

            monkeypatch.setattr(ingestor, "_persist_sources", persist)
            assert len(await ingest(ingestor, run_context, max_results=count)) == count
    finally:
        event.remove(db_session.engine.sync_engine, "before_cursor_execute", capture)
    batches = (count + 7) // 8
    assert batch_sizes == ([6] if count == 6 else [8, 2])
    assert len(statements) == 5 * batches + 6 * count
    assert sum("set_config" in sql for sql in statements) == batches
    assert sum(sql.startswith("SAVEPOINT") for sql in statements) == count
    assert sum(sql.startswith("RELEASE SAVEPOINT") for sql in statements) == count


def prepared(index):
    url = f"https://example.test/{index}"
    return _PreparedSource(url, url, f"{index:064x}", f"fixture/{index}", [])


async def persist(ingestor, context, items, quick=False):
    tenant, run = context
    return await ingestor._persist_sources(
        tenant_id=tenant,
        run_id=run,
        sub_question_id=None,
        prepared=items,
        titles={},
        original_urls={},
        publication_dates={},
        quick_mode=quick,
    )


async def test_parallel_metadata_batches_enforce_ceiling_and_unique_sources(run_context):
    tenant, run = run_context
    async with tenant_session(str(tenant)) as session:
        await session.execute(
            Budget.__table__.update().where(Budget.run_id == run).values(max_search_calls=6)
        )
    async with mock_ingestor() as (ingestor, _):
        results = await asyncio.wait_for(
            asyncio.gather(
                persist(ingestor, run_context, [prepared(i) for i in range(6)]),
                persist(ingestor, run_context, [prepared(i) for i in range(3, 9)]),
            ),
            timeout=10,
        )
    sources, events, *_ = await durable(run_context)
    assert len(sources) == 6
    assert len({(source.canonical_url, source.content_hash) for source in sources}) == 6
    assert set(results[0]) & set(results[1])
    assert {id_ for result in results for id_ in result} == {source.id for source in sources}
    assert [entry.event_sequence for entry in events] == list(range(1, len(events) + 1))


async def test_quick_ceiling_and_cancellation_at_metadata_lock(run_context):
    tenant, run = run_context
    async with mock_ingestor() as (ingestor, _):
        assert len(await persist(ingestor, run_context, [prepared(i) for i in range(6)], True)) == 2
        # Existing identities may still be reused at the ceiling.
        assert len(await persist(ingestor, run_context, [prepared(0)], True)) == 1
        async with tenant_session(str(tenant)) as session:
            record = await session.get(ResearchRun, run)
            record.cancellation_requested_at = datetime.now(UTC)
        with pytest.raises(asyncio.CancelledError):
            await persist(ingestor, run_context, [prepared(7)])
    assert len((await durable(run_context))[0]) == 2


async def test_metadata_batch_bound_and_missing_tenant_run(run_context):
    async with mock_ingestor() as (ingestor, _):
        with pytest.raises(ValueError, match="transaction bound"):
            await persist(ingestor, run_context, [prepared(i) for i in range(9)])
        with pytest.raises(LookupError, match="research run missing"):
            await persist(ingestor, (uuid.uuid4(), run_context[1]), [prepared(0)])
    assert (await durable(run_context))[0] == []


async def test_repository_prefetch_is_tenant_scoped_and_merges_bounded_discovery(run_context):
    tenant, run = run_context
    async with mock_ingestor() as (ingestor, _):
        await persist(ingestor, run_context, [prepared(0)])
    async with tenant_session(str(tenant)) as session:
        repository = SourceRepository(session, tenant)
        existing = await repository.find_existing(
            run_id=run,
            identities=[
                (prepared(0).canonical_url, prepared(0).content_hash),
            ],
        )
        source = existing[(prepared(0).canonical_url, prepared(0).content_hash)]
        result = await repository.upsert(
            run_id=run,
            sub_question_id=None,
            canonical_url=source.canonical_url,
            title=source.title,
            provider="tavily",
            source_class="unknown",
            retrieved_at=source.retrieved_at,
            content_hash=source.content_hash,
            artifact_ref=source.artifact_ref,
            original_urls=[f"https://example.test/0?discovery={i}" for i in range(40)],
            existing_source=source,
        )
        assert result.id == source.id
        assert len(result.discovery_paths) == 32
        # Standalone upsert retains its original lookup, and remains idempotent.
        repeated = await repository.upsert(
            run_id=run,
            sub_question_id=None,
            canonical_url=source.canonical_url,
            title=source.title,
            provider="tavily",
            source_class="unknown",
            retrieved_at=source.retrieved_at,
            content_hash=source.content_hash,
            artifact_ref=source.artifact_ref,
        )
        assert repeated.id == source.id
        assert len(repeated.discovery_paths) == 32
        other = SourceRepository(session, uuid.uuid4())
        assert await other.find_existing(run_id=run, identities=list(existing)) == {}
        with pytest.raises(ValueError, match="tenant/run/content identity"):
            await other.upsert(
                run_id=run,
                sub_question_id=None,
                canonical_url=source.canonical_url,
                title=source.title,
                provider="tavily",
                source_class="unknown",
                retrieved_at=source.retrieved_at,
                content_hash=source.content_hash,
                artifact_ref=source.artifact_ref,
                existing_source=source,
            )


@pytest.mark.parametrize("failed_count", [1, 6])
async def test_successful_receipts_recover_missing_sources_without_provider_redispatch(
    run_context, monkeypatch, failed_count
):
    original = SourceRepository.upsert

    async def fail(self, **kwargs):
        if failed_count == 6 or kwargs["canonical_url"].endswith("/1"):
            kwargs["sub_question_id"] = uuid.uuid4()
        return await original(self, **kwargs)

    async with mock_ingestor() as (ingestor, fetched):
        with monkeypatch.context() as patch:
            patch.setattr(SourceRepository, "upsert", fail)
            first = await ingest(ingestor, run_context)
        assert len(first) == 6 - failed_count
        monkeypatch.setattr(
            ingestor._adapter, "search", AsyncMock(side_effect=AssertionError("paid search"))
        )
        monkeypatch.setattr(
            ingestor._adapter, "extract", AsyncMock(side_effect=AssertionError("paid extract"))
        )
        recovered = await ingest(ingestor, run_context)
        assert len(recovered) == len(set(recovered)) == 6
        assert set(first) <= set(recovered)
        assert len(fetched) == 6
    snapshot = await durable(run_context)
    assert len(snapshot[0]) == 6
    assert_paid(snapshot, 6)


@pytest.mark.parametrize("trim", ["cached", "quota", "cached_and_quota"])
async def test_trimmed_extraction_receipt_recovers_without_new_paid_calls(run_context, trim):
    import json

    tenant, run = run_context
    if trim != "cached":
        async with tenant_session(str(tenant)) as session:
            await session.execute(
                Budget.__table__.update().where(Budget.run_id == run).values(max_search_calls=6)
            )
    requests = []

    class Store(InMemoryArtifactStore):
        interrupted = False

        async def put(self, **kwargs):
            if self.interrupted and kwargs["media_type"].startswith("text/"):
                raise asyncio.CancelledError
            return await super().put(**kwargs)

    store = Store()

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path == "/search":
            indices = (
                list(range(5))
                if payload["query"] == "seed" and trim != "cached"
                else [0]
                if payload["query"] == "seed"
                else [5, 6, 7]
                if trim == "quota"
                else [0, 5, 6]
            )
            return httpx.Response(
                200, json={"results": [{"url": f"https://example.test/{i}"} for i in indices]}
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": url, "raw_content": "Evidence " + url} for url in payload["urls"]
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.tavily.com", transport=httpx.MockTransport(respond)
    ) as client:
        ingestor = TavilyEvidenceIngestor(
            adapter=TavilyAdapter(api_key="fixture", client=client), artifact_store=store
        )
        seeded = await ingest(ingestor, run_context, query="seed", max_results=5)
        store.interrupted = True
        with pytest.raises(asyncio.CancelledError):
            await ingest(ingestor, run_context, max_results=3)
        before = await durable(run_context)
        store.interrupted = False
        recovered = await ingest(ingestor, run_context, max_results=3)
        repeated = await ingest(ingestor, run_context, max_results=3)
    expected = 3 if trim == "cached" else 1 if trim == "quota" else 2
    assert len(set(recovered)) == expected
    assert set(repeated) == set(recovered)
    assert len(requests) == 4
    if trim != "quota":
        assert set(seeded) & set(recovered)
    after = await durable(run_context)
    assert len(after[0]) == (3 if trim == "cached" else 6)
    assert after[4].search_calls == before[4].search_calls == 4
    assert after[4].estimated_cost_usd == before[4].estimated_cost_usd
    assert {row.id for row in after[3]} == {row.id for row in before[3]}


@pytest.mark.parametrize("damage", ["query", "receipt"])
async def test_extraction_recovery_keeps_exact_request_and_receipt_checks(run_context, damage):
    class Store(InMemoryArtifactStore):
        interrupted = True

        async def put(self, **kwargs):
            if self.interrupted and kwargs["media_type"].startswith("text/"):
                raise asyncio.CancelledError
            return await super().put(**kwargs)

    store = Store()
    tenant, run = run_context
    async with mock_ingestor(store=store) as (ingestor, fetched):
        with pytest.raises(asyncio.CancelledError):
            await ingest(ingestor, run_context)
        before = await durable(run_context)
        store.interrupted = False
        if damage == "query":
            ingestor._adapter.extract_request = lambda **kwargs: TavilyAdapter.extract_request(
                **{**kwargs, "query": "Changed extraction request"}
            )
        else:
            async with tenant_session(str(tenant)) as session:
                call = await session.scalar(
                    select(ProviderCall).where(
                        ProviderCall.tenant_id == tenant,
                        ProviderCall.run_id == run,
                        ProviderCall.operation == "extract",
                    )
                )
                call.response_artifact_ref = None
        with pytest.raises(ProviderRecoveryNeededError, match="recovery-needed"):
            await ingest(ingestor, run_context)
        assert len(fetched) == 6
    after = await durable(run_context)
    assert after[0] == []
    assert after[4].search_calls == before[4].search_calls == 2
    assert after[4].estimated_cost_usd == before[4].estimated_cost_usd
    assert {row.id for row in after[3]} == {row.id for row in before[3]}


@pytest.mark.parametrize("state", ["reserved", "uncertain"])
async def test_unresolved_attempt_without_trusted_receipt_fails_recovery_needed(
    run_context, monkeypatch, state
):
    tenant, run = run_context
    async with mock_ingestor() as (ingestor, fetched):
        request = ingestor._adapter.search_request(query="fixture", max_results=6)
        reservation = await ingestor._reserve(
            tenant_id=tenant, run_id=run, request=request, estimated_cost=Decimal("0.008")
        )
        if state == "uncertain":
            await ingestor._finalize(
                tenant_id=tenant,
                reservation_id=reservation,
                state="uncertain",
                response_schema_version=None,
                provider_request_id=None,
            )
        monkeypatch.setattr(
            ingestor._adapter, "search", AsyncMock(side_effect=AssertionError("paid search"))
        )
        with pytest.raises(ProviderRecoveryNeededError, match="recovery-needed"):
            await ingest(ingestor, run_context)
        assert fetched == []
    snapshot = await durable(run_context)
    assert snapshot[0] == snapshot[1] == []
    assert len(snapshot[3]) == 1 and snapshot[3][0].state == state
    assert snapshot[4].reserved_search_calls == 1
    assert snapshot[4].search_calls == 0


@pytest.mark.parametrize("damage", ["missing", "corrupt", "scope", "schema", "cancel_read"])
async def test_unusable_success_receipt_never_redispatches_or_refunds(
    run_context, monkeypatch, damage
):
    tenant, run = run_context
    store = InMemoryArtifactStore()
    async with mock_ingestor(store=store) as (ingestor, fetched):
        await ingest(ingestor, run_context)
        async with tenant_session(str(tenant)) as session:
            call = await session.scalar(
                select(ProviderCall).where(
                    ProviderCall.run_id == run, ProviderCall.operation == "search"
                )
            )
            reference = call.response_artifact_ref
            if damage == "missing":
                call.response_artifact_ref = None
            elif damage == "scope":
                call.response_artifact_ref = f"tenants/{uuid.uuid4()}/runs/{run}/sha256/invalid"
            elif damage == "schema":
                call.response_schema_version = "unsupported"
        if damage == "corrupt":
            store._objects[reference] = b"{}"
        if damage == "cancel_read":
            monkeypatch.setattr(
                store, "get_for_verification", AsyncMock(side_effect=asyncio.CancelledError)
            )
        monkeypatch.setattr(
            ingestor._adapter, "search", AsyncMock(side_effect=AssertionError("paid search"))
        )
        with pytest.raises(
            asyncio.CancelledError if damage == "cancel_read" else ProviderRecoveryNeededError
        ):
            await ingest(ingestor, run_context)
        assert len(fetched) == 6
    snapshot = await durable(run_context)
    assert len(snapshot[0]) == 6
    assert_paid(snapshot, 6)


@pytest.mark.parametrize("state", ["reserved", "uncertain"])
async def test_trusted_extract_receipt_reconciles_unresolved_accounting_without_refetch(
    run_context, monkeypatch, state
):
    tenant, run = run_context
    original = SourceRepository.upsert

    async def fail(self, **kwargs):
        kwargs["sub_question_id"] = uuid.uuid4()
        return await original(self, **kwargs)

    async with mock_ingestor() as (ingestor, fetched):
        with monkeypatch.context() as patch:
            patch.setattr(SourceRepository, "upsert", fail)
            assert await ingest(ingestor, run_context) == []
        # Simulate a durable success receipt whose terminal accounting has not
        # been committed. Replay must settle once, retaining all fetch quota.
        async with tenant_session(str(tenant)) as session:
            reservation = await session.scalar(
                select(ProviderCallReservation).where(
                    ProviderCallReservation.run_id == run,
                    ProviderCallReservation.operation == "extract",
                )
            )
            reservation.state = state
            usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
            usage.search_calls = usage.reserved_search_calls = 1
            usage.estimated_cost_usd = usage.reserved_estimated_cost_usd = Decimal("0.008")
            await session.execute(
                ExtractionSlot.__table__.update()
                .where(ExtractionSlot.run_id == run)
                .values(state=state)
            )
        monkeypatch.setattr(
            ingestor._adapter, "search", AsyncMock(side_effect=AssertionError("paid search"))
        )
        monkeypatch.setattr(
            ingestor._adapter, "extract", AsyncMock(side_effect=AssertionError("paid extract"))
        )
        assert len(await ingest(ingestor, run_context)) == 6
        assert len(await ingest(ingestor, run_context)) == 6
        assert len(fetched) == 6
    assert_paid(await durable(run_context), 6)


async def test_receipt_artifact_reads_happen_outside_tenant_transaction(run_context, monkeypatch):
    active = 0
    original = ingestion.tenant_session

    @asynccontextmanager
    async def tracked(tenant):
        nonlocal active
        async with original(tenant) as session:
            active += 1
            try:
                yield session
            finally:
                active -= 1

    class Store(InMemoryArtifactStore):
        async def get_for_verification(self, **kwargs):
            assert active == 0
            return await super().get_for_verification(**kwargs)

    monkeypatch.setattr(ingestion, "tenant_session", tracked)
    async with mock_ingestor(store=Store()) as (ingestor, _):
        first = await ingest(ingestor, run_context)
        assert set(await ingest(ingestor, run_context)) == set(first)


@pytest.mark.parametrize("count", [3, 7])
async def test_inexact_extraction_reconstruction_requires_recovery_without_new_fetch(
    run_context, monkeypatch, count
):
    original = SourceRepository.upsert
    store = InMemoryArtifactStore()

    async def fail(self, **kwargs):
        kwargs["sub_question_id"] = uuid.uuid4()
        return await original(self, **kwargs)

    async with mock_ingestor(store=store) as (ingestor, fetched):
        with monkeypatch.context() as patch:
            patch.setattr(SourceRepository, "upsert", fail)
            assert await ingest(ingestor, run_context) == []
        assert len(fetched) == 6
    async with mock_ingestor(count=count, store=store) as (ingestor, fetched):
        with pytest.raises(ProviderRecoveryNeededError, match="recovery-needed"):
            tenant, run = run_context
            await ingestor._admit_extraction(
                tenant_id=tenant,
                run_id=run,
                sub_question_id=None,
                query="changed",
                titles={f"https://example.test/{i}": f"Source {i}" for i in range(count)},
                original_urls={},
                quick_mode=False,
                recovery=True,
            )
        assert fetched == []
    _, _, slots, reservations, usage, calls = await durable(run_context)
    # Even mixed new/blocked URLs cannot commit fresh fetch slots on failure.
    assert len(slots) == 6 and all(slot.state == "consumed" for slot in slots)
    assert len(reservations) == len(calls) == usage.search_calls == 2
    assert all(row.state == "consumed" for row in reservations)
