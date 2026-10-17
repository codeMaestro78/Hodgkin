import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.artifacts.store import artifact_identity
from research_api.ingestion import TavilyEvidenceIngestor
from research_api.providers.tavily import ExtractResponse, ExtractResult


@pytest.mark.asyncio
async def test_artifact_writes_are_bounded_concurrent_and_persist_in_source_order(monkeypatch):
    tenant_id, run_id = uuid.uuid4(), uuid.uuid4()

    class Store:
        active = 0
        peak = 0

        async def put(self, *, tenant_id, run_id, content, media_type):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return artifact_identity(
                tenant_id=tenant_id, run_id=run_id, content=content, media_type=media_type
            )

    store = Store()
    ingestor = TavilyEvidenceIngestor(adapter=SimpleNamespace(), artifact_store=store)
    monkeypatch.setattr(ingestor, "_check_cancelled", AsyncMock())
    saved = []

    async def persist(**kwargs):
        saved.extend(item.canonical_url for item in kwargs["prepared"])
        return [uuid.uuid4() for _ in kwargs["prepared"]]

    monkeypatch.setattr(ingestor, "_persist_sources", AsyncMock(side_effect=persist))
    urls = [f"https://example.test/{index}" for index in range(4)]
    source_ids = await ingestor._ingest_extract_results(
        tenant_id=tenant_id,
        run_id=run_id,
        sub_question_id=None,
        extract_response=ExtractResponse(
            results=[
                ExtractResult(url=url, raw_content=f"Evidence {i}") for i, url in enumerate(urls)
            ]
        ),
        admitted_urls=set(urls),
        cached_ids=[],
        titles={url: url for url in urls},
        original_urls={url: [url] for url in urls},
        publication_dates={},
        source_details={},
        max_results=4,
        quick_mode=False,
    )
    assert len(source_ids) == 4
    assert saved == urls
    assert 1 < store.peak <= 3


@pytest.mark.asyncio
async def test_artifact_write_cancellation_does_not_persist_source_metadata(monkeypatch):
    class CancelledStore:
        async def put(self, **_kwargs):
            raise asyncio.CancelledError

    ingestor = TavilyEvidenceIngestor(adapter=SimpleNamespace(), artifact_store=CancelledStore())
    monkeypatch.setattr(ingestor, "_check_cancelled", AsyncMock())
    persist = AsyncMock()
    monkeypatch.setattr(ingestor, "_persist_sources", persist)
    url = "https://example.test/cancelled"
    with pytest.raises(asyncio.CancelledError):
        await ingestor._ingest_extract_results(
            tenant_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            sub_question_id=None,
            extract_response=ExtractResponse(
                results=[ExtractResult(url=url, raw_content="Evidence")]
            ),
            admitted_urls={url},
            cached_ids=[],
            titles={url: "Test"},
            original_urls={url: [url]},
            publication_dates={},
            source_details={},
            max_results=1,
            quick_mode=False,
        )
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_artifact_write_cancellation_stops_sibling_writes(monkeypatch):
    class Store:
        sibling_cancelled = False

        async def put(self, *, content, **_kwargs):
            if content.endswith(b"0"):
                await asyncio.sleep(0)
                raise asyncio.CancelledError
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.sibling_cancelled = True
                raise

    store = Store()
    ingestor = TavilyEvidenceIngestor(adapter=SimpleNamespace(), artifact_store=store)
    monkeypatch.setattr(ingestor, "_check_cancelled", AsyncMock())
    persist = AsyncMock()
    monkeypatch.setattr(ingestor, "_persist_sources", persist)
    urls = [f"https://example.test/{i}" for i in range(2)]
    with pytest.raises(asyncio.CancelledError):
        await ingestor._ingest_extract_results(
            tenant_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            sub_question_id=None,
            extract_response=ExtractResponse(
                results=[
                    ExtractResult(url=url, raw_content=f"Evidence {i}")
                    for i, url in enumerate(urls)
                ]
            ),
            admitted_urls=set(urls),
            cached_ids=[],
            titles={url: "Test" for url in urls},
            original_urls={url: [url] for url in urls},
            publication_dates={},
            source_details={},
            max_results=2,
            quick_mode=False,
        )
    assert store.sibling_cancelled
    persist.assert_not_awaited()
