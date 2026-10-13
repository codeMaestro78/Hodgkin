from __future__ import annotations

import os

import pytest

from research_api.providers.tavily import TavilyAdapter

pytestmark = pytest.mark.live_provider


async def test_tavily_search_response_remains_compatible() -> None:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        pytest.skip("TAVILY_API_KEY is not configured")

    adapter = TavilyAdapter(api_key=api_key)
    try:
        response = await adapter.search(
            adapter.search_request(query="PostgreSQL row level security", max_results=1)
        )
    finally:
        await adapter.aclose()

    assert response.results
    assert response.results[0].url.startswith(("http://", "https://"))
