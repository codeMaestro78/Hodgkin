import asyncio
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from research_api.providers import serper
from research_api.providers.serper import SerperAdapter, SerperCancelled, SerperRequestError
from research_api.providers.tavily import SearchResponse, request_fingerprint


@pytest.fixture
def delays(monkeypatch):
    backoff = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr(serper, "retry_delay", backoff)
    monkeypatch.setattr(serper.asyncio, "sleep", sleep)
    return backoff, sleep


def test_request_is_sanitized_scoped_and_deterministic():
    first = SerperAdapter.search_request(
        query="  query  ", max_results=50, allowed_domains=[".Example.COM", "example.com"]
    )
    second = SerperAdapter.search_request(
        query="query", max_results=10, allowed_domains=["example.com"]
    )
    assert first == second
    assert first.operation == "search"
    assert first.request_schema_version == "serper-discovery-v1"
    assert first.payload == {
        "query": "query",
        "max_results": 10,
        "allowed_domains": ["example.com"],
    }
    assert first.fingerprint == request_fingerprint("serper:search:v1", first.payload)
    assert first.fingerprint != request_fingerprint("search", first.payload)
    assert first.fingerprint != SerperAdapter.search_request(query="query").fingerprint
    assert SerperAdapter.search_request(query="q", max_results=-1).payload["max_results"] == 1


@pytest.mark.parametrize("query", ["", "  ", "x" * 1001, None, 12])
def test_invalid_query_is_rejected(query):
    with pytest.raises(ValueError):
        SerperAdapter.search_request(query=query)


async def test_success_filters_deduplicates_and_never_exposes_snippets_as_evidence(monkeypatch):
    events = []
    monkeypatch.setattr(serper, "dependency_event", lambda **event: events.append(event))

    def handler(request):
        assert str(request.url) == "https://google.serper.dev/search"
        assert request.method == "POST"
        assert request.headers["X-API-KEY"] == "secret"
        assert json.loads(request.content) == {"q": "private prompt", "num": 10}
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "link": "https://EXAMPLE.com:443/a?utm_source=x#fragment",
                        "title": "first",
                        "snippet": "discovery only",
                    },
                    {"link": "https://example.com/a", "title": "duplicate"},
                    {"link": "https://evil-example.com/a"},
                    {
                        "link": "https://docs.example.com/b",
                        "title": "t" * 1100,
                        "snippet": "s" * 2100,
                    },
                    {"link": "https://example.com/c", "title": 42, "snippet": {}},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SerperAdapter("secret", client=client)
        response = await adapter.search(
            adapter.search_request(
                query="private prompt", max_results=2, allowed_domains=["example.com"]
            )
        )
        assert isinstance(response, SearchResponse)
        assert [r.url for r in response.results] == [
            "https://example.com/a",
            "https://docs.example.com/b",
        ]
        assert all(r.content == "" and "snippet" not in r.model_dump() for r in response.results)
        extras = response.model_extra
        assert extras["response_schema_version"] == "serper-discovery-v1"
        assert extras["shortlist_policy"] == "serper-order-v1"
        candidates = extras["discovery_candidates"]
        assert [c["rank"] for c in candidates] == [1, 4, 5]
        assert candidates[0]["snippet"] == "discovery only"
        assert len(candidates[1]["title"]) == 1000
        assert len(candidates[1]["snippet"]) == 2000
        assert candidates[2]["title"] == "Untitled source"
        assert candidates[2]["snippet"] == ""
        await adapter.aclose()
        assert not client.is_closed
    assert all(e["provider"] == "serper" and e["operation"] == "search" for e in events)
    assert events[0]["outcome"] == "started"
    assert events[-1]["outcome"] == "succeeded"
    assert "secret" not in repr(events) and "private prompt" not in repr(events)


@pytest.mark.parametrize(
    "organic, expected",
    [
        ([], []),
        (
            [
                None,
                {},
                {"link": 42},
                {"link": "ftp://example.com/a"},
                {"link": "https://user:password@example.com/a"},
                {"link": "https://[broken"},
                {"link": "https://example.com:bad/a"},
                {"link": "https://example.com/good"},
            ],
            ["https://example.com/good"],
        ),
    ],
)
async def test_malformed_items_are_dropped_individually(organic, expected):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"organic": organic}))
    ) as client:
        response = await SerperAdapter("key", client).search(
            SerperAdapter.search_request(query="q")
        )
    assert [r.url for r in response.results] == expected


async def test_candidate_breadth_is_bounded_at_ten():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"organic": [{"link": f"https://example.com/{i}"} for i in range(30)]}
            )
        )
    ) as client:
        response = await SerperAdapter("key", client).search(
            SerperAdapter.search_request(query="q", max_results=50)
        )
    assert len(response.results) == len(response.model_extra["discovery_candidates"]) == 10


async def test_shared_transport_keeps_adapter_credentials_request_scoped():
    seen_keys = []

    def handler(request):
        seen_keys.append(request.headers["X-API-KEY"])
        return httpx.Response(200, json={"organic": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = SerperAdapter("tenant-one-key", client=client)
        second = SerperAdapter("tenant-two-key", client=client)
        requests = [SerperAdapter.search_request(query="same query") for _ in range(2)]
        await asyncio.gather(first.search(requests[0]), second.search(requests[1]))
        await first.aclose()
        await second.aclose()
        assert not client.is_closed

    assert sorted(seen_keys) == ["tenant-one-key", "tenant-two-key"]


@pytest.mark.parametrize("body", [None, [], {}, {"organic": None}, {"organic": {}}, "bad-json"])
async def test_invalid_top_level_response_is_consumed(body):
    def handler(_):
        if body == "bad-json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(200, content=json.dumps(body).encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SerperRequestError) as error:
            await SerperAdapter("key", client).search(SerperAdapter.search_request(query="q"))
    assert error.value.outcome == "consumed"


@pytest.mark.parametrize(
    "history, expected, calls",
    [
        (["connect", "ok"], None, 2),
        (["connect"] * 3, "released", 3),
        ([429] * 3, "uncertain", 3),
        ([429, "connect", "connect"], "uncertain", 3),
        ([429, 401], "uncertain", 2),
        (["connect", 401], "released", 2),
        *[([status], "released", 1) for status in (400, 401, 403, 404, 422)],
        *[([status], "uncertain", 1) for status in (402, 408, 409, 500, 503)],
        (["timeout"], "uncertain", 1),
        (["write"], "uncertain", 1),
    ],
)
async def test_retry_histories_preserve_uncertainty(history, expected, calls, delays):
    attempts = []

    def handler(request):
        action = history[len(attempts)]
        attempts.append(action)
        if action == "connect":
            raise httpx.ConnectError("sensitive", request=request)
        if action == "timeout":
            raise httpx.ReadTimeout("sensitive", request=request)
        if action == "write":
            raise httpx.WriteError("sensitive", request=request)
        return httpx.Response(200 if action == "ok" else action, json={"organic": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SerperAdapter("key", client)
        if expected is None:
            assert (await adapter.search(adapter.search_request(query="q"))).results == []
        else:
            with pytest.raises(SerperRequestError) as error:
                await adapter.search(adapter.search_request(query="q"))
            assert error.value.outcome == expected
            assert "sensitive" not in str(error.value)
    assert len(attempts) == calls


@pytest.mark.parametrize(
    "history, cancel_at, expected",
    [
        ([], "gate", "released"),
        (["connect"], "gate", "released"),
        ([429], "gate", "uncertain"),
        (["connect"], "delay", "released"),
        ([429], "delay", "uncertain"),
        ([], "network", "uncertain"),
        (["connect"], "network", "uncertain"),
        ([429], "network", "uncertain"),
    ],
)
async def test_cancellation_histories(history, cancel_at, expected, delays):
    attempts = []
    backoff, _ = delays
    if cancel_at == "delay":
        backoff.side_effect = asyncio.CancelledError

    async def gate():
        if cancel_at == "gate" and len(attempts) == len(history):
            raise asyncio.CancelledError

    async def handler(request):
        if len(attempts) == len(history):
            raise asyncio.CancelledError
        action = history[len(attempts)]
        attempts.append(action)
        if action == "connect":
            raise httpx.ConnectError("connect", request=request)
        return httpx.Response(action)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SerperCancelled) as error:
            await SerperAdapter("key", client).search(
                SerperAdapter.search_request(query="q"), before_attempt=gate
            )
    assert isinstance(error.value, asyncio.CancelledError)
    assert error.value.outcome == expected
    assert len(attempts) == len(history)


@pytest.mark.parametrize(
    "header, expected",
    [
        ("2", 2),
        ("100", 5),
        ("-3", 0),
        ("NaN", None),
        ("garbage", None),
        (format_datetime(datetime.now(UTC) + timedelta(days=1)), 5),
        (format_datetime(datetime(2000, 1, 1, tzinfo=UTC)), 0),
    ],
)
async def test_retry_after_seconds_dates_and_cap(header, expected, delays):
    attempts = []

    def handler(_):
        attempts.append(1)
        return httpx.Response(
            429 if len(attempts) == 1 else 200,
            headers={"Retry-After": header},
            json={"organic": []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await SerperAdapter("key", client).search(SerperAdapter.search_request(query="q"))
    backoff, sleep = delays
    if expected is None:
        backoff.assert_awaited_once_with(1)
        sleep.assert_not_awaited()
    else:
        sleep.assert_awaited_once_with(expected)
        backoff.assert_not_awaited()


async def test_owned_client_is_closed():
    adapter = SerperAdapter("key")
    await adapter.aclose()
    assert adapter._client.is_closed


async def test_tampered_request_is_rejected_without_dispatch():
    def handler(_):
        pytest.fail("invalid request dispatched")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        request = SerperAdapter.search_request(query="q")
        request.payload["api_key"] = "injected"
        with pytest.raises(ValueError):
            await SerperAdapter("key", client).search(request)


@pytest.mark.parametrize("limit", [None, 1.5, float("inf"), float("nan"), True, "10"])
def test_invalid_result_limits_are_rejected(limit):
    with pytest.raises(ValueError):
        SerperAdapter.search_request(query="q", max_results=limit)


@pytest.mark.parametrize(
    "options",
    [
        {"max_attempts": 0},
        {"max_attempts": 4},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"retry_after_max_s": -1},
        {"retry_after_max_s": float("nan")},
    ],
)
def test_invalid_constructor_options_are_rejected(options):
    with pytest.raises(ValueError):
        SerperAdapter("key", **options)


@pytest.mark.parametrize("cancel", [False, True])
async def test_custom_retry_after_cap_and_cancellation(cancel, delays):
    _, sleep = delays
    if cancel:
        sleep.side_effect = asyncio.CancelledError
    attempts = []

    def handler(_):
        attempts.append(1)
        return httpx.Response(
            429 if len(attempts) == 1 else 200,
            headers={"Retry-After": "90"},
            json={"organic": []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SerperAdapter("key", client, retry_after_max_s=0.25)
        if cancel:
            with pytest.raises(SerperCancelled) as error:
                await adapter.search(adapter.search_request(query="q"))
            assert error.value.outcome == "uncertain"
        else:
            await adapter.search(adapter.search_request(query="q"))
    sleep.assert_awaited_once_with(0.25)
    assert len(attempts) == (1 if cancel else 2)


async def test_timeout_applies_to_injected_client_and_redirect_is_not_followed():
    attempts = []

    def handler(request):
        attempts.append(request)
        assert request.extensions["timeout"] == {
            "connect": 0.25,
            "read": 0.25,
            "write": 0.25,
            "pool": 0.25,
        }
        return httpx.Response(302, headers={"Location": "https://other.example/"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(SerperRequestError) as error:
            await SerperAdapter("key", client, timeout=0.25).search(
                SerperAdapter.search_request(query="q")
            )
    assert error.value.outcome == "uncertain"
    assert len(attempts) == 1


async def test_task_cancellation_during_network_is_typed_and_uncertain():
    entered = asyncio.Event()
    pending = asyncio.Event()

    async def handler(_):
        entered.set()
        await pending.wait()
        return httpx.Response(200, json={"organic": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = SerperAdapter("key", client)
        task = asyncio.create_task(adapter.search(adapter.search_request(query="q")))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(SerperCancelled) as error:
            await task
    assert error.value.outcome == "uncertain"
