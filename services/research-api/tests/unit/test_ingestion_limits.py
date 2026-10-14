import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api import ingestion
from research_api.artifacts.store import InMemoryArtifactStore
from research_api.db.models import Budget, ResearchRun


@pytest.mark.asyncio
async def test_extraction_rejects_unsolicited_and_duplicate_urls(monkeypatch) -> None:
    adapter = SimpleNamespace(
        search_request=lambda **kwargs: SimpleNamespace(operation="search"),
        extract_request=lambda **kwargs: SimpleNamespace(operation="extract"),
        search=AsyncMock(
            return_value=SimpleNamespace(
                results=[
                    SimpleNamespace(url="https://example.com/a", title="A", published_date=None)
                ],
                request_id=None,
                usage={},
                model_dump=lambda **kwargs: {},
            )
        ),
        extract=AsyncMock(
            return_value=SimpleNamespace(
                results=[
                    SimpleNamespace(url=url, raw_content="evidence")
                    for url in (
                        "https://other.example/unsolicited",
                        "https://example.com/a",
                        "https://example.com/a",
                    )
                ],
                request_id=None,
                usage={},
                model_dump=lambda **kwargs: {},
            )
        ),
    )

    @asynccontextmanager
    async def session(_tenant):
        async def scalar(statement):
            entity = statement.column_descriptions[0].get("entity")
            if entity is ResearchRun:
                return SimpleNamespace(status="researching", cancellation_requested_at=None)
            if entity is Budget:
                return SimpleNamespace(max_search_calls=6)
            return 0

        yield SimpleNamespace(scalar=scalar)

    upsert = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid.uuid4(),
            canonical_url="https://example.com/a",
            title="A",
            source_class="unknown",
        )
    )
    monkeypatch.setattr(ingestion, "tenant_session", session)
    monkeypatch.setattr(ingestion, "SourceRepository", lambda *args: SimpleNamespace(upsert=upsert))
    monkeypatch.setattr(ingestion, "EventOutbox", lambda *args: SimpleNamespace(append=AsyncMock()))
    ingestor = ingestion.TavilyEvidenceIngestor(
        adapter=adapter, artifact_store=InMemoryArtifactStore()
    )
    monkeypatch.setattr(ingestor, "_reserve", AsyncMock(return_value=uuid.uuid4()))
    monkeypatch.setattr(ingestor, "_finalize", AsyncMock())
    monkeypatch.setattr(ingestor, "_replay_response", AsyncMock(return_value=None))
    accepted = []

    async def persist(**kwargs):
        accepted.extend(item.canonical_url for item in kwargs["prepared"])
        return [uuid.uuid4()]

    monkeypatch.setattr(ingestor, "_persist_sources", AsyncMock(side_effect=persist))
    monkeypatch.setattr(
        ingestor,
        "_admit_extraction",
        AsyncMock(
            return_value=(
                SimpleNamespace(payload={"urls": ["https://example.com/a"]}),
                uuid.uuid4(),
                [],
                False,
            )
        ),
    )
    ids = await ingestor.ingest(
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        sub_question_id=None,
        query="test",
        max_results=2,
    )
    assert len(ids) == 1
    assert ingestor._persist_sources.await_count == 1
    assert accepted == ["https://example.com/a"]


@pytest.mark.asyncio
async def test_zero_slots_do_not_dispatch_a_provider_request() -> None:
    adapter = SimpleNamespace(search_request=AsyncMock())
    ingestor = ingestion.TavilyEvidenceIngestor(
        adapter=adapter, artifact_store=InMemoryArtifactStore()
    )
    assert (
        await ingestor.ingest(
            tenant_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            sub_question_id=None,
            query="test",
            max_results=0,
        )
        == []
    )
    adapter.search_request.assert_not_called()
