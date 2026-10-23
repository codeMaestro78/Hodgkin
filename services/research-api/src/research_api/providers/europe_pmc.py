"""Europe PMC lite search: bounded publication metadata only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_api.providers.tavily import ProviderRequest, request_fingerprint

EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_SCHEMA_VERSION = "europe-pmc-lite-v1"
_SOURCE = re.compile(r"[A-Z]{2,8}\Z")
_ID = re.compile(r"[A-Za-z0-9._-]{1,80}\Z")
_DOI = re.compile(r"10\.[0-9]{4,9}/\S+\Z", re.I)


class EuropePMCRequestError(RuntimeError):
    """The official API failed or returned a malformed discovery response."""


class EuropePMCCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(pattern=r"^[A-Z]{2,8}$")
    record_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=1000)
    authors: str | None = Field(default=None, max_length=1000)
    venue: str | None = Field(default=None, max_length=500)
    publication_year: int | None = Field(default=None, ge=1400, le=2200)
    publication_date: date | None = None
    doi: str | None = Field(default=None, max_length=2048)
    pmid: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,11}$")
    landing_page_url: str = Field(max_length=200)


@dataclass(frozen=True, slots=True)
class EuropePMCSearchResult:
    candidates: tuple[EuropePMCCandidate, ...]
    total_count: int | None
    attempt_count: int = 1
    response_schema_version: str = EUROPE_PMC_SCHEMA_VERSION


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


def _candidate(raw: object) -> EuropePMCCandidate | None:
    if not isinstance(raw, dict):
        return None
    source, record_id = raw.get("source"), raw.get("id")
    if not isinstance(source, str) or not _SOURCE.fullmatch(source):
        return None
    if not isinstance(record_id, str) or not _ID.fullmatch(record_id):
        return None
    title = _text(raw.get("title"), 1000)
    if title is None:
        return None
    year = raw.get("pubYear")
    publication_year = (
        int(year) if isinstance(year, str) and year.isascii() and year.isdecimal() else None
    )
    published = raw.get("firstPublicationDate")
    try:
        publication_date = date.fromisoformat(published) if isinstance(published, str) else None
    except ValueError:
        publication_date = None
    raw_doi = _text(raw.get("doi"), 2048)
    doi = raw_doi.lower() if raw_doi and _DOI.fullmatch(raw_doi) else None
    pmid = raw.get("pmid")
    pmid = pmid if isinstance(pmid, str) and re.fullmatch(r"[1-9][0-9]{0,11}", pmid) else None
    try:
        return EuropePMCCandidate(
            source=source,
            record_id=record_id,
            title=title,
            authors=_text(raw.get("authorString"), 1000),
            venue=_text(raw.get("journalTitle"), 500),
            publication_year=publication_year,
            publication_date=publication_date,
            doi=doi,
            pmid=pmid,
            landing_page_url=f"https://europepmc.org/article/{source}/{record_id}",
        )
    except ValidationError:
        return None


class EuropePMCAdapter:
    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 20) -> None:
        if not 0 < timeout <= 60:
            raise ValueError("Europe PMC timeout must be between zero and 60 seconds")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
        self._timeout = httpx.Timeout(timeout, connect=min(10, timeout))

    @staticmethod
    def search_request(*, query: str, per_page: int = 8) -> ProviderRequest:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ValueError("Europe PMC query must contain 1 to 1000 characters")
        if type(per_page) is not int or not 1 <= per_page <= 10:
            raise ValueError("Europe PMC per_page must be between one and ten")
        payload = {
            "query": query.strip(),
            "pageSize": per_page,
            "resultType": "lite",
            "format": "json",
        }
        return ProviderRequest(
            "search",
            payload,
            request_fingerprint("europe-pmc:search:v1", payload),
            request_schema_version=EUROPE_PMC_SCHEMA_VERSION,
        )

    async def search(self, request: ProviderRequest) -> EuropePMCSearchResult:
        payload = request.payload
        try:
            expected = self.search_request(query=payload["query"], per_page=payload["pageSize"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid Europe PMC search request") from exc
        if request != expected:
            raise ValueError("Invalid Europe PMC search request")
        try:
            response = await self._client.get(
                EUROPE_PMC_API, params=payload, timeout=self._timeout, follow_redirects=False
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise EuropePMCRequestError("Europe PMC response exceeds metadata limit")
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EuropePMCRequestError(
                "Europe PMC request failed or returned invalid JSON"
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("resultList"), dict):
            raise EuropePMCRequestError("Europe PMC response is invalid")
        results = body["resultList"].get("result")
        if not isinstance(results, list):
            raise EuropePMCRequestError("Europe PMC response is invalid")
        count = body.get("hitCount")
        total = count if type(count) is int and count >= 0 else None
        candidates = tuple(
            candidate
            for raw in results[: payload["pageSize"]]
            if (candidate := _candidate(raw)) is not None
        )
        return EuropePMCSearchResult(candidates, total)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
