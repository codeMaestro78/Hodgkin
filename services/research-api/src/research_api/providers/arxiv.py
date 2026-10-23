"""Bounded arXiv Atom discovery; article summaries are intentionally discarded."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_api.providers.tavily import ProviderRequest, request_fingerprint

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_SCHEMA_VERSION = "arxiv-atom-v1"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
_ID = re.compile(
    r"(?:[0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})(?:v[1-9][0-9]*)?\Z", re.I
)
_DOI = re.compile(r"10\.[0-9]{4,9}/\S+\Z", re.I)


class ArxivRequestError(RuntimeError):
    """The official API failed or returned a malformed discovery feed."""


class ArxivCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arxiv_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=1000)
    authors: tuple[str, ...] = Field(max_length=20)
    published: datetime | None = None
    doi: str | None = Field(default=None, max_length=2048)
    landing_page_url: str = Field(max_length=200)


@dataclass(frozen=True, slots=True)
class ArxivSearchResult:
    candidates: tuple[ArxivCandidate, ...]
    total_count: int | None
    attempt_count: int = 1
    response_schema_version: str = ARXIV_SCHEMA_VERSION


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return " ".join(value.split())[:limit] or None


def _candidate(entry: ET.Element) -> ArxivCandidate | None:
    raw_id = entry.findtext(f"{_ATOM}id")
    if not raw_id or not raw_id.startswith(("http://arxiv.org/abs/", "https://arxiv.org/abs/")):
        return None
    arxiv_id = raw_id.split("/abs/", 1)[1]
    if _ID.fullmatch(arxiv_id) is None:
        return None
    title = _text(entry.findtext(f"{_ATOM}title"), 1000)
    if title is None:
        return None
    authors = tuple(
        name
        for author in entry.findall(f"{_ATOM}author")[:20]
        if (name := _text(author.findtext(f"{_ATOM}name"), 300)) is not None
    )
    raw_published = entry.findtext(f"{_ATOM}published")
    try:
        published = (
            datetime.fromisoformat(raw_published.replace("Z", "+00:00")) if raw_published else None
        )
    except ValueError:
        published = None
    raw_doi = _text(entry.findtext(f"{_ARXIV}doi"), 2048)
    doi = raw_doi.lower() if raw_doi and _DOI.fullmatch(raw_doi) else None
    try:
        return ArxivCandidate(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            published=published,
            doi=doi,
            landing_page_url=f"https://arxiv.org/abs/{arxiv_id}",
        )
    except ValidationError:
        return None


class ArxivAdapter:
    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 20) -> None:
        if not 0 < timeout <= 60:
            raise ValueError("arXiv timeout must be between zero and 60 seconds")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
        self._timeout = httpx.Timeout(timeout, connect=min(10, timeout))

    @staticmethod
    def search_request(*, query: str, per_page: int = 8) -> ProviderRequest:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ValueError("arXiv query must contain 1 to 1000 characters")
        if type(per_page) is not int or not 1 <= per_page <= 10:
            raise ValueError("arXiv per_page must be between one and ten")
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not terms or len(terms) > 32:
            raise ValueError("arXiv query must contain 1 to 32 searchable terms")
        payload = {
            "search_query": " AND ".join(f"all:{term}" for term in terms),
            "start": 0,
            "max_results": per_page,
        }
        return ProviderRequest(
            "search",
            payload,
            request_fingerprint("arxiv:query:v1", payload),
            request_schema_version=ARXIV_SCHEMA_VERSION,
        )

    async def search(self, request: ProviderRequest) -> ArxivSearchResult:
        payload = request.payload
        # Only this grammar can reach the API; callers cannot inject paging or extra parameters.
        try:
            expression = payload["search_query"]
            terms = expression.split(" AND ")
            if not terms or any(
                not re.fullmatch(r"all:[^\W_]+", term, re.UNICODE) for term in terms
            ):
                raise ValueError("Invalid arXiv expression")
            expected = self.search_request(
                query=" ".join(term[4:] for term in terms), per_page=payload["max_results"]
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Invalid arXiv search request") from exc
        if request != expected:
            raise ValueError("Invalid arXiv search request")
        try:
            response = await self._client.get(
                ARXIV_API, params=payload, timeout=self._timeout, follow_redirects=False
            )
            response.raise_for_status()
            content = response.content
            if len(content) > 1_000_000:
                raise ArxivRequestError("arXiv response exceeds metadata limit")
            if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                raise ArxivRequestError("arXiv response contains unsupported XML declarations")
            # The size cap and declaration rejection above bound ElementTree input.
            root = ET.fromstring(content)  # noqa: S314
        except httpx.HTTPError as exc:
            raise ArxivRequestError("arXiv request failed") from exc
        except ET.ParseError as exc:
            raise ArxivRequestError("arXiv response is invalid XML") from exc
        if root.tag != f"{_ATOM}feed":
            raise ArxivRequestError("arXiv response is not an Atom feed")
        raw_count = root.findtext(f"{_OPENSEARCH}totalResults")
        total = (
            int(raw_count) if raw_count and raw_count.isascii() and raw_count.isdecimal() else None
        )
        candidates = tuple(
            candidate
            for entry in root.findall(f"{_ATOM}entry")[: payload["max_results"]]
            if (candidate := _candidate(entry)) is not None
        )
        return ArxivSearchResult(candidates, total)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
