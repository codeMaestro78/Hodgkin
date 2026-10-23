"""Bounded Semantic Scholar discovery and citation links; neither is evidence."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_api.artifacts.normalization import canonicalize_url
from research_api.providers.retry_policy import pre_dispatch_failure, retry_delay
from research_api.providers.tavily import ProviderRequest, request_fingerprint
from research_api.telemetry import dependency_event

S2_REQUEST_SCHEMA_VERSION = "semantic-scholar-graph-v1"
S2_RESPONSE_SCHEMA_VERSION = "semantic-scholar-graph-v1"
S2_API = "https://api.semanticscholar.org/graph/v1/paper"
PAPER_FIELDS = (
    "title,authors,year,publicationDate,externalIds,venue,citationCount,"
    "abstract,openAccessPdf,url"
)
GRAPH_FIELDS = PAPER_FIELDS
MAX_RESULTS = 10
MAX_ABSTRACT_CHARS = 12_000
_PAPER_ID = re.compile(r"[0-9a-fA-F]{40}\Z")
_DOI = re.compile(r"10\.[0-9]{4,9}/\S+\Z", re.IGNORECASE)


class SemanticScholarRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        outcome: str = "uncertain",
        attempt_count: int = 1,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.attempt_count = attempt_count
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class SemanticScholarCancelledBeforeDispatch(asyncio.CancelledError):
    outcome = "released"

    def __init__(self, *, attempt_count: int) -> None:
        super().__init__("Semantic Scholar request cancelled before dispatch")
        self.attempt_count = attempt_count


class SemanticScholarCancelledAfterDispatch(asyncio.CancelledError):
    outcome = "uncertain"

    def __init__(self, *, attempt_count: int) -> None:
        super().__init__("Semantic Scholar request cancelled after dispatch")
        self.attempt_count = attempt_count


class SemanticScholarCandidate(BaseModel):
    """Index metadata only. Abstracts, counts, and links are not source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paper_id: str = Field(pattern=r"^[0-9a-f]{40}$")
    doi: str | None = Field(default=None, max_length=2048)
    title: str = Field(min_length=1, max_length=1000)
    authors: tuple[str, ...] = Field(max_length=20)
    publication_year: int | None = Field(default=None, ge=1400, le=2200)
    publication_date: date | None = None
    venue: str | None = Field(default=None, max_length=500)
    citation_count: int | None = Field(default=None, ge=0)
    abstract: str | None = Field(default=None, max_length=MAX_ABSTRACT_CHARS)
    landing_page_url: str | None = Field(default=None, max_length=8192)
    pdf_url: str | None = Field(default=None, max_length=8192)


@dataclass(frozen=True, slots=True)
class SemanticScholarSearchResult:
    candidates: tuple[SemanticScholarCandidate, ...]
    total_count: int | None
    attempt_count: int
    response_schema_version: str = S2_RESPONSE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class SemanticScholarGraphLink:
    source_paper_id: str
    target_paper_id: str
    related_paper: SemanticScholarCandidate


@dataclass(frozen=True, slots=True)
class SemanticScholarGraphResult:
    links: tuple[SemanticScholarGraphLink, ...]
    next_offset: int | None
    attempt_count: int
    response_schema_version: str = S2_RESPONSE_SCHEMA_VERSION


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


def _url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        result = canonicalize_url(value)
        parsed = httpx.URL(result)
    except (ValueError, UnicodeError, httpx.InvalidURL):
        return None
    return result if parsed.scheme in {"http", "https"} and not parsed.userinfo else None


def _doi(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if result.lower().startswith(prefix):
            result = result[len(prefix) :]
            break
    result = result.strip().strip("/").lower()
    return result if len(result) <= 2048 and _DOI.fullmatch(result) else None


def _candidate(raw: object) -> SemanticScholarCandidate | None:
    if not isinstance(raw, dict):
        return None
    raw_id = raw.get("paperId")
    title = _text(raw.get("title"), 1000)
    if not isinstance(raw_id, str) or not _PAPER_ID.fullmatch(raw_id) or title is None:
        return None
    authors: list[str] = []
    if isinstance(raw.get("authors"), list):
        for author in raw["authors"][:20]:
            name = _text(author.get("name"), 300) if isinstance(author, dict) else None
            if name:
                authors.append(name)
    year = raw.get("year")
    if type(year) is not int:
        year = None
    publication_date = None
    if isinstance(raw.get("publicationDate"), str):
        try:
            publication_date = date.fromisoformat(raw["publicationDate"])
        except ValueError:
            pass
    count = raw.get("citationCount")
    if type(count) is not int or count < 0:
        count = None
    ids = raw.get("externalIds")
    pdf = raw.get("openAccessPdf")
    try:
        return SemanticScholarCandidate(
            paper_id=raw_id.lower(),
            doi=_doi(ids.get("DOI")) if isinstance(ids, dict) else None,
            title=title,
            authors=tuple(authors),
            publication_year=year,
            publication_date=publication_date,
            venue=_text(raw.get("venue"), 500),
            citation_count=count,
            abstract=_text(raw.get("abstract"), MAX_ABSTRACT_CHARS),
            landing_page_url=_url(raw.get("url")),
            pdf_url=_url(pdf.get("url")) if isinstance(pdf, dict) else None,
        )
    except ValidationError:
        return None


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        if not math.isfinite(seconds):
            return None
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return min(60.0, max(0.0, seconds))


class SemanticScholarAdapter:
    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 2,
        timeout: float = 20,
    ) -> None:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("Semantic Scholar attempts must be between one and three")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Semantic Scholar timeout must be finite and positive")
        self._max_attempts = max_attempts
        self._timeout = httpx.Timeout(timeout, connect=min(10.0, timeout))
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
        self._headers = {"x-api-key": api_key} if api_key else {}

    @staticmethod
    def search_request(*, query: str, limit: int = 8) -> ProviderRequest:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ValueError("Semantic Scholar query must contain 1-1000 characters")
        if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
            raise ValueError("Semantic Scholar limit must be between 1 and 10")
        payload = {"query": query.strip(), "limit": limit, "fields": PAPER_FIELDS}
        return ProviderRequest(
            operation="search",
            payload=payload,
            fingerprint=request_fingerprint("semantic_scholar:paper.search:v1", payload),
            request_schema_version=S2_REQUEST_SCHEMA_VERSION,
        )

    @staticmethod
    def graph_request(
        *, paper_id: str, direction: Literal["citations", "references"], limit: int = 10,
        offset: int = 0,
    ) -> ProviderRequest:
        if not isinstance(paper_id, str) or not _PAPER_ID.fullmatch(paper_id):
            raise ValueError("Semantic Scholar paper_id must be a 40-character hex ID")
        if direction not in ("citations", "references"):
            raise ValueError("Semantic Scholar graph direction is invalid")
        if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
            raise ValueError("Semantic Scholar graph limit must be between 1 and 10")
        if type(offset) is not int or not 0 <= offset <= 990:
            raise ValueError("Semantic Scholar graph offset must be between 0 and 990")
        payload = {
            "paper_id": paper_id.lower(), "direction": direction, "limit": limit,
            "offset": offset, "fields": GRAPH_FIELDS,
        }
        return ProviderRequest(
            operation=direction,
            payload=payload,
            fingerprint=request_fingerprint(f"semantic_scholar:paper.{direction}:v1", payload),
            request_schema_version=S2_REQUEST_SCHEMA_VERSION,
        )

    async def _get(
        self, request: ProviderRequest, *, path: str, params: dict[str, Any],
        before_attempt: Callable[[], Awaitable[None]] | None,
    ) -> tuple[object, int]:
        for attempt in range(1, self._max_attempts + 1):
            if before_attempt is not None:
                try:
                    await before_attempt()
                except asyncio.CancelledError as exc:
                    raise SemanticScholarCancelledBeforeDispatch(attempt_count=attempt - 1) from exc
            started = asyncio.get_running_loop().time()
            operation = f"paper.{request.operation}"
            dependency_event(
                provider="semantic_scholar", operation=operation,
                outcome="started", attempt=attempt,
            )
            try:
                response = await self._client.get(
                    path, params=params, headers=self._headers,
                    timeout=self._timeout, follow_redirects=False,
                )
                response.raise_for_status()
            except asyncio.CancelledError as exc:
                dependency_event(
                    provider="semantic_scholar", operation=operation, outcome="uncertain",
                    attempt=attempt, started=started, reason="cancelled_after_dispatch",
                )
                raise SemanticScholarCancelledAfterDispatch(attempt_count=attempt) from exc
            except httpx.HTTPError as exc:
                safe = pre_dispatch_failure(exc)
                status = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                rejected = safe or status in {400, 401, 403, 404, 422, 429}
                dependency_event(
                    provider="semantic_scholar", operation=operation,
                    outcome="not_dispatched" if safe else "rejected" if rejected else "uncertain",
                    attempt=attempt, started=started, reason=type(exc).__name__,
                )
                if safe and attempt < self._max_attempts:
                    try:
                        await retry_delay(attempt)
                    except asyncio.CancelledError as cancellation:
                        raise SemanticScholarCancelledBeforeDispatch(
                            attempt_count=attempt
                        ) from cancellation
                    continue
                raise SemanticScholarRequestError(
                    "Semantic Scholar request failed",
                    outcome="released" if rejected else "uncertain",
                    attempt_count=attempt,
                    status_code=status,
                    retry_after_seconds=_retry_after(exc.response.headers.get("Retry-After"))
                    if status == 429 and isinstance(exc, httpx.HTTPStatusError) else None,
                ) from exc
            dependency_event(
                provider="semantic_scholar", operation=operation, outcome="succeeded",
                attempt=attempt, started=started,
                remote_duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
            )
            try:
                return response.json(), attempt
            except ValueError as exc:
                raise SemanticScholarRequestError(
                    "Semantic Scholar returned invalid JSON",
                    outcome="consumed", attempt_count=attempt,
                ) from exc
        raise AssertionError("unreachable")

    async def search(
        self, request: ProviderRequest, *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> SemanticScholarSearchResult:
        try:
            expected = self.search_request(
                query=request.payload["query"], limit=request.payload["limit"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid Semantic Scholar search request") from exc
        if request != expected:
            raise ValueError("Invalid Semantic Scholar search request")
        body, attempt = await self._get(
            request, path=f"{S2_API}/search", params=expected.payload,
            before_attempt=before_attempt,
        )
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise SemanticScholarRequestError(
                "Semantic Scholar response is invalid", outcome="consumed", attempt_count=attempt
            )
        total = body.get("total")
        if type(total) is not int or total < 0:
            total = None
        candidates = tuple(
            paper for raw in body["data"][:expected.payload["limit"]]
            if (paper := _candidate(raw)) is not None
        )
        return SemanticScholarSearchResult(candidates, total, attempt)

    async def graph(
        self, request: ProviderRequest, *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> SemanticScholarGraphResult:
        try:
            payload = request.payload
            expected = self.graph_request(
                paper_id=payload["paper_id"], direction=payload["direction"],
                limit=payload["limit"], offset=payload["offset"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid Semantic Scholar graph request") from exc
        if request != expected:
            raise ValueError("Invalid Semantic Scholar graph request")
        anchor = expected.payload["paper_id"]
        direction = expected.payload["direction"]
        body, attempt = await self._get(
            request, path=f"{S2_API}/{anchor}/{direction}",
            params={key: value for key, value in expected.payload.items()
                    if key not in {"paper_id", "direction"}},
            before_attempt=before_attempt,
        )
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise SemanticScholarRequestError(
                "Semantic Scholar graph response is invalid",
                outcome="consumed", attempt_count=attempt,
            )
        next_offset = body.get("next")
        if type(next_offset) is not int or not expected.payload["offset"] < next_offset <= 990:
            next_offset = None
        nested_key = "citingPaper" if direction == "citations" else "citedPaper"
        links = []
        for raw in body["data"][:expected.payload["limit"]]:
            paper = _candidate(raw.get(nested_key)) if isinstance(raw, dict) else None
            if paper is None or paper.paper_id == anchor:
                continue
            source, target = (
                (paper.paper_id, anchor) if direction == "citations"
                else (anchor, paper.paper_id)
            )
            links.append(SemanticScholarGraphLink(source, target, paper))
        return SemanticScholarGraphResult(tuple(links), next_offset, attempt)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
