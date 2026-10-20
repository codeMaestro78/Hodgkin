from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_api.artifacts.normalization import canonicalize_url
from research_api.providers.retry_policy import pre_dispatch_failure, retry_delay
from research_api.telemetry import dependency_event

TAVILY_REQUEST_SCHEMA_VERSION = "2026-09-28"
TAVILY_RESPONSE_SCHEMA_VERSION = "2026-09-28"


class TavilyRequestError(RuntimeError):
    def __init__(self, message: str, *, outcome: str = "uncertain") -> None:
        super().__init__(message)
        self.outcome = outcome


class TavilyAmbiguousTimeoutError(TavilyRequestError):
    pass


class TavilyCancelledBeforeDispatch(asyncio.CancelledError):
    outcome = "released"


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str
    title: str = "Untitled source"
    content: str = ""
    score: float = 0.0
    published_date: str | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    results: list[SearchResult] = Field(default_factory=list)
    request_id: str | None = None
    usage: dict[str, Any] | None = None


class ExtractResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str
    raw_content: str


class ExtractFailure(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str
    error: str


class ExtractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    results: list[ExtractResult] = Field(default_factory=list)
    failed_results: list[ExtractFailure] = Field(default_factory=list)
    request_id: str | None = None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    operation: str
    payload: dict[str, Any]
    fingerprint: str
    request_schema_version: str = TAVILY_REQUEST_SCHEMA_VERSION


def request_fingerprint(operation: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"operation": operation, "payload": payload}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class TavilyAdapter:
    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 3,
        timeout: float = 30,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("Tavily attempts must be between one and three")
        self._max_attempts = max_attempts
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url="https://api.tavily.com",
            timeout=httpx.Timeout(timeout, connect=min(10, timeout)),
        )
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    @staticmethod
    def search_request(
        *, query: str, max_results: int = 6, allowed_domains: list[str] | None = None
    ) -> ProviderRequest:
        payload: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "chunks_per_source": 3,
            "max_results": min(max(max_results, 1), 6),
            "include_answer": False,
            "include_raw_content": False,
            "include_usage": True,
            "include_domains": allowed_domains or [],
        }
        return ProviderRequest("search", payload, request_fingerprint("search", payload))

    @staticmethod
    def extract_request(*, urls: list[str], query: str) -> ProviderRequest:
        canonical_urls = sorted({canonicalize_url(url) for url in urls})
        if not canonical_urls or len(canonical_urls) > 20:
            raise ValueError("Tavily Extract requires between 1 and 20 unique HTTP(S) URLs")
        payload: dict[str, Any] = {
            "urls": canonical_urls,
            "query": query,
            "chunks_per_source": 3,
            "extract_depth": "basic",
            "format": "markdown",
            "include_images": False,
            "include_usage": True,
        }
        return ProviderRequest("extract", payload, request_fingerprint("extract", payload))

    async def search(
        self,
        request: ProviderRequest,
        *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> SearchResponse:
        data = await self._post("/search", request.payload, before_attempt=before_attempt)
        try:
            response = SearchResponse.model_validate(data)
        except ValidationError as exc:
            raise TavilyRequestError(
                "Tavily search response is invalid", outcome="consumed"
            ) from exc
        filtered = self._post_filter(response.results, request.payload)
        return response.model_copy(
            update={"results": filtered[: int(request.payload["max_results"])]}
        )

    async def extract(
        self,
        request: ProviderRequest,
        *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> ExtractResponse:
        data = await self._post("/extract", request.payload, before_attempt=before_attempt)
        try:
            return ExtractResponse.model_validate(data)
        except ValidationError as exc:
            raise TavilyRequestError(
                "Tavily extract response is invalid", outcome="consumed"
            ) from exc

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(1, self._max_attempts + 1):
            if before_attempt is not None:
                try:
                    await before_attempt()
                except asyncio.CancelledError as exc:
                    # This gate runs before any network attempt. Earlier attempts
                    # can only be proven non-dispatched connect failures.
                    raise TavilyCancelledBeforeDispatch from exc
            started = monotonic()
            dependency_event(
                provider="tavily",
                operation=path.lstrip("/"),
                outcome="started",
                attempt=attempt,
            )
            try:
                response = await self._client.post(path, headers=self._headers, json=payload)
                response.raise_for_status()
                dependency_event(
                    provider="tavily",
                    operation=path.lstrip("/"),
                    outcome="succeeded",
                    attempt=attempt,
                    started=started,
                    remote_duration_ms=(monotonic() - started) * 1000,
                )
                break
            except httpx.HTTPError as exc:
                safe = pre_dispatch_failure(exc)
                dependency_event(
                    provider="tavily",
                    operation=path.lstrip("/"),
                    outcome="not_dispatched" if safe else "uncertain",
                    attempt=attempt,
                    started=started,
                    reason=type(exc).__name__,
                    remote_duration_ms=(monotonic() - started) * 1000,
                )
                if safe and attempt < self._max_attempts:
                    try:
                        await retry_delay(attempt)
                    except asyncio.CancelledError as cancellation:
                        raise TavilyCancelledBeforeDispatch from cancellation
                    continue
                status = getattr(getattr(exc, "response", None), "status_code", None)
                outcome = "released" if safe or status in {400, 401, 403, 404, 422} else "uncertain"
                if isinstance(exc, httpx.TimeoutException) and not safe:
                    raise TavilyAmbiguousTimeoutError(
                        "Tavily request timed out after dispatch"
                    ) from exc
                raise TavilyRequestError("Tavily request failed", outcome=outcome) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise TavilyRequestError("Tavily returned invalid JSON", outcome="consumed") from exc
        if not isinstance(body, dict):
            raise TavilyRequestError("Tavily returned a non-object response", outcome="consumed")
        return body

    @staticmethod
    def _post_filter(results: list[SearchResult], payload: dict[str, Any]) -> list[SearchResult]:
        domains = {domain.lower().lstrip(".") for domain in payload.get("include_domains", [])}
        filtered: list[SearchResult] = []
        for result in results:
            try:
                hostname = httpx.URL(canonicalize_url(result.url)).host.lower()
            except (ValueError, UnicodeError):
                dependency_event(
                    provider="tavily", operation="source", outcome="rejected", reason="invalid_url"
                )
                continue
            if not domains or any(
                hostname == domain or hostname.endswith(f".{domain}") for domain in domains
            ):
                filtered.append(result)
        return filtered

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
