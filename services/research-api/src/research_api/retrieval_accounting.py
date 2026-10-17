"""Build a conservative, tenant-authorized retrieval activity projection."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

_PUBLIC_PROVIDERS = frozenset({"openalex", "serper", "tavily", "parallel", "browser"})
_COUNT_FIELDS = ("discovered", "shortlisted", "excluded", "duplicateWork", "unavailable")
_EXTRACTION_OUTCOMES = ("succeeded", "failed", "uncertain", "pending")
_SEMANTIC_OUTCOMES = ("supports", "partially_supports", "contradicts", "unrelated")


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _provider_usage(call: Mapping[str, object]) -> Mapping[str, object]:
    value = call.get("provider_usage")
    return value if isinstance(value, Mapping) else {}


def _retrieval_summary(usage: Mapping[str, object]) -> Mapping[str, object]:
    value = usage.get("retrieval")
    return value if isinstance(value, Mapping) else {}


def search_provider_usage(*, provider: str, response: Mapping[str, object]) -> dict[str, object]:
    """Persist small count-only discovery receipts beside provider usage."""
    raw_usage = response.get("usage")
    usage = dict(raw_usage) if isinstance(raw_usage, Mapping) else {}
    raw_results = response.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    raw_candidates = response.get("discovery_candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else None

    if provider == "openalex":
        discovered = _count(usage.get("candidate_records_returned"))
        shortlisted = _count(usage.get("selected_for_extraction"))
        excluded = _count(usage.get("excluded"))
        duplicate_work = (
            sum(
                1
                for item in candidates
                if isinstance(item, Mapping)
                and item.get("exclusion_reason") == "duplicate_work_identity"
            )
            if candidates is not None
            else None
        )
        unavailable = (
            sum(
                1
                for item in candidates
                if isinstance(item, Mapping)
                and item.get("exclusion_reason") == "no_extractable_location"
            )
            if candidates is not None
            else None
        )
    elif candidates is not None:
        discovered = len(candidates)
        shortlisted = len(results)
        excluded = max(0, discovered - shortlisted)
        duplicate_work = None
        unavailable = None
    else:
        # Providers that return only their bounded shortlist do not expose the
        # size or exclusions of their upstream candidate pool.
        discovered = len(results)
        shortlisted = len(results)
        excluded = None
        duplicate_work = None
        unavailable = None

    policy = response.get("shortlist_policy") or usage.get("screening_policy")
    usage["retrieval"] = {
        "discovered": discovered,
        "shortlisted": shortlisted,
        "excluded": excluded,
        "duplicateWork": duplicate_work,
        "unavailable": unavailable,
        "policy": policy if isinstance(policy, str) and len(policy) <= 100 else None,
    }
    return usage


def build_retrieval_accounting(
    *,
    calls: Sequence[Mapping[str, object]],
    sources: Sequence[Mapping[str, object]],
    claim_checks: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Summarize persisted provider/source/claim records without inferring quality.

    Candidate counts are shown only when the corresponding successful provider
    call persisted them. Missing legacy/provider counts stay null. Relevance and
    independence require adjudication or stronger source evidence and are never
    inferred from lexical scores, citations, URLs, or publisher names here.
    """
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    extraction_outcomes = {outcome: 0 for outcome in _EXTRACTION_OUTCOMES}
    extraction_outcomes["other"] = 0
    for call in calls:
        provider = call.get("provider")
        operation = call.get("operation")
        outcome = call.get("outcome")
        if provider not in _PUBLIC_PROVIDERS:
            continue
        if operation == "extract":
            outcome = call.get("outcome")
            outcome_key = outcome if outcome in _EXTRACTION_OUTCOMES else "other"
            extraction_outcomes[str(outcome_key)] += 1
        if operation == "search" and outcome == "succeeded":
            grouped[str(provider)].append(call)

    source_provider: dict[str, str] = {}
    for source in sources:
        source_id, provider = source.get("id"), source.get("provider")
        if isinstance(source_id, str) and provider in _PUBLIC_PROVIDERS:
            source_provider[source_id] = str(provider)
    extracted_by_provider: dict[str, set[str]] = defaultdict(set)
    for source_id, provider in source_provider.items():
        extracted_by_provider[provider].add(source_id)

    cited_by_provider: dict[str, set[str]] = defaultdict(set)
    verified_cited_sources: set[str] = set()
    semantic_outcomes = {outcome: 0 for outcome in _SEMANTIC_OUTCOMES}
    semantic_outcomes["notRecorded"] = 0
    citation_checks = exact_span_verified = published_claims = 0
    for claim in claim_checks:
        published_claims += claim.get("publishedInReport") is True
        citations = claim.get("citations")
        if isinstance(citations, list):
            for citation in citations:
                if not isinstance(citation, Mapping):
                    continue
                citation_checks += 1
                exact_span_verified += citation.get("exactSpanVerified") is True
                verdict = citation.get("verdict")
                outcome_key = verdict if verdict in _SEMANTIC_OUTCOMES else "notRecorded"
                semantic_outcomes[str(outcome_key)] += 1
        if claim.get("publishedInReport") is not True:
            continue
        if not isinstance(citations, list):
            continue
        for citation in citations:
            if not isinstance(citation, Mapping):
                continue
            source_id = citation.get("sourceId")
            if (
                isinstance(source_id, str)
                and citation.get("exactSpanVerified") is True
                and citation.get("verdict") == "supports"
            ):
                verified_cited_sources.add(source_id)
                provider = source_provider.get(source_id)
                if provider is not None:
                    cited_by_provider[provider].add(source_id)

    providers: list[dict[str, object]] = []
    for provider in sorted(set(grouped) | set(extracted_by_provider)):
        provider_calls = grouped.get(provider, [])
        rows: dict[str, list[int]] = {name: [] for name in _COUNT_FIELDS}
        policies: set[str] = set()
        complete = True
        for call in provider_calls:
            summary = _retrieval_summary(_provider_usage(call))
            for field in _COUNT_FIELDS:
                value = _count(summary.get(field))
                if value is None:
                    complete = False
                else:
                    rows[field].append(value)
            policy = summary.get("policy")
            if isinstance(policy, str) and policy and len(policy) <= 100:
                policies.add(policy)
        providers.append(
            {
                "provider": provider,
                "searchCalls": len(provider_calls),
                **{
                    field: sum(values)
                    if provider_calls and len(values) == len(provider_calls)
                    else None
                    for field, values in rows.items()
                },
                "policyVersions": sorted(policies),
                "countsComplete": bool(provider_calls) and complete,
                "extractedSources": len(extracted_by_provider.get(provider, set())),
                "citedInVerifiedFinding": len(cited_by_provider.get(provider, set())),
            }
        )

    return {
        "schemaVersion": "1.1",
        "providers": providers,
        "extractionCalls": sum(extraction_outcomes.values()),
        "extractionOutcomes": extraction_outcomes,
        "extractedSources": len(
            {source_id for source in sources if isinstance((source_id := source.get("id")), str)}
        ),
        "citedInVerifiedFinding": len(verified_cited_sources),
        "citationChecks": citation_checks,
        "exactSpanVerifiedCitations": exact_span_verified,
        "semanticReviewOutcomes": semantic_outcomes,
        "publishedClaims": published_claims,
        "answerUsefulness": "not_assessed",
        "dimensionRelevance": "not_assessed",
        "sourceIndependence": "not_assessed",
    }
