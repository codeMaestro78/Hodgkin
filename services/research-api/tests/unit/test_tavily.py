import httpx
import pytest

from research_api.providers.tavily import (
    TAVILY_REQUEST_SCHEMA_VERSION,
    TAVILY_RESTRICTED_DOMAIN_REQUEST_SCHEMA_VERSION,
    TavilyAdapter,
)


@pytest.mark.asyncio
async def test_search_enforces_requested_limit_even_when_provider_overproduces() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"url": f"https://example.com/{i}", "title": str(i)} for i in range(6)]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.tavily.com"
    ) as client:
        adapter = TavilyAdapter(api_key="test", client=client)
        results = []
        # Focused has three search/extract pairs, not six sources per pair.
        for question in range(3):
            response = await adapter.search(
                adapter.search_request(query=f"question {question}", max_results=2)
            )
            results.extend(response.results)
        assert len(results) <= 6


@pytest.mark.asyncio
async def test_search_uses_evidence_safe_defaults_and_post_filters_hosts() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.read() and __import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "results": [
                    {"url": "https://docs.example.com/a", "title": "Allowed"},
                    {"url": "https://attacker.example/a", "title": "Rejected"},
                ],
                "usage": {"credits": 1},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.tavily.com"
    )
    adapter = TavilyAdapter(api_key="secret", client=client)
    request = adapter.search_request(query="test query", allowed_domains=["example.com"])
    response = await adapter.search(request)

    assert captured["include_answer"] is False
    assert captured["include_raw_content"] is False
    assert captured["search_depth"] == "basic"
    assert captured["include_domains"] == ["example.com"]
    assert captured["include_domains_mode"] == "restrict"
    assert request.request_schema_version == TAVILY_RESTRICTED_DOMAIN_REQUEST_SCHEMA_VERSION
    assert [result.title for result in response.results] == ["Allowed"]
    await client.aclose()


def test_extract_request_is_deterministic_and_deduplicated() -> None:
    adapter = TavilyAdapter(api_key="secret", client=httpx.AsyncClient())
    first = adapter.extract_request(
        urls=["https://example.com/b", "https://example.com/a", "https://example.com/a"],
        query="q",
    )
    second = adapter.extract_request(
        urls=["https://example.com/a", "https://example.com/b"], query="q"
    )
    assert first.fingerprint == second.fingerprint
    assert first.payload["urls"] == ["https://example.com/a", "https://example.com/b"]


def test_unrestricted_search_keeps_the_archived_request_schema_version() -> None:
    request = TavilyAdapter.search_request(query="unrestricted")
    assert request.request_schema_version == TAVILY_REQUEST_SCHEMA_VERSION
