"""Deterministic, auditable candidate ranking before paid extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from research_api.artifacts.normalization import canonicalize_url
from research_api.providers.openalex import OpenAlexCandidate
from research_api.providers.tavily import SearchResponse, SearchResult

ACADEMIC_SCREEN_POLICY = "academic-lexical-topk-v1"
_TOKEN = re.compile(r"[\w-]+", re.UNICODE)
_STOPWORDS = frozenset(
    "a an and are as at be by for from how in is it of on or that the this to vs what"
    " when where which who why with".split()
)


@dataclass(frozen=True, slots=True)
class _RankedCandidate:
    candidate: OpenAlexCandidate
    provider_rank: int
    identity: str
    score: float
    title_overlap: float
    abstract_overlap: float


def _terms(text: str) -> set[str]:
    values = {match.group(0).casefold() for match in _TOKEN.finditer(text)}
    useful = {term for term in values if len(term) > 1 and term not in _STOPWORDS}
    return useful or values


def _overlap(query_terms: set[str], text: str | None) -> float:
    if not text:
        return 0.0
    return len(query_terms & _terms(text)) / len(query_terms)


def _identity(candidate: OpenAlexCandidate) -> str:
    return f"doi:{candidate.doi}" if candidate.doi else f"openalex:{candidate.work_id}"


def _metadata(candidate: OpenAlexCandidate) -> dict[str, Any]:
    return {
        "provider": "openalex",
        "work_id": candidate.work_id,
        "doi": candidate.doi,
        "title": candidate.title,
        "authors": list(candidate.authors),
        "publication_year": candidate.publication_year,
        "publication_date": candidate.publication_date.isoformat()
        if isinstance(candidate.publication_date, date)
        else None,
        "work_type": candidate.work_type,
        "venue": candidate.venue,
        "citation_count": candidate.citation_count,
        "open_access": candidate.open_access,
        "landing_page_url": candidate.landing_page_url,
        "pdf_url": candidate.pdf_url,
    }


def screen_openalex_candidates(
    candidates: tuple[OpenAlexCandidate, ...] | list[OpenAlexCandidate],
    *,
    query: str,
    max_results: int,
    reported_cost_usd: float | None = None,
    index_total_count: int | None = None,
) -> SearchResponse:
    """Rank by query-term coverage and persist bounded decisions without abstracts.

    Scores are ordering features, not probabilities or evidence-quality judgments.
    Ties retain provider rank, then OpenAlex work ID. Only selected URLs are passed
    to extraction; all candidates and bounded exclusion reasons remain in the
    private provider-call receipt for deterministic replay and evaluation.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("candidate screening requires a non-empty dimension query")
    if type(max_results) is not int or not 1 <= max_results <= 10:
        raise ValueError("candidate screening limit must be between one and ten")
    query_terms = _terms(query.strip())
    if not query_terms:
        raise ValueError("candidate screening query has no searchable terms")

    ranked = []
    for index, candidate in enumerate(candidates, start=1):
        title_overlap = _overlap(query_terms, candidate.title)
        abstract_overlap = _overlap(query_terms, candidate.abstract)
        score = round(0.7 * title_overlap + 0.3 * abstract_overlap, 6)
        ranked.append(
            _RankedCandidate(
                candidate=candidate,
                provider_rank=index,
                identity=_identity(candidate),
                score=score,
                title_overlap=round(title_overlap, 6),
                abstract_overlap=round(abstract_overlap, 6),
            )
        )

    ordered = sorted(
        ranked, key=lambda item: (-item.score, item.provider_rank, item.candidate.work_id)
    )
    seen: set[str] = set()
    unique: list[_RankedCandidate] = []
    duplicate_ranks: set[int] = set()
    duplicate_url_ranks: set[int] = set()
    for item in ordered:
        if item.score <= 0:
            continue
        if item.identity in seen:
            duplicate_ranks.add(item.provider_rank)
            continue
        seen.add(item.identity)
        unique.append(item)

    with_location = [
        item for item in unique if item.candidate.landing_page_url or item.candidate.pdf_url
    ]
    unique_urls: list[_RankedCandidate] = []
    seen_urls: set[str] = set()
    for item in with_location:
        url = canonicalize_url(item.candidate.landing_page_url or item.candidate.pdf_url or "")
        if url in seen_urls:
            duplicate_url_ranks.add(item.provider_rank)
            continue
        seen_urls.add(url)
        unique_urls.append(item)
    selected = unique_urls[:max_results]
    selected_ranks = {item.provider_rank: rank for rank, item in enumerate(selected, start=1)}
    receipt = []
    for item in sorted(ranked, key=lambda value: value.provider_rank):
        candidate = item.candidate
        row = {
            **_metadata(candidate),
            "candidate_rank": item.provider_rank,
            "identity": item.identity,
            "relevance": {
                "policy": ACADEMIC_SCREEN_POLICY,
                "basis": "lexical_overlap_v1",
                "score": item.score,
                "title_term_coverage": item.title_overlap,
                "abstract_term_coverage": item.abstract_overlap,
                "query_term_count": len(query_terms),
            },
        }
        if item.score <= 0:
            row.update(decision="excluded", exclusion_reason="no_relevance_overlap")
        elif item.provider_rank in duplicate_ranks:
            row.update(decision="excluded", exclusion_reason="duplicate_work_identity")
        elif not (candidate.landing_page_url or candidate.pdf_url):
            row.update(decision="excluded", exclusion_reason="no_extractable_location")
        elif item.provider_rank in duplicate_url_ranks:
            row.update(decision="excluded", exclusion_reason="duplicate_extract_url")
        elif item.provider_rank not in selected_ranks:
            row.update(decision="excluded", exclusion_reason="outside_source_allocation")
        else:
            row.update(decision="selected", selection_rank=selected_ranks[item.provider_rank])
        receipt.append(row)

    results = [
        SearchResult(
            url=item.candidate.landing_page_url or item.candidate.pdf_url or "",
            title=item.candidate.title,
            content="",
            score=item.score,
            published_date=item.candidate.publication_date.isoformat()
            if item.candidate.publication_date
            else None,
            provider="openalex",
            source_class="academic",
        )
        for item in selected
    ]
    return SearchResponse(
        results=results,
        usage={
            "reported_cost_usd": reported_cost_usd,
            "candidate_records_returned": len(ranked),
            "index_total_count": index_total_count,
            "unique_work_candidates": len(unique),
            "selected_for_extraction": len(selected),
            "excluded": len(ranked) - len(selected),
            "screening_policy": ACADEMIC_SCREEN_POLICY,
        },
        discovery_candidates=receipt,
        shortlist_policy=ACADEMIC_SCREEN_POLICY,
        discovery_provider="openalex",
        source_class="academic",
    )
