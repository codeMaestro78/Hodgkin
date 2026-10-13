import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api import ingestion
from research_api.artifacts.store import InMemoryArtifactStore


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
        yield SimpleNamespace(scalar=AsyncMock())

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
    ids = await ingestor.ingest(
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        sub_question_id=None,
        query="test",
        max_results=2,
    )
    assert len(ids) == 1
    assert upsert.await_count == 1
    assert upsert.call_args.kwargs["canonical_url"] == "https://example.com/a"


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
