"""Crossref single-work lookup. Returned metadata is never citation evidence."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from datetime import date
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from research_api.providers.doi import normalize_doi
from research_api.providers.retry_policy import pre_dispatch_failure, retry_delay
from research_api.providers.tavily import ProviderRequest, request_fingerprint
from research_api.telemetry import dependency_event

CROSSREF_REQUEST_SCHEMA_VERSION = "crossref-work-v1"
CROSSREF_RESPONSE_SCHEMA_VERSION = "crossref-work-v2"
CROSSREF_API = "https://api.crossref.org/works/"
MAX_ABSTRACT_CHARS = 12_000
MAX_FUNDERS = 20
MAX_LICENSES = 10
MAX_AFFILIATIONS_PER_AUTHOR = 10


class CrossrefRequestError(RuntimeError):
    def __init__(self, message: str, *, outcome: str, attempt_count: int) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.attempt_count = attempt_count


class CrossrefCancelledBeforeDispatch(asyncio.CancelledError):
    outcome = "released"

    def __init__(self, *, attempt_count: int) -> None:
        super().__init__("Crossref lookup cancelled before dispatch")
        self.attempt_count = attempt_count


class CrossrefCancelledAfterDispatch(asyncio.CancelledError):
    outcome = "uncertain"

    def __init__(self, *, attempt_count: int) -> None:
        super().__init__("Crossref lookup cancelled after dispatch")
        self.attempt_count = attempt_count


class CrossrefFunder(BaseModel):
    """Deposited funding metadata for discovery, not proof of funding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, max_length=300)
    doi: str | None = Field(default=None, max_length=2048)
    award_numbers: tuple[str, ...] = Field(max_length=10)


class CrossrefLicense(BaseModel):
    """Deposited license reference; it does not establish full-text availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(max_length=2048)
    start_date: date | None = None
    content_version: str | None = Field(default=None, max_length=100)


class CrossrefMetadata(BaseModel):
    """Bounded discovery-only metadata, never extracted claim evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_status: Literal["discovery_only"] = "discovery_only"
    doi: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=1000)
    authors: tuple[str, ...] = Field(max_length=20)
    # Positional match to authors; each inner tuple is that author's affiliations.
    author_affiliations: tuple[tuple[str, ...], ...] = Field(max_length=20)
    publication_date: date | None = None
    work_type: str | None = Field(default=None, max_length=100)
    venue: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=500)
    citation_count: int | None = Field(default=None, ge=0)
    abstract: str | None = Field(default=None, max_length=MAX_ABSTRACT_CHARS)
    funders: tuple[CrossrefFunder, ...] = Field(max_length=MAX_FUNDERS)
    licenses: tuple[CrossrefLicense, ...] = Field(max_length=MAX_LICENSES)
    landing_page_url: str = Field(max_length=8192)


class CrossrefLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: CrossrefMetadata
    attempt_count: int
    response_schema_version: str = CROSSREF_RESPONSE_SCHEMA_VERSION


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


class _AbstractText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def _abstract(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parser = _AbstractText()
    parser.feed(value[: MAX_ABSTRACT_CHARS * 4])
    parser.close()
    return _text(" ".join(parser.parts), MAX_ABSTRACT_CHARS)


def _date_parts(value: object) -> date | None:
    parts = value.get("date-parts") if isinstance(value, dict) else None
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None
    values = parts[0]
    if not 1 <= len(values) <= 3 or any(type(part) is not int for part in values):
        return None
    try:
        return date(
            values[0], values[1] if len(values) > 1 else 1, values[2] if len(values) > 2 else 1
        )
    except ValueError:
        return None


def _publication_date(message: dict[str, Any]) -> date | None:
    for key in ("published", "published-print", "published-online", "issued"):
        if parsed := _date_parts(message.get(key)):
            return parsed
    return None


def _url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            return None
        _ = parsed.port  # Validate malformed ports without changing the deposited URL.
    except ValueError:
        return None
    return value


def _funders(value: object) -> tuple[CrossrefFunder, ...]:
    if not isinstance(value, list):
        return ()
    result: list[CrossrefFunder] = []
    for item in value[: MAX_FUNDERS * 2]:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 300)
        doi = normalize_doi(item.get("DOI"))
        if name is None and doi is None:
            continue
        awards = item.get("award")
        award_numbers = (
            tuple(number for raw in awards[:10] if (number := _text(raw, 100)))
            if isinstance(awards, list)
            else ()
        )
        result.append(CrossrefFunder(name=name, doi=doi, award_numbers=award_numbers))
        if len(result) == MAX_FUNDERS:
            break
    return tuple(result)


def _licenses(value: object) -> tuple[CrossrefLicense, ...]:
    if not isinstance(value, list):
        return ()
    result: list[CrossrefLicense] = []
    for item in value[: MAX_LICENSES * 2]:
        if not isinstance(item, dict) or (url := _url(item.get("URL"))) is None:
            continue
        result.append(
            CrossrefLicense(
                url=url,
                start_date=_date_parts(item.get("start")),
                content_version=_text(item.get("content-version"), 100),
            )
        )
        if len(result) == MAX_LICENSES:
            break
    return tuple(result)


def _metadata(message: dict[str, Any], requested_doi: str, attempt: int) -> CrossrefMetadata:
    returned_doi = normalize_doi(message.get("DOI"))
    if returned_doi != requested_doi:
        raise CrossrefRequestError(
            "Crossref returned a different DOI", outcome="consumed", attempt_count=attempt
        )
    titles = message.get("title")
    title = _text(titles[0], 1000) if isinstance(titles, list) and titles else None
    authors: list[str] = []
    affiliations: list[tuple[str, ...]] = []
    raw_authors = message.get("author")
    if isinstance(raw_authors, list):
        for item in raw_authors[:20]:
            if not isinstance(item, dict):
                continue
            name = _text(
                " ".join(
                    part
                    for part in (item.get("given"), item.get("family"))
                    if isinstance(part, str)
                ),
                300,
            )
            if name:
                authors.append(name)
                raw_affiliations = item.get("affiliation")
                affiliations.append(
                    tuple(
                        label
                        for affiliation in raw_affiliations[:MAX_AFFILIATIONS_PER_AUTHOR]
                        if isinstance(affiliation, dict)
                        if (label := _text(affiliation.get("name"), 300))
                    )
                    if isinstance(raw_affiliations, list)
                    else ()
                )
    containers = message.get("container-title")
    venue = _text(containers[0], 500) if isinstance(containers, list) and containers else None
    citation_count = message.get("is-referenced-by-count")
    if type(citation_count) is not int or citation_count < 0:
        citation_count = None
    return CrossrefMetadata(
        doi=requested_doi,
        title=title,
        authors=tuple(authors),
        author_affiliations=tuple(affiliations),
        publication_date=_publication_date(message),
        work_type=_text(message.get("type"), 100),
        venue=venue,
        publisher=_text(message.get("publisher"), 500),
        citation_count=citation_count,
        abstract=_abstract(message.get("abstract")),
        funders=_funders(message.get("funder")),
        licenses=_licenses(message.get("license")),
        landing_page_url=f"https://doi.org/{quote(requested_doi, safe='/')}",
    )


class CrossrefAdapter:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 2,
        timeout: float = 20,
    ) -> None:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("Crossref attempts must be between one and three")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Crossref timeout must be finite and positive")
        self._max_attempts = max_attempts
        self._timeout = httpx.Timeout(timeout, connect=min(10, timeout))
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()

    @staticmethod
    def lookup_request(*, doi: str) -> ProviderRequest:
        normalized = normalize_doi(doi)
        if normalized is None:
            raise ValueError("Invalid DOI")
        payload = {"doi": normalized}
        return ProviderRequest(
            operation="works.lookup",
            payload=payload,
            fingerprint=request_fingerprint("crossref:works.lookup:v1", payload),
            request_schema_version=CROSSREF_REQUEST_SCHEMA_VERSION,
        )

    async def lookup(
        self,
        request: ProviderRequest,
        *,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> CrossrefLookupResult:
        try:
            payload = request.payload
            if set(payload) != {"doi"} or payload["doi"] != normalize_doi(payload["doi"]):
                raise ValueError
            sanitized = self.lookup_request(doi=payload["doi"])
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            raise ValueError("Invalid Crossref lookup request") from exc
        if request != sanitized:
            raise ValueError("Invalid Crossref lookup request")

        response: httpx.Response | None = None
        for attempt in range(1, self._max_attempts + 1):
            if before_attempt is not None:
                try:
                    await before_attempt()
                except asyncio.CancelledError as exc:
                    raise CrossrefCancelledBeforeDispatch(attempt_count=attempt - 1) from exc
            started = asyncio.get_running_loop().time()
            dependency_event(
                provider="crossref", operation="works.lookup", outcome="started", attempt=attempt
            )
            try:
                response = await self._client.get(
                    CROSSREF_API + quote(sanitized.payload["doi"], safe="/"),
                    headers={"Accept": "application/json"},
                    timeout=self._timeout,
                    follow_redirects=False,
                )
                response.raise_for_status()
                dependency_event(
                    provider="crossref",
                    operation="works.lookup",
                    outcome="succeeded",
                    attempt=attempt,
                    started=started,
                    remote_duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
                )
                break
            except asyncio.CancelledError as exc:
                dependency_event(
                    provider="crossref",
                    operation="works.lookup",
                    outcome="uncertain",
                    attempt=attempt,
                    started=started,
                    reason="cancelled_after_dispatch",
                    remote_duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
                )
                raise CrossrefCancelledAfterDispatch(attempt_count=attempt) from exc
            except httpx.HTTPError as exc:
                safe = pre_dispatch_failure(exc)
                status = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                rejected = status in {400, 401, 403, 404, 422}
                dependency_event(
                    provider="crossref",
                    operation="works.lookup",
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
                        raise CrossrefCancelledBeforeDispatch(
                            attempt_count=attempt
                        ) from cancellation
                    continue
                raise CrossrefRequestError(
                    "Crossref lookup failed",
                    outcome="released" if safe or rejected else "uncertain",
                    attempt_count=attempt,
                ) from exc

        assert response is not None
        try:
            body = response.json()
        except ValueError as exc:
            raise CrossrefRequestError(
                "Crossref returned invalid JSON", outcome="consumed", attempt_count=attempt
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("message"), dict):
            raise CrossrefRequestError(
                "Crossref response is invalid", outcome="consumed", attempt_count=attempt
            )
        return CrossrefLookupResult(
            metadata=_metadata(body["message"], sanitized.payload["doi"], attempt),
            attempt_count=attempt,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
