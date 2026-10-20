"""Bounded Serper discovery. Snippets are metadata, never source evidence."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any

import httpx

from research_api.artifacts.normalization import canonicalize_url
from research_api.providers.retry_policy import pre_dispatch_failure, retry_delay
from research_api.providers.tavily import (
    ProviderRequest,
    SearchResponse,
    SearchResult,
    request_fingerprint,
)
from research_api.telemetry import dependency_event

SERPER_REQUEST_SCHEMA_VERSION = "serper-discovery-v1"
SERPER_RESPONSE_SCHEMA_VERSION = "serper-discovery-v1"


class SerperRequestError(RuntimeError):
    def __init__(self, message: str, *, outcome: str = "uncertain") -> None:
        super().__init__(message)
        self.outcome = outcome


class SerperCancelled(asyncio.CancelledError):
    def __init__(self, *, outcome: str) -> None:
        super().__init__("Serper search cancelled")
        self.outcome = outcome


class SerperAdapter:
    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 3,
        timeout: float = 30,
        retry_after_max_s: float = 5,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("Serper attempts must be between one and three")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Serper timeout must be finite and positive")
        if not math.isfinite(retry_after_max_s) or retry_after_max_s < 0:
            raise ValueError("Serper retry delay cap must be finite and nonnegative")
        self._max_attempts = max_attempts
        self._timeout = httpx.Timeout(timeout, connect=min(10, timeout))
        self._retry_after_max_s = retry_after_max_s
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()
        self._headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

    @staticmethod
    def search_request(
        *, query: str, max_results: int = 6, allowed_domains: list[str] | None = None
    ) -> ProviderRequest:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ValueError("Serper query must contain between 1 and 1000 characters")
        if not isinstance(max_results, int) or isinstance(max_results, bool):
            raise ValueError("Serper result limit must be an integer")
        domains = set()
        for domain in allowed_domains or []:
            if not isinstance(domain, str):
                raise ValueError("Serper domains must be hostnames")
            domain = domain.strip().lower().lstrip(".").rstrip(".")
            url = httpx.URL(canonicalize_url(f"https://{domain}"))
            if not domain or url.port is not None or url.raw_path != b"/":
                raise ValueError("Serper domains must be hostnames")
            domains.add(url.host)
        payload: dict[str, Any] = {
            "query": query.strip(),
            "max_results": min(max(max_results, 1), 10),
            "allowed_domains": sorted(domains),
        }
        return ProviderRequest(
            operation="search",
            payload=payload,
            fingerprint=request_fingerprint("serper:search:v1", payload),
            request_schema_version=SERPER_REQUEST_SCHEMA_VERSION,
        )

    async def search(
        self,
        request: ProviderRequest,
        *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> SearchResponse:
        # Revalidate the mutable request payload before any dispatch.
        query = request.payload.get("query")
        if not isinstance(query, str):
            raise ValueError("Invalid Serper discovery query")
        sanitized = self.search_request(
            query=query,
            max_results=request.payload.get("max_results", 6),
            allowed_domains=request.payload.get("allowed_domains"),
        )
        if request.operation != "search" or request != sanitized:
            raise ValueError("Invalid Serper discovery request")
        body = await self._post(sanitized.payload["query"], before_attempt)
        organic = body.get("organic")
        if not isinstance(organic, list):
            raise SerperRequestError("Serper organic results are invalid", outcome="consumed")
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        domains = sanitized.payload["allowed_domains"]
        for rank, item in enumerate(organic[:10], start=1):
            if not isinstance(item, dict) or not isinstance(item.get("link"), str):
                continue
            link = item["link"]
            if len(link) > 8192:
                continue
            try:
                url = canonicalize_url(link)
                host = httpx.URL(url).host.lower().rstrip(".")
            except (ValueError, UnicodeError, httpx.InvalidURL):
                continue
            if url in seen or (
                domains
                and not any(host == domain or host.endswith(f".{domain}") for domain in domains)
            ):
                continue
            seen.add(url)
            candidates.append(
                {
                    "url": url,
                    "title": (item["title"][:1000] or "Untitled source")
                    if isinstance(item.get("title"), str)
                    else "Untitled source",
                    "snippet": item["snippet"][:2000]
                    if isinstance(item.get("snippet"), str)
                    else "",
                    "rank": rank,
                }
            )
        return SearchResponse(
            results=[
                SearchResult(url=c["url"], title=c["title"], content="")
                for c in candidates[: sanitized.payload["max_results"]]
            ],
            discovery_candidates=candidates,
            shortlist_policy="serper-order-v1",
            response_schema_version=SERPER_RESPONSE_SCHEMA_VERSION,
        )

    def _retry_after(self, value: str | None) -> float | None:
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                seconds = (date - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return None
        if not math.isfinite(seconds):
            return None
        return min(max(0.0, seconds), self._retry_after_max_s)

    async def _post(
        self, query: str, before_attempt: Callable[[], Awaitable[None]] | None
    ) -> dict[str, Any]:
        uncertain = False
        in_flight = False
        started = monotonic()
        attempt = 0
        try:
            for attempt in range(1, self._max_attempts + 1):
                if before_attempt is not None:
                    await before_attempt()
                started = monotonic()
                in_flight = True
                dependency_event(
                    provider="serper",
                    operation="search",
                    outcome="started",
                    attempt=attempt,
                )
                try:
                    response = await self._client.post(
                        "https://google.serper.dev/search",
                        headers=self._headers,
                        json={"q": query, "num": 10},
                        timeout=self._timeout,
                        follow_redirects=False,
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    in_flight = False
                    safe = pre_dispatch_failure(exc)
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    rejected = status in {400, 401, 403, 404, 422}
                    uncertain = uncertain or not (safe or rejected)
                    dependency_event(
                        provider="serper",
                        operation="search",
                        outcome="uncertain"
                        if uncertain
                        else "not_dispatched"
                        if safe
                        else "rejected",
                        attempt=attempt,
                        started=started,
                        reason=type(exc).__name__,
                        remote_duration_ms=(monotonic() - started) * 1000,
                        retry_scheduled=attempt < self._max_attempts and (safe or status == 429),
                    )
                    if attempt < self._max_attempts and (safe or status == 429):
                        delay = (
                            self._retry_after(exc.response.headers.get("Retry-After"))
                            if isinstance(exc, httpx.HTTPStatusError) and status == 429
                            else None
                        )
                        if delay is None:
                            await retry_delay(attempt)
                        else:
                            await asyncio.sleep(delay)
                        continue
                    raise SerperRequestError(
                        "Serper search failed", outcome="uncertain" if uncertain else "released"
                    ) from exc
                in_flight = False
                dependency_event(
                    provider="serper",
                    operation="search",
                    outcome="succeeded",
                    attempt=attempt,
                    started=started,
                    remote_duration_ms=(monotonic() - started) * 1000,
                )
                try:
                    body = response.json()
                except ValueError as exc:
                    raise SerperRequestError(
                        "Serper returned invalid JSON", outcome="consumed"
                    ) from exc
                if not isinstance(body, dict):
                    raise SerperRequestError("Serper returned invalid body", outcome="consumed")
                return body
        except asyncio.CancelledError as exc:
            outcome = "uncertain" if uncertain or in_flight else "released"
            dependency_event(
                provider="serper",
                operation="search",
                outcome=outcome,
                attempt=attempt,
                started=started,
                reason="cancelled",
            )
            raise SerperCancelled(outcome=outcome) from exc
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
