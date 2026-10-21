"""Distributed inbound request limits for the authenticated research API."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from hmac import compare_digest
from math import ceil
from uuid import UUID

from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from research_api.config import Settings, get_settings

logger = logging.getLogger("research_api.rate_limits")
_warned_redis_unavailable = False
_RESEARCH_START_PATH = re.compile(r"^/research/runs(?:/[^/]+/(?:retry|followups|approve))?$")
_RAZORPAY_WEBHOOK_PATH = "/billing/webhooks/razorpay"

_INCREMENT_WITH_EXPIRY = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    bucket: str
    limit: int
    fail_closed: bool


def request_policy(method: str, path: str, settings: Settings) -> RateLimitPolicy | None:
    """Use dedicated buckets for costly paths; leave only probes unmetered."""
    if method in {"OPTIONS", "HEAD"} or path == "/health" or path.startswith("/health/"):
        return None
    if path == _RAZORPAY_WEBHOOK_PATH:
        return RateLimitPolicy(
            "razorpay-webhook", settings.HTTP_RATE_LIMIT_WEBHOOK_PER_MINUTE, True
        )
    if method == "POST" and _RESEARCH_START_PATH.fullmatch(path):
        return RateLimitPolicy(
            "research-start", settings.HTTP_RATE_LIMIT_RESEARCH_START_PER_MINUTE, True
        )
    if method == "POST" and path in {"/billing/checkout", "/billing/credit-checkout"}:
        return RateLimitPolicy("billing-checkout", 5, True)
    if method in {"POST", "PATCH", "PUT", "DELETE"}:
        return RateLimitPolicy("mutation", settings.HTTP_RATE_LIMIT_MUTATION_PER_MINUTE, True)
    return RateLimitPolicy("general", settings.HTTP_RATE_LIMIT_GENERAL_PER_MINUTE, False)


def _request_identity(scope: Scope, settings: Settings) -> str:
    """Use account IDs only when attested by the private BFF credential."""
    headers = {key.lower(): value for key, value in scope.get("headers", [])}
    supplied_service_key = headers.get(b"x-internal-service-auth", b"").decode(
        "utf-8", errors="ignore"
    )
    configured_service_key = (
        settings.INTERNAL_SERVICE_AUTH.get_secret_value() if settings.INTERNAL_SERVICE_AUTH else ""
    )
    account_id = headers.get(b"x-verified-account-id", b"").decode("ascii", errors="ignore")
    if (
        configured_service_key
        and compare_digest(configured_service_key, supplied_service_key)
        and _is_uuid(account_id)
    ):
        principal = f"account:{account_id}"
    else:
        authorization = headers.get(b"authorization", b"")
        if authorization:
            principal = f"credential:{hashlib.sha256(authorization).hexdigest()}"
        else:
            client = scope.get("client")
            peer = client[0] if client else "unknown"
            principal = f"peer:{peer}"
    return hashlib.sha256(principal.encode()).hexdigest()


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


class RequestRateLimitMiddleware:
    """Redis fixed-window limiter shared by all API replicas.

    Read-only routes fail open if Redis is unavailable; mutations fail closed so
    provider spend and persisted state changes cannot bypass request protection.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        app = scope.get("app")
        state = getattr(app, "state", None)
        settings = getattr(state, "rate_limit_settings", None) or get_settings()
        if not settings.HTTP_RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return
        policy = request_policy(scope["method"], scope.get("path", "/"), settings)
        if policy is None or settings.APP_ENV == "test":
            await self.app(scope, receive, send)
            return

        redis = getattr(state, "rate_limit_redis", None)
        if redis is None:
            if policy.fail_closed:
                await self._unavailable(scope, receive, send)
            else:
                self._warn_unavailable()
                await self.app(scope, receive, send)
            return

        window_ms = 60_000
        principal = _request_identity(scope, settings)
        env = settings.APP_ENV
        key = f"hogskin:request-limit:v1:{env}:{policy.bucket}:{principal}"
        try:
            count, ttl_ms = await redis.eval(_INCREMENT_WITH_EXPIRY, 1, key, window_ms)
            count = int(count)
            ttl_ms = max(0, int(ttl_ms))
        except (RedisError, OSError, TimeoutError):
            if policy.fail_closed:
                await self._unavailable(scope, receive, send)
            else:
                self._warn_unavailable()
                await self.app(scope, receive, send)
            return

        retry_after = max(1, ceil(ttl_ms / 1000))
        remaining = max(0, policy.limit - count)
        if count > policy.limit:
            response = JSONResponse(
                {"detail": "Too many requests. Please retry shortly."},
                status_code=429,
                headers={
                    "Retry-After": str(retry_after),
                    "RateLimit-Limit": str(policy.limit),
                    "RateLimit-Remaining": "0",
                    "RateLimit-Reset": str(retry_after),
                },
            )
            await response(scope, receive, send)
            return

        async def rate_limit_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"ratelimit-limit", str(policy.limit).encode()),
                        (b"ratelimit-remaining", str(remaining).encode()),
                        (b"ratelimit-reset", str(retry_after).encode()),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, rate_limit_headers)

    @staticmethod
    async def _unavailable(scope: Scope, receive: Receive, send: Send) -> None:
        RequestRateLimitMiddleware._warn_unavailable()
        response = JSONResponse(
            {"detail": "Request protection is temporarily unavailable."},
            status_code=503,
            headers={"Retry-After": "5"},
        )
        await response(scope, receive, send)

    @staticmethod
    def _warn_unavailable() -> None:
        global _warned_redis_unavailable
        if not _warned_redis_unavailable:
            logger.warning("request_rate_limit.redis_unavailable")
            _warned_redis_unavailable = True
