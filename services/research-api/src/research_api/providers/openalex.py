"""Bounded OpenAlex works discovery; metadata is never citation evidence."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_api.artifacts.normalization import canonicalize_url
from research_api.providers.retry_policy import (
    pre_dispatch_failure,
    rejected_without_usage,
    retry_delay,
)
from research_api.providers.tavily import ProviderRequest, request_fingerprint
from research_api.telemetry import dependency_event

OPENALEX_REQUEST_SCHEMA_VERSION = "openalex-works-v1"
OPENALEX_RESPONSE_SCHEMA_VERSION = "openalex-works-v1"
OPENALEX_API = "https://api.openalex.org/works"
MAX_QUERY_CHARS = 1000
MAX_PAGE_SIZE = 10
MAX_AUTHORS = 20
MAX_ABSTRACT_CHARS = 12_000
OPENALEX_WORK_ID = re.compile(r"W[0-9]+\Z")
DOI_PATTERN = re.compile(r"10\.[0-9]{4,9}/\S+\Z", re.IGNORECASE)
WORK_FIELDS = (
    "id,doi,title,publication_year,publication_date,type,cited_by_count,"
    "authorships,primary_location,best_oa_location,locations,open_access,abstract_inverted_index"
)


class OpenAlexRequestError(RuntimeError):
    def __init__(self, message: str, *, outcome: str = "uncertain", attempt_count: int = 1) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.attempt_count = attempt_count


class OpenAlexCancelledBeforeDispatch(asyncio.CancelledError):
    outcome = "released"

    def __init__(self, *, attempt_count: int) -> None:
        super().__init__("OpenAlex search cancelled before dispatch")
        self.attempt_count = attempt_count


class OpenAlexCancelledAfterDispatch(asyncio.CancelledError):
    outcome = "uncertain"

    def __init__(self, *, attempt_count: int) -> None:
        super().__init__("OpenAlex search cancelled after dispatch")
        self.attempt_count = attempt_count


class OpenAlexCandidate(BaseModel):
    """Normalized index metadata. This object must not be passed as source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_id: str = Field(min_length=1, max_length=100)
    doi: str | None = Field(default=None, max_length=2048)
    title: str = Field(min_length=1, max_length=1000)
    authors: tuple[str, ...] = Field(max_length=MAX_AUTHORS)
    publication_year: int | None = Field(default=None, ge=1400, le=2200)
    publication_date: date | None = None
    work_type: str | None = Field(default=None, max_length=100)
    venue: str | None = Field(default=None, max_length=500)
    citation_count: int | None = Field(default=None, ge=0)
    abstract: str | None = Field(default=None, max_length=MAX_ABSTRACT_CHARS)
    open_access: bool | None = None
    landing_page_url: str | None = Field(default=None, max_length=8192)
    pdf_url: str | None = Field(default=None, max_length=8192)


@dataclass(frozen=True, slots=True)
class OpenAlexSearchResult:
    candidates: tuple[OpenAlexCandidate, ...]
    total_count: int | None
    reported_cost_usd: float | None
    attempt_count: int
    response_schema_version: str = OPENALEX_RESPONSE_SCHEMA_VERSION


def _bounded_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:limit] or None


def _safe_http_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        normalized = canonicalize_url(value)
        parsed = httpx.URL(normalized)
    except (ValueError, UnicodeError, httpx.InvalidURL):
        return None
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    return normalized


def _normalize_doi(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip().strip("/").lower()
    if len(doi) > 2048 or DOI_PATTERN.fullmatch(doi) is None:
        return None
    if any(char.isspace() or ord(char) < 32 for char in doi):
        return None
    return doi


def _abstract_from_inverted_index(value: object) -> str | None:
    if not isinstance(value, dict) or len(value) > 100_000:
        return None
    positioned: list[tuple[int, str]] = []
    for token, positions in value.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        safe_token = _bounded_text(token, 200)
        if safe_token is None:
            continue
        for position in positions:
            if (
                isinstance(position, int)
                and not isinstance(position, bool)
                and 0 <= position < 100_000
            ):
                positioned.append((position, safe_token))
                if len(positioned) >= 20_000:
                    break
        if len(positioned) >= 20_000:
            break
    if not positioned:
        return None
    text = " ".join(token for _, token in sorted(positioned))
    return text[:MAX_ABSTRACT_CHARS] or None


def _open_access_urls(
    work: dict[str, Any], open_access: bool | None
) -> tuple[str | None, str | None]:
    best = work.get("best_oa_location")
    best = best if isinstance(best, dict) else {}
    locations = work.get("locations")
    locations = locations if isinstance(locations, list) else []

    landing = _safe_http_url(best.get("landing_page_url"))
    if landing:
        pdf = _safe_http_url(best.get("pdf_url"))
        return landing, pdf

    for location in locations:
        if not isinstance(location, dict) or location.get("is_oa") is not True:
            continue
        landing = _safe_http_url(location.get("landing_page_url"))
        if landing:
            return landing, _safe_http_url(location.get("pdf_url"))

    if open_access is True:
        pdf = _safe_http_url(best.get("pdf_url"))
        if pdf:
            return None, pdf
        for location in locations:
            if isinstance(location, dict) and location.get("is_oa") is True:
                pdf = _safe_http_url(location.get("pdf_url"))
                if pdf:
                    return None, pdf
    return None, None


def _candidate(raw: object) -> OpenAlexCandidate | None:
    if not isinstance(raw, dict):
        return None
    raw_id = raw.get("id")
    work_id = raw_id.rsplit("/", 1)[-1] if isinstance(raw_id, str) else ""
    title = _bounded_text(raw.get("title"), 1000)
    if OPENALEX_WORK_ID.fullmatch(work_id) is None or title is None:
        return None

    authorships = raw.get("authorships")
    authors: list[str] = []
    if isinstance(authorships, list):
        for authorship in authorships[:MAX_AUTHORS]:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author")
            name = (
                _bounded_text(author.get("display_name"), 300) if isinstance(author, dict) else None
            )
            if name:
                authors.append(name)

    publication_year = raw.get("publication_year")
    if isinstance(publication_year, bool) or not isinstance(publication_year, int):
        publication_year = None
    publication_date: date | None = None
    raw_date = raw.get("publication_date")
    if isinstance(raw_date, str):
        try:
            publication_date = date.fromisoformat(raw_date)
        except ValueError:
            pass

    citation_count = raw.get("cited_by_count")
    if (
        isinstance(citation_count, bool)
        or not isinstance(citation_count, int)
        or citation_count < 0
    ):
        citation_count = None
    oa = raw.get("open_access")
    open_access = (
        oa.get("is_oa") if isinstance(oa, dict) and isinstance(oa.get("is_oa"), bool) else None
    )
    landing, pdf = _open_access_urls(raw, open_access)
    primary_location = raw.get("primary_location")
    source = primary_location.get("source") if isinstance(primary_location, dict) else None
    venue = _bounded_text(source.get("display_name"), 500) if isinstance(source, dict) else None
    work_type = _bounded_text(raw.get("type"), 100)

    try:
        return OpenAlexCandidate(
            work_id=work_id,
            doi=_normalize_doi(raw.get("doi")),
            title=title,
            authors=tuple(authors),
            publication_year=publication_year,
            publication_date=publication_date,
            work_type=work_type,
            venue=venue,
            citation_count=citation_count,
            abstract=_abstract_from_inverted_index(raw.get("abstract_inverted_index")),
            open_access=open_access,
            landing_page_url=landing,
            pdf_url=pdf,
        )
    except ValidationError:
        return None


class OpenAlexAdapter:
    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 2,
        timeout: float = 20,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("OpenAlex attempts must be between one and three")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("OpenAlex timeout must be finite and positive")
        self._max_attempts = max_attempts
        self._timeout = httpx.Timeout(timeout, connect=min(10, timeout))
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    @staticmethod
    def search_request(
        *,
        query: str,
        per_page: int = 8,
        selection_limit: int | None = None,
        from_publication_date: str | None = None,
        to_publication_date: str | None = None,
        is_oa: bool | None = None,
    ) -> ProviderRequest:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= MAX_QUERY_CHARS:
            raise ValueError(
                f"OpenAlex query must contain between 1 and {MAX_QUERY_CHARS} characters"
            )
        if (
            not isinstance(per_page, int)
            or isinstance(per_page, bool)
            or not 1 <= per_page <= MAX_PAGE_SIZE
        ):
            raise ValueError(f"OpenAlex per_page must be between 1 and {MAX_PAGE_SIZE}")
        selection_limit = per_page if selection_limit is None else selection_limit
        if (
            not isinstance(selection_limit, int)
            or isinstance(selection_limit, bool)
            or not 1 <= selection_limit <= per_page
        ):
            raise ValueError("OpenAlex selection_limit must be between one and per_page")
        filters: dict[str, Any] = {"search": query.strip(), "per_page": per_page}
        # This is local routing identity; it is stripped before sending provider
        # query parameters so changing the extraction cap cannot replay another
        # run's shortlist or leak an unsupported parameter to OpenAlex.
        filters["selection_limit"] = selection_limit
        filters["select"] = WORK_FIELDS
        for name, value in (
            ("from_publication_date", from_publication_date),
            ("to_publication_date", to_publication_date),
        ):
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be an ISO date")
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{name} must be an ISO date") from exc
                filters[name] = value
        if is_oa is not None:
            if not isinstance(is_oa, bool):
                raise ValueError("is_oa must be a boolean")
            filters["is_oa"] = is_oa
        if (
            from_publication_date is not None
            and to_publication_date is not None
            and from_publication_date > to_publication_date
        ):
            raise ValueError("publication date range is inverted")
        return ProviderRequest(
            operation="search",
            payload=filters,
            fingerprint=request_fingerprint("openalex:works.search:v1", filters),
            request_schema_version=OPENALEX_REQUEST_SCHEMA_VERSION,
        )

    async def search(
        self,
        request: ProviderRequest,
        *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> OpenAlexSearchResult:
        try:
            payload = request.payload
            if "search" not in payload:
                raise ValueError("missing search")
            sanitized = self.search_request(
                query=payload["search"],
                per_page=payload.get("per_page", 8),
                selection_limit=payload.get("selection_limit"),
                from_publication_date=payload.get("from_publication_date"),
                to_publication_date=payload.get("to_publication_date"),
                is_oa=payload.get("is_oa"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid OpenAlex search request") from exc
        if request != sanitized:
            raise ValueError("Invalid OpenAlex search request")

        response: httpx.Response | None = None
        for attempt in range(1, self._max_attempts + 1):
            if before_attempt is not None:
                try:
                    await before_attempt()
                except asyncio.CancelledError as exc:
                    raise OpenAlexCancelledBeforeDispatch(attempt_count=attempt - 1) from exc
            started = asyncio.get_running_loop().time()
            dependency_event(
                provider="openalex",
                operation="works.search",
                outcome="started",
                attempt=attempt,
            )
            try:
                response = await self._client.get(
                    OPENALEX_API,
                    params={
                        key: value
                        for key, value in sanitized.payload.items()
                        if key != "selection_limit"
                    },
                    headers=self._headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                )
                response.raise_for_status()
                dependency_event(
                    provider="openalex",
                    operation="works.search",
                    outcome="succeeded",
                    attempt=attempt,
                    started=started,
                    remote_duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
                )
                break
            except asyncio.CancelledError as exc:
                dependency_event(
                    provider="openalex",
                    operation="works.search",
                    outcome="uncertain",
                    attempt=attempt,
                    started=started,
                    reason="cancelled_after_dispatch",
                    remote_duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
                )
                raise OpenAlexCancelledAfterDispatch(attempt_count=attempt) from exc
            except httpx.HTTPError as exc:
                safe = pre_dispatch_failure(exc)
                rejected = rejected_without_usage(exc) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in {400, 401, 403, 404, 422, 429}
                )
                dependency_event(
                    provider="openalex",
                    operation="works.search",
                    outcome="not_dispatched" if safe else "rejected" if rejected else "uncertain",
                    attempt=attempt,
                    started=started,
                    reason=type(exc).__name__,
                    remote_duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
                )
                if safe and attempt < self._max_attempts:
                    try:
                        await retry_delay(attempt)
                    except asyncio.CancelledError as cancellation:
                        raise OpenAlexCancelledBeforeDispatch(
                            attempt_count=attempt
                        ) from cancellation
                    continue
                outcome = "released" if rejected else "uncertain"
                if isinstance(exc, httpx.TimeoutException) and not safe:
                    raise OpenAlexRequestError(
                        "OpenAlex request timed out after dispatch",
                        outcome=outcome,
                        attempt_count=attempt,
                    ) from exc
                raise OpenAlexRequestError(
                    "OpenAlex request failed", outcome=outcome, attempt_count=attempt
                ) from exc

        assert response is not None
        try:
            body = response.json()
        except ValueError as exc:
            raise OpenAlexRequestError(
                "OpenAlex returned invalid JSON", outcome="consumed", attempt_count=attempt
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise OpenAlexRequestError(
                "OpenAlex response is invalid", outcome="consumed", attempt_count=attempt
            )

        metadata = body.get("meta")
        metadata = metadata if isinstance(metadata, dict) else {}
        total_count = metadata.get("count")
        if isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0:
            total_count = None
        raw_cost = metadata.get("cost_usd")
        reported_cost = (
            float(raw_cost)
            if isinstance(raw_cost, (int, float))
            and not isinstance(raw_cost, bool)
            and math.isfinite(raw_cost)
            and raw_cost >= 0
            else None
        )
        candidates = tuple(
            candidate
            for raw in body["results"][: sanitized.payload["per_page"]]
            if (candidate := _candidate(raw)) is not None
        )
        return OpenAlexSearchResult(
            candidates=candidates,
            total_count=total_count,
            reported_cost_usd=reported_cost,
            attempt_count=attempt,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
