import io
import json
import logging
import uuid
from time import monotonic
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

from research_api import model_budget
from research_api.pricing import model_rate
from research_api.providers import tavily
from research_api.providers.retry_policy import pre_dispatch_failure
from research_api.providers.tavily import TavilyAdapter, TavilyRequestError
from research_api.telemetry import dependency_event, dependency_logging, dependency_run


def test_default_model_snapshot_and_cached_input_rounding():
    rate = model_rate("gpt-4o-mini")
    assert rate.cost(1_000_000, 1_000_000) == __import__("decimal").Decimal("0.750000")
    assert rate.cost(1_000_000, 0, 1_000_000) == __import__("decimal").Decimal("0.075000")
    assert model_rate("unreviewed-model") is None
    with pytest.raises(ValueError):
        rate.cost(1, 1, 2)


async def test_sdk_implicit_retries_are_rejected_before_network_dispatch():
    async with AsyncOpenAI(api_key="fixture", max_retries=2) as client:
        with pytest.raises(ValueError, match="SDK retries disabled"):
            await model_budget.model_response(client, model="gpt-4o-mini", input="fixture")


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
async def test_tavily_retries_only_pre_dispatch_failures(monkeypatch, error, caplog):
    monkeypatch.setattr(tavily, "retry_delay", AsyncMock())
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise error("sensitive transport detail", request=request)
        return httpx.Response(200, json={"results": []})

    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://api.tavily.com"
        ) as client:
            adapter = TavilyAdapter(api_key="private-key", client=client)
            await adapter.search(adapter.search_request(query="private question"))
    assert attempts == 3
    assert "sensitive transport detail" not in caplog.text
    assert "private-key" not in caplog.text and "private question" not in caplog.text
    events = [json.loads(record.message) for record in caplog.records]
    assert [item["attempt"] for item in events] == [1, 2, 3]
    assert all(type(item["remoteDurationMs"]) is float for item in events)
    assert all(item["remoteDurationMs"] >= 0 for item in events)


@pytest.mark.parametrize("status", [400, 401, 429, 500])
async def test_tavily_http_failures_are_not_retried(status):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "not logged"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.tavily.com"
    ) as client:
        adapter = TavilyAdapter(api_key="fixture", client=client)
        with pytest.raises(TavilyRequestError) as failure:
            await adapter.search(adapter.search_request(query="q"))
    assert calls == 1
    assert failure.value.outcome == ("released" if status in {400, 401} else "uncertain")


async def test_tavily_read_timeout_is_ambiguous_and_not_retried():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private details", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.tavily.com"
    ) as client:
        adapter = TavilyAdapter(api_key="fixture", client=client)
        with pytest.raises(TavilyRequestError) as failure:
            await adapter.search(adapter.search_request(query="q"))
    assert calls == 1 and failure.value.outcome == "uncertain"
    assert not pre_dispatch_failure(failure.value)


@pytest.mark.parametrize("payload", ["not json", "[]", '{"results":[{}]}'])
async def test_tavily_malformed_success_is_typed_and_remains_chargeable(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=payload)),
        base_url="https://api.tavily.com",
    ) as client:
        adapter = TavilyAdapter(api_key="fixture", client=client)
        with pytest.raises(TavilyRequestError) as failure:
            await adapter.search(adapter.search_request(query="q"))
    assert failure.value.outcome == "consumed"


async def test_invalid_search_urls_do_not_poison_valid_results():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "results": [
                        {"url": "file:///private"},
                        {"url": "https://valid.example/a"},
                        {"url": "https://bad.example:invalid/a"},
                    ]
                },
            )
        ),
        base_url="https://api.tavily.com",
    ) as client:
        adapter = TavilyAdapter(api_key="fixture", client=client)
        response = await adapter.search(adapter.search_request(query="q"))
    assert [result.url for result in response.results] == ["https://valid.example/a"]


def test_dependency_logging_is_enabled_correlated_and_restored(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(
        logging.getLogger("uvicorn.error"), "handlers", [logging.StreamHandler(stream)]
    )
    run = uuid.uuid4()
    token = dependency_run.set(run)
    try:
        with dependency_logging():
            dependency_event(
                provider="openai",
                operation="model",
                outcome="consumed",
                started=monotonic(),
                reason="provider-usage",
            )
    finally:
        dependency_run.reset(token)
    record = json.loads(stream.getvalue())
    assert record["runId"] == str(run) and record["durationMs"] >= 0
