import asyncio
from dataclasses import replace

import httpx
import pytest

from research_api.providers.semantic_scholar import (
    GRAPH_FIELDS,
    PAPER_FIELDS,
    SemanticScholarAdapter,
    SemanticScholarCancelledAfterDispatch,
    SemanticScholarCancelledBeforeDispatch,
    SemanticScholarRequestError,
)

PAPER_A = "a" * 40
PAPER_B = "b" * 40


def paper(paper_id=PAPER_A, **overrides):
    return {
        "paperId": paper_id,
        "title": "A research paper",
        "authors": [{"name": "Ada Researcher"}],
        "year": 2024,
        "publicationDate": "2024-03-10",
        "externalIds": {"DOI": "https://doi.org/10.1234/Example.7"},
        "venue": "Example Journal",
        "citationCount": 12,
        "abstract": "Discovery metadata, not evidence.",
        "url": "https://www.semanticscholar.org/paper/example",
        "openAccessPdf": {"url": "https://repository.example/paper.pdf"},
        **overrides,
    }


def test_request_identity_and_validation():
    request = SemanticScholarAdapter.search_request(query="  ledger durability  ", limit=3)
    assert request == SemanticScholarAdapter.search_request(query="ledger durability", limit=3)
    assert request.payload == {"query": "ledger durability", "limit": 3, "fields": PAPER_FIELDS}
    assert request.request_schema_version == "semantic-scholar-graph-v1"
    citation = SemanticScholarAdapter.graph_request(
        paper_id=PAPER_A.upper(), direction="citations", limit=5, offset=2
    )
    assert citation.payload == {
        "paper_id": PAPER_A, "direction": "citations", "limit": 5,
        "offset": 2, "fields": GRAPH_FIELDS,
    }
    assert citation.fingerprint != SemanticScholarAdapter.graph_request(
        paper_id=PAPER_A, direction="references", limit=5, offset=2
    ).fingerprint
    for kwargs in ({"query": " "}, {"query": "x" * 1001},
                   {"query": "ok", "limit": 0}, {"query": "ok", "limit": True}):
        with pytest.raises(ValueError):
            SemanticScholarAdapter.search_request(**kwargs)
    for kwargs in ({"paper_id": "bad", "direction": "citations"},
                   {"paper_id": PAPER_A, "direction": "other"},
                   {"paper_id": PAPER_A, "direction": "references", "offset": -1},
                   {"paper_id": PAPER_A, "direction": "references", "limit": 11}):
        with pytest.raises(ValueError):
            SemanticScholarAdapter.graph_request(**kwargs)


async def test_search_normalizes_metadata_and_uses_header_auth():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/graph/v1/paper/search"
        assert request.headers["x-api-key"] == "secret"
        assert "secret" not in str(request.url)
        assert request.url.params["fields"] == PAPER_FIELDS
        return httpx.Response(200, json={"total": 2, "data": [paper(), None]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SemanticScholarAdapter(api_key="secret", client=client)
        result = await adapter.search(adapter.search_request(query="ledger"))
        await adapter.aclose()
        assert not client.is_closed
    assert result.total_count == 2
    assert result.attempt_count == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.paper_id == PAPER_A
    assert candidate.doi == "10.1234/example.7"
    assert candidate.authors == ("Ada Researcher",)
    assert candidate.citation_count == 12
    assert candidate.pdf_url == "https://repository.example/paper.pdf"
    assert "content" not in candidate.model_dump()
    assert "verified" not in candidate.model_dump()


@pytest.mark.parametrize("direction,nested,source,target", [
    ("citations", "citingPaper", PAPER_B, PAPER_A),
    ("references", "citedPaper", PAPER_A, PAPER_B),
])
async def test_graph_links_have_correct_direction_and_no_evidence(
    direction, nested, source, target
):
    def handler(request):
        assert request.url.path == f"/graph/v1/paper/{PAPER_A}/{direction}"
        assert request.url.params["fields"] == GRAPH_FIELDS
        assert "paper_id" not in request.url.params
        return httpx.Response(200, json={
            "offset": 0, "next": 2,
            "data": [{nested: paper(PAPER_B)}, {nested: {"paperId": "bad"}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client)
        result = await adapter.graph(adapter.graph_request(
            paper_id=PAPER_A, direction=direction, limit=2
        ))
    assert len(result.links) == 1
    assert (result.links[0].source_paper_id, result.links[0].target_paper_id) == (
        source, target
    )
    assert result.links[0].related_paper.paper_id == PAPER_B
    assert "content" not in result.links[0].related_paper.model_dump()
    assert result.next_offset == 2


async def test_tampered_request_is_rejected_before_network():
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client)
        request = adapter.search_request(query="test")
        with pytest.raises(ValueError):
            await adapter.search(replace(request, payload={**request.payload, "limit": 10}))
        graph = adapter.graph_request(paper_id=PAPER_A, direction="citations")
        with pytest.raises(ValueError):
            await adapter.graph(replace(graph, payload={**graph.payload, "fields": "contexts"}))
    assert calls == 0


@pytest.mark.parametrize("body", [{"data": {}}, [], {"total": 1}])
async def test_invalid_envelope_is_consumed_not_empty(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client)
        with pytest.raises(SemanticScholarRequestError) as error:
            await adapter.search(adapter.search_request(query="test"))
    assert error.value.outcome == "consumed"


async def test_malformed_metadata_is_sanitized_or_dropped():
    unsafe = paper()
    unsafe["url"] = "javascript:alert(1)"
    unsafe["openAccessPdf"] = {"url": "https://user:pass@example.org/file.pdf"}
    unsafe["citationCount"] = True
    unsafe["externalIds"] = {"DOI": "not-a-doi"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "total": 2, "data": [unsafe, {"paperId": "bad", "title": "Bad"}],
        }))
    ) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client)
        result = await adapter.search(adapter.search_request(query="test"))
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.landing_page_url is None
    assert candidate.pdf_url is None
    assert candidate.citation_count is None
    assert candidate.doi is None


async def test_429_exposes_bounded_retry_after_without_redispatch():
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client, max_attempts=3)
        with pytest.raises(SemanticScholarRequestError) as error:
            await adapter.search(adapter.search_request(query="test"))
    assert calls == 1
    assert error.value.status_code == 429
    assert error.value.retry_after_seconds == 60
    assert error.value.outcome == "released"


async def test_pre_dispatch_retry_and_read_timeout(monkeypatch):
    async def no_delay(_):
        pass

    monkeypatch.setattr("research_api.providers.semantic_scholar.retry_delay", no_delay)
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"data": [paper()]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client)
        result = await adapter.search(adapter.search_request(query="test"))
    assert calls == 2
    assert result.attempt_count == 2

    calls = 0

    def timeout(_):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("stream lost")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client, max_attempts=3)
        with pytest.raises(SemanticScholarRequestError) as error:
            await adapter.search(adapter.search_request(query="test"))
    assert calls == 1
    assert error.value.outcome == "uncertain"


async def test_cancellation_before_and_after_dispatch():
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": []})

    async def cancel():
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client)
        with pytest.raises(SemanticScholarCancelledBeforeDispatch) as error:
            await adapter.search(adapter.search_request(query="test"), before_attempt=cancel)
    assert calls == 0
    assert error.value.attempt_count == 0

    entered = asyncio.Event()
    hold = asyncio.Event()

    async def slow(_):
        entered.set()
        await hold.wait()
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        adapter = SemanticScholarAdapter(api_key=None, client=client)
        task = asyncio.create_task(adapter.search(adapter.search_request(query="test")))
        await entered.wait()
        task.cancel()
        with pytest.raises(SemanticScholarCancelledAfterDispatch) as error:
            await task
    assert error.value.outcome == "uncertain"
