import pytest

from research_api.providers.http_clients import (
    get_provider_http_client,
    provider_http_transport,
)


async def test_provider_transports_are_separate_bounded_and_lifespan_scoped():
    async with provider_http_transport(timeout_seconds=12, worker_concurrency=2) as clients:
        assert clients.tavily is get_provider_http_client("tavily")
        assert clients.serper is get_provider_http_client("serper")
        assert clients.tavily is not clients.serper
        assert clients.tavily.base_url.host == "api.tavily.com"
        assert clients.tavily.timeout.connect == 10
        assert clients.serper.timeout.pool == 2
        assert "authorization" not in clients.tavily.headers
        assert "x-api-key" not in clients.serper.headers

    assert get_provider_http_client("tavily") is None
    assert get_provider_http_client("serper") is None
    assert clients.tavily.is_closed
    assert clients.serper.is_closed


async def test_unknown_provider_is_rejected_inside_lifespan():
    async with provider_http_transport(timeout_seconds=12, worker_concurrency=1):
        with pytest.raises(ValueError, match="unsupported HTTP provider"):
            get_provider_http_client("other")
