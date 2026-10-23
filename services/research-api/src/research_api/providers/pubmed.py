"""Bounded PubMed ESearch/ESummary discovery; summaries are metadata, not evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_api.providers.tavily import ProviderRequest, request_fingerprint

PUBMED_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_SCHEMA_VERSION = "pubmed-esummary-v1"
_PMID = re.compile(r"[1-9][0-9]{0,11}\Z")
_DOI = re.compile(r"10\.[0-9]{4,9}/\S+\Z", re.I)


class PubMedRequestError(RuntimeError):
    """The official API failed or returned a malformed discovery response."""


class PubMedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pmid: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    title: str = Field(min_length=1, max_length=1000)
    authors: tuple[str, ...] = Field(max_length=20)
    venue: str | None = Field(default=None, max_length=500)
    publication_date: str | None = Field(default=None, max_length=40)
    doi: str | None = Field(default=None, max_length=2048)
    landing_page_url: str = Field(pattern=r"^https://pubmed\.ncbi\.nlm\.nih\.gov/[1-9][0-9]*/$")


@dataclass(frozen=True, slots=True)
class PubMedSearchResult:
    candidates: tuple[PubMedCandidate, ...]
    total_count: int | None
    attempt_count: int
    response_schema_version: str = PUBMED_SCHEMA_VERSION


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


def _candidate(pmid: str, raw: object) -> PubMedCandidate | None:
    if _PMID.fullmatch(pmid) is None or not isinstance(raw, dict):
        return None
    if raw.get("uid") != pmid:
        return None
    title = _text(raw.get("title"), 1000)
    if title is None:
        return None
    authors_raw = raw.get("authors")
    authors = tuple(
        name
        for author in (authors_raw[:20] if isinstance(authors_raw, list) else [])
        if isinstance(author, dict)
        if (name := _text(author.get("name"), 300)) is not None
    )
    doi = None
    articleids = raw.get("articleids")
    for item in articleids[:40] if isinstance(articleids, list) else []:
        if isinstance(item, dict) and item.get("idtype") == "doi":
            value = _text(item.get("value"), 2048)
            if value and _DOI.fullmatch(value):
                doi = value.lower()
                break
    try:
        return PubMedCandidate(
            pmid=pmid,
            title=title,
            authors=authors,
            venue=_text(raw.get("source"), 500),
            publication_date=_text(raw.get("pubdate"), 40),
            doi=doi,
            landing_page_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        )
    except ValidationError:
        return None


class PubMedAdapter:
    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 20) -> None:
        if not 0 < timeout <= 60:
            raise ValueError("PubMed timeout must be between zero and 60 seconds")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
        self._timeout = httpx.Timeout(timeout, connect=min(10, timeout))

    @staticmethod
    def search_request(*, query: str, per_page: int = 8) -> ProviderRequest:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ValueError("PubMed query must contain 1 to 1000 characters")
        if type(per_page) is not int or not 1 <= per_page <= 10:
            raise ValueError("PubMed per_page must be between one and ten")
        payload = {"term": query.strip(), "retmax": per_page}
        return ProviderRequest(
            "search",
            payload,
            request_fingerprint("pubmed:esearch:v1", payload),
            request_schema_version=PUBMED_SCHEMA_VERSION,
        )

    async def _get_json(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        try:
            response = await self._client.get(
                f"{PUBMED_API}/{path}",
                params=params,
                timeout=self._timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise PubMedRequestError("PubMed response exceeds metadata limit")
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PubMedRequestError("PubMed request failed or returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise PubMedRequestError("PubMed response is invalid")
        return body

    async def search(self, request: ProviderRequest) -> PubMedSearchResult:
        payload = request.payload
        try:
            expected = self.search_request(query=payload["term"], per_page=payload["retmax"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid PubMed search request") from exc
        if request != expected:
            raise ValueError("Invalid PubMed search request")
        search = await self._get_json(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": payload["term"],
                "retmax": payload["retmax"],
                "retmode": "json",
            },
        )
        result = search.get("esearchresult")
        if not isinstance(result, dict) or not isinstance(result.get("idlist"), list):
            raise PubMedRequestError("PubMed ESearch response is invalid")
        ids = result["idlist"]
        if len(ids) > payload["retmax"] or any(
            not isinstance(i, str) or not _PMID.fullmatch(i) for i in ids
        ):
            raise PubMedRequestError("PubMed ESearch identifiers are invalid")
        count = result.get("count")
        total = (
            int(count) if isinstance(count, str) and count.isascii() and count.isdecimal() else None
        )
        if not ids:
            return PubMedSearchResult((), total, 1)
        summary = await self._get_json(
            "esummary.fcgi",
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        )
        records = summary.get("result")
        if not isinstance(records, dict) or not isinstance(records.get("uids"), list):
            raise PubMedRequestError("PubMed ESummary response is invalid")
        if any(uid not in ids for uid in records["uids"]):
            raise PubMedRequestError("PubMed ESummary identifiers are invalid")
        candidates = tuple(
            candidate
            for uid in ids
            if uid in records
            if (candidate := _candidate(uid, records[uid])) is not None
        )
        return PubMedSearchResult(candidates, total, 2)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
