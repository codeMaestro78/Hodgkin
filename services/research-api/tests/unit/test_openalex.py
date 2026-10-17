import asyncio
import json

import httpx
import pytest

from research_api.providers.openalex import (
    WORK_FIELDS,
    OpenAlexAdapter,
    OpenAlexCancelledAfterDispatch,
    OpenAlexCancelledBeforeDispatch,
    OpenAlexRequestError,
)


def work_payload(**overrides):
    return {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/Example.7",
        "title": "A relevant paper",
        "publication_year": 2024,
        "publication_date": "2024-03-10",
        "type": "article",
        "cited_by_count": 12,
        "authorships": [
            {"author": {"display_name": "Ada Researcher"}},
            {"author": {"display_name": "Lin Researcher"}},
        ],
        "primary_location": {
            "landing_page_url": "https://publisher.example/paper",
            "pdf_url": "https://publisher.example/paper.pdf",
            "source": {"display_name": "Example Journal"},
        },
        "best_oa_location": {
            "landing_page_url": "https://repository.example/paper",
            "pdf_url": "https://repository.example/paper.pdf",
        },
        "locations": [],
        "open_access": {"is_oa": True},
        "abstract_inverted_index": {"Evidence": [0], "supports": [1], "a": [2], "claim.": [3]},
        **overrides,
    }


def test_request_is_stable_bounded_and_does_not_put_key_in_query():
    request = OpenAlexAdapter.search_request(
        query="  distributed transaction recovery  ",
        per_page=8,
        from_publication_date="2020-01-01",
        is_oa=True,
    )
    same = OpenAlexAdapter.search_request(
        query="distributed transaction recovery",
        per_page=8,
        from_publication_date="2020-01-01",
        is_oa=True,
    )
    assert request == same
    assert request.request_schema_version == "openalex-works-v1"
    assert request.operation == "search"
    assert request.payload == {
        "search": "distributed transaction recovery",
        "per_page": 8,
        "selection_limit": 8,
        "select": WORK_FIELDS,
        "from_publication_date": "2020-01-01",
        "is_oa": True,
    }
    assert "api_key" not in json.dumps(request.payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": "  "},
        {"query": "x" * 1001},
        {"query": "ok", "per_page": 0},
        {"query": "ok", "per_page": 11},
        {"query": "ok", "per_page": 3, "selection_limit": 4},
        {"query": "ok", "from_publication_date": "2024-13-01"},
        {"query": "ok", "is_oa": "yes"},
    ],
)
def test_invalid_search_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        OpenAlexAdapter.search_request(**kwargs)


async def test_search_normalizes_metadata_and_keeps_abstract_out_of_evidence():
    def handler(request):
        assert request.method == "GET"
        assert request.url.host == "api.openalex.org"
        assert request.headers["Authorization"] == "Bearer private-key"
        assert request.url.params["search"] == "distributed transaction recovery"
        assert "selection_limit" not in request.url.params
        assert "api_key" not in request.url.params
        return httpx.Response(
            200,
            json={"meta": {"count": 1, "cost_usd": 0.0001}, "results": [work_payload()]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAlexAdapter(api_key="private-key", client=client)
        request = adapter.search_request(query="distributed transaction recovery")
        result = await adapter.search(request)
        await adapter.aclose()
        assert not client.is_closed

    assert result.total_count == 1
    assert result.reported_cost_usd == 0.0001
    assert result.attempt_count == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.work_id == "W123"
    assert candidate.doi == "10.1234/example.7"
    assert candidate.authors == ("Ada Researcher", "Lin Researcher")
    assert candidate.venue == "Example Journal"
    assert candidate.abstract == "Evidence supports a claim."
    assert candidate.open_access is True
    assert candidate.landing_page_url == "https://repository.example/paper"
    assert candidate.pdf_url == "https://repository.example/paper.pdf"
    assert "content" not in candidate.model_dump()


async def test_malformed_work_is_dropped_without_losing_valid_candidates():
    payload = work_payload()
    payload["best_oa_location"] = {
        "landing_page_url": "javascript:alert(1)",
        "pdf_url": "https://repository.example/good.pdf",
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "meta": {"count": 2},
                    "results": [None, {"id": "bad", "title": 12}, payload],
                },
            )
        )
    ) as client:
        result = await OpenAlexAdapter(api_key=None, client=client).search(
            OpenAlexAdapter.search_request(query="question")
        )

    assert len(result.candidates) == 1
    assert result.candidates[0].landing_page_url is None
    assert result.candidates[0].pdf_url == "https://repository.example/good.pdf"


async def test_search_response_schema_failure_is_not_misreported_as_empty_results():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": {}}))
    ) as client:
        with pytest.raises(OpenAlexRequestError, match="response is invalid") as error:
            await OpenAlexAdapter(api_key=None, client=client).search(
                OpenAlexAdapter.search_request(query="question")
            )
        assert error.value.outcome == "consumed"


async def test_cancellation_before_attempt_does_not_dispatch_request():
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    async def cancel():
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAlexAdapter(api_key=None, client=client)
        with pytest.raises(OpenAlexCancelledBeforeDispatch):
            await adapter.search(
                OpenAlexAdapter.search_request(query="question"), before_attempt=cancel
            )

    assert calls == 0


async def test_known_pre_dispatch_retry_is_counted_and_returns_one_result(monkeypatch):
    calls = 0

    async def no_delay(_attempt):
        return None

    monkeypatch.setattr("research_api.providers.openalex.retry_delay", no_delay)

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [work_payload()]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenAlexAdapter(api_key=None, client=client).search(
            OpenAlexAdapter.search_request(query="ledger durability")
        )

    assert calls == 2
    assert result.attempt_count == 2
    assert len(result.candidates) == 1


async def test_uncertain_read_timeout_is_not_retried():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("response stream interrupted")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAlexAdapter(api_key=None, client=client, max_attempts=3)
        with pytest.raises(OpenAlexRequestError) as error:
            await adapter.search(OpenAlexAdapter.search_request(query="ledger durability"))

    assert error.value.outcome == "uncertain"
    assert calls == 1


async def test_rate_limit_is_known_rejection_and_is_not_retried():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OpenAlexRequestError) as error:
            await OpenAlexAdapter(api_key=None, client=client, max_attempts=3).search(
                OpenAlexAdapter.search_request(query="ledger durability")
            )

    assert error.value.outcome == "released"
    assert error.value.attempt_count == 1
    assert calls == 1


async def test_cancellation_after_dispatch_is_recorded_as_uncertain():
    entered = asyncio.Event()
    hold_response = asyncio.Event()

    async def handler(_request):
        entered.set()
        await hold_response.wait()
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAlexAdapter(api_key=None, client=client)
        task = asyncio.create_task(
            adapter.search(OpenAlexAdapter.search_request(query="ledger durability"))
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(OpenAlexCancelledAfterDispatch) as error:
            await task

    assert error.value.outcome == "uncertain"
    assert error.value.attempt_count == 1
