from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from research_api.artifacts.normalization import canonicalize_url

TAVILY_REQUEST_SCHEMA_VERSION = "2026-09-28"
TAVILY_RESPONSE_SCHEMA_VERSION = "2026-09-28"


class TavilyRequestError(RuntimeError):
    pass


class TavilyAmbiguousTimeoutError(TavilyRequestError):
    pass


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
    def __init__(self, *, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url="https://api.tavily.com", timeout=httpx.Timeout(30.0, connect=10.0)
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

    async def search(self, request: ProviderRequest) -> SearchResponse:
        data = await self._post("/search", request.payload)
        response = SearchResponse.model_validate(data)
        filtered = self._post_filter(response.results, request.payload)
        return response.model_copy(
            update={"results": filtered[: int(request.payload["max_results"])]}
        )

    async def extract(self, request: ProviderRequest) -> ExtractResponse:
        return ExtractResponse.model_validate(await self._post("/extract", request.payload))

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, headers=self._headers, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TavilyAmbiguousTimeoutError("Tavily request timed out after dispatch") from exc
        except httpx.HTTPError as exc:
            raise TavilyRequestError("Tavily request failed") from exc
        body = response.json()
        if not isinstance(body, dict):
            raise TavilyRequestError("Tavily returned a non-object response")
        return body

    @staticmethod
    def _post_filter(results: list[SearchResult], payload: dict[str, Any]) -> list[SearchResult]:
        domains = {domain.lower().lstrip(".") for domain in payload.get("include_domains", [])}
        if not domains:
            return results
        filtered: list[SearchResult] = []
        for result in results:
            hostname = httpx.URL(canonicalize_url(result.url)).host.lower()
            if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
                filtered.append(result)
        return filtered

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
