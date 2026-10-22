from __future__ import annotations

import asyncio
import threading
from collections import defaultdict

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.config import Settings
from research_api.request_rate_limits import RequestRateLimitMiddleware


class InMemoryRedis:
    """Atomic test double for the Redis increment-and-expiry operation."""

    def __init__(self, *, fail: bool = False) -> None:
        self.counts: dict[str, int] = defaultdict(int)
        self.lock = threading.Lock()
        self.fail = fail

    async def eval(self, _script: str, _numkeys: int, key: str, _window_ms: int) -> list[int]:
        if self.fail:
            raise OSError("Redis unavailable")
        with self.lock:
            self.counts[key] += 1
            return [self.counts[key], 30_000]


def rate_limited_app(redis: InMemoryRedis) -> FastAPI:
    app = FastAPI()
    app.state.rate_limit_settings = Settings(
        APP_ENV="development",
        INTERNAL_SERVICE_AUTH="trusted-bff-secret",
        HTTP_RATE_LIMIT_GENERAL_PER_MINUTE=3,
        HTTP_RATE_LIMIT_MUTATION_PER_MINUTE=2,
        HTTP_RATE_LIMIT_RESEARCH_START_PER_MINUTE=2,
        HTTP_RATE_LIMIT_WEBHOOK_PER_MINUTE=3,
    )
    app.state.rate_limit_redis = redis
    app.add_middleware(RequestRateLimitMiddleware)

    @app.get("/research/runs")
    async def list_runs() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/research/runs")
    async def create_run() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/billing/credit-checkout")
    async def create_credit_checkout() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health/live")
    async def live() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/billing/webhooks/razorpay")
    async def razorpay_webhook() -> dict[str, bool]:
        return {"ok": True}

    return app


def trusted_headers(account_id: str) -> dict[str, str]:
    return {
        "x-internal-service-auth": "trusted-bff-secret",
        "x-verified-account-id": account_id,
    }


def test_rate_limit_returns_429_and_standard_headers() -> None:
    client = TestClient(rate_limited_app(InMemoryRedis()))
    headers = trusted_headers("00000000-0000-4000-8000-000000000001")

    assert client.get("/research/runs", headers=headers).status_code == 200
    assert client.get("/research/runs", headers=headers).status_code == 200
    assert client.get("/research/runs", headers=headers).status_code == 200
    limited = client.get("/research/runs", headers=headers)

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many requests. Please retry shortly."}
    assert limited.headers["retry-after"] == "30"
    assert limited.headers["ratelimit-limit"] == "3"
    assert limited.headers["ratelimit-remaining"] == "0"


def test_research_creation_uses_stricter_limit_than_reads() -> None:
    client = TestClient(rate_limited_app(InMemoryRedis()))
    headers = trusted_headers("00000000-0000-4000-8000-000000000002")

    assert client.post("/research/runs", headers=headers).status_code == 200
    assert client.post("/research/runs", headers=headers).status_code == 200
    limited = client.post("/research/runs", headers=headers)

    assert limited.status_code == 429
    assert limited.headers["ratelimit-limit"] == "2"


def test_credit_checkout_has_five_per_minute_limit_and_retry_after() -> None:
    client = TestClient(rate_limited_app(InMemoryRedis()))
    headers = trusted_headers("00000000-0000-4000-8000-000000000009")

    for _ in range(5):
        assert client.post("/billing/credit-checkout", headers=headers).status_code == 200
    limited = client.post("/billing/credit-checkout", headers=headers)

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many requests. Please retry shortly."}
    assert limited.headers["retry-after"] == "30"
    assert limited.headers["ratelimit-limit"] == "5"


def test_verified_accounts_have_independent_buckets() -> None:
    client = TestClient(rate_limited_app(InMemoryRedis()))
    first = trusted_headers("00000000-0000-4000-8000-000000000003")
    second = trusted_headers("00000000-0000-4000-8000-000000000004")

    for _ in range(3):
        assert client.get("/research/runs", headers=first).status_code == 200
    assert client.get("/research/runs", headers=first).status_code == 429
    assert client.get("/research/runs", headers=second).status_code == 200


async def test_concurrent_requests_cannot_overshoot_the_shared_limit() -> None:
    app = rate_limited_app(InMemoryRedis())
    headers = trusted_headers("00000000-0000-4000-8000-000000000007")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(
            *(client.get("/research/runs", headers=headers) for _ in range(20))
        )

    assert sum(response.status_code == 200 for response in responses) == 3
    assert sum(response.status_code == 429 for response in responses) == 17


def test_untrusted_account_header_does_not_choose_rate_limit_identity() -> None:
    redis = InMemoryRedis()
    client = TestClient(rate_limited_app(redis))
    forged = {"x-verified-account-id": "00000000-0000-4000-8000-000000000005"}

    for _ in range(3):
        assert client.get("/research/runs", headers=forged).status_code == 200
    assert client.get("/research/runs", headers=forged).status_code == 429
    assert len(redis.counts) == 1


def test_health_is_exempt_but_payment_webhooks_have_their_own_limit() -> None:
    client = TestClient(rate_limited_app(InMemoryRedis()))

    for _ in range(5):
        assert client.get("/health/live").status_code == 200
    for _ in range(3):
        assert client.post("/billing/webhooks/razorpay").status_code == 200
    assert client.post("/billing/webhooks/razorpay").status_code == 429


def test_redis_failure_fails_closed_for_mutations_but_not_reads() -> None:
    client = TestClient(rate_limited_app(InMemoryRedis(fail=True)))
    headers = trusted_headers("00000000-0000-4000-8000-000000000006")

    assert client.get("/research/runs", headers=headers).status_code == 200
    unavailable = client.post("/research/runs", headers=headers)

    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Request protection is temporarily unavailable."}
