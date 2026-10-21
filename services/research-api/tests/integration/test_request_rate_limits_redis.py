from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis

from research_api.config import Settings
from research_api.request_rate_limits import RequestRateLimitMiddleware


def app_for_limiter(redis: Redis, limit: int) -> FastAPI:
    app = FastAPI()
    app.state.rate_limit_settings = Settings(
        APP_ENV="staging",
        INTERNAL_SERVICE_AUTH="integration-secret",
        HTTP_RATE_LIMIT_GENERAL_PER_MINUTE=limit,
    )
    app.state.rate_limit_redis = redis
    app.add_middleware(RequestRateLimitMiddleware)

    @app.get("/research/runs")
    async def list_runs() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.mark.integration
async def test_limit_is_shared_across_independent_api_instances() -> None:
    url = os.environ["TEST_REDIS_URL"]
    first_redis = Redis.from_url(url, decode_responses=False)
    second_redis = Redis.from_url(url, decode_responses=False)
    limit = 20
    account_id = str(uuid.uuid4())
    headers = {
        "x-internal-service-auth": "integration-secret",
        "x-verified-account-id": account_id,
    }
    first_transport = httpx.ASGITransport(app=app_for_limiter(first_redis, limit))
    second_transport = httpx.ASGITransport(app=app_for_limiter(second_redis, limit))
    try:
        async with (
            httpx.AsyncClient(transport=first_transport, base_url="http://api-one") as first,
            httpx.AsyncClient(transport=second_transport, base_url="http://api-two") as second,
        ):
            responses = await asyncio.gather(
                *(
                    (first if index % 2 == 0 else second).get("/research/runs", headers=headers)
                    for index in range(100)
                )
            )
    finally:
        await first_redis.aclose()
        await second_redis.aclose()

    assert sum(response.status_code == 200 for response in responses) == limit
    assert sum(response.status_code == 429 for response in responses) == 100 - limit
