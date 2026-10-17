from datetime import date

import pytest

from research_api.providers.candidate_screening import (
    ACADEMIC_SCREEN_POLICY,
    screen_openalex_candidates,
)
from research_api.providers.openalex import OpenAlexCandidate


def candidate(work_id, title, abstract, doi=None, landing="https://papers.example/paper"):
    return OpenAlexCandidate(
        work_id=work_id,
        doi=doi,
        title=title,
        authors=(),
        publication_year=2024,
        publication_date=date(2024, 1, 1),
        abstract=abstract,
        open_access=True,
        landing_page_url=landing,
        pdf_url=None,
    )


def test_screening_persists_ranked_identity_and_exclusion_receipts():
    candidates = [
        candidate("W1", "Distributed ledger throughput", "Kafka throughput results."),
        candidate("W2", "Unrelated audit procedures", "Financial audit workflow."),
        candidate("W3", "Duplicate version", "Kafka throughput results.", doi="10.1234/work"),
        candidate("W4", "Same paper", "Kafka throughput results.", doi="10.1234/work"),
        candidate("W5", "Paper without a readable location", "Kafka throughput.", landing=None),
    ]

    response = screen_openalex_candidates(candidates, query="Kafka throughput", max_results=1)

    assert response.shortlist_policy == ACADEMIC_SCREEN_POLICY
    assert len(response.results) == 1
    assert response.results[0].url == "https://papers.example/paper"
    assert response.results[0].content == ""
    assert len(response.discovery_candidates) == 5
    assert response.usage["candidate_records_returned"] == 5
    assert "index_total_count" in response.usage
    reasons = {row["work_id"]: row.get("exclusion_reason") for row in response.discovery_candidates}
    assert reasons["W2"] == "no_relevance_overlap"
    assert reasons["W4"] == "duplicate_work_identity"
    assert reasons["W5"] == "no_extractable_location"
    assert reasons["W2"] == "no_relevance_overlap"
    assert response.discovery_candidates[0]["relevance"]["basis"] == "lexical_overlap_v1"
    assert "abstract" not in response.discovery_candidates[0]


def test_screening_tie_breaks_by_provider_order():
    response = screen_openalex_candidates(
        [
            candidate(
                "W20", "Graph research", "Graph systems.", landing="https://papers.example/20"
            ),
            candidate(
                "W10", "Graph research", "Graph systems.", landing="https://papers.example/10"
            ),
        ],
        query="graph research",
        max_results=1,
    )

    assert [item.url for item in response.results] == ["https://papers.example/20"]
    assert response.discovery_candidates[0]["work_id"] == "W20"
    assert response.discovery_candidates[0]["decision"] == "selected"
    assert response.discovery_candidates[1]["exclusion_reason"] == "outside_source_allocation"


def test_duplicate_provider_work_id_does_not_mark_selected_occurrence_excluded():
    response = screen_openalex_candidates(
        [
            candidate("W20", "Graph research", "Graph systems."),
            candidate("W20", "Graph research revised metadata", "Graph systems."),
        ],
        query="graph research",
        max_results=1,
    )

    decisions = response.discovery_candidates
    assert decisions[0]["decision"] == "selected"
    assert decisions[0]["selection_rank"] == 1
    assert decisions[1]["exclusion_reason"] == "duplicate_work_identity"


def test_distinct_works_with_same_extract_url_are_counted_once():
    response = screen_openalex_candidates(
        [
            candidate(
                "W1",
                "Graph research",
                "Graph systems.",
                doi="10.1234/one",
                landing="https://papers.example/shared",
            ),
            candidate(
                "W2",
                "Graph research",
                "Graph systems.",
                doi="10.1234/two",
                landing="https://papers.example/shared",
            ),
        ],
        query="graph research",
        max_results=2,
    )

    assert len(response.results) == 1
    assert response.discovery_candidates[1]["exclusion_reason"] == "duplicate_extract_url"


def test_screening_rejects_unbounded_or_invalid_selection_limits():
    with pytest.raises(ValueError):
        screen_openalex_candidates([], query="", max_results=1)
    with pytest.raises(ValueError):
        screen_openalex_candidates([], query="valid query", max_results=0)
