from research_api.retrieval_accounting import (
    build_retrieval_accounting,
    search_provider_usage,
)
from research_api.schemas.generated.run_insights import RetrievalAccounting, RunInsights


def test_retrieval_accounting_keeps_unmeasured_relevance_and_independence_explicit():
    result = build_retrieval_accounting(
        calls=[
            {
                "provider": "openalex",
                "operation": "search",
                "outcome": "succeeded",
                "provider_usage": {
                    "retrieval": {
                        "discovered": 6,
                        "shortlisted": 2,
                        "excluded": 4,
                        "duplicateWork": 1,
                        "unavailable": 1,
                        "policy": "academic-lexical-topk-v1",
                    }
                },
            },
            {
                "provider": "tavily",
                "operation": "search",
                "outcome": "succeeded",
                "provider_usage": None,
            },
            {"provider": "tavily", "operation": "extract", "outcome": "succeeded"},
            {"provider": "openalex", "operation": "extract", "outcome": "failed"},
        ],
        sources=[
            {"id": "source-1", "provider": "openalex"},
            {"id": "source-2", "provider": "tavily"},
        ],
        claim_checks=[
            {
                "publishedInReport": True,
                "citations": [
                    {
                        "sourceId": "source-1",
                        "exactSpanVerified": True,
                        "verdict": "supports",
                    },
                    {
                        "sourceId": "source-2",
                        "exactSpanVerified": False,
                        "verdict": "not_recorded",
                    },
                ],
            }
        ],
    )

    assert result == {
        "schemaVersion": "1.2",
        "exactDuplicateSources": 0,
        "sourceClasses": {},
        "providers": [
            {
                "provider": "openalex",
                "searchCalls": 1,
                "discovered": 6,
                "shortlisted": 2,
                "excluded": 4,
                "duplicateWork": 1,
                "duplicateUrl": None,
                "unavailable": 1,
                "policyVersions": ["academic-lexical-topk-v1"],
                "countsComplete": False,
                "extractedSources": 1,
                "citedInVerifiedFinding": 1,
            },
            {
                "provider": "tavily",
                "searchCalls": 1,
                "discovered": None,
                "shortlisted": None,
                "excluded": None,
                "duplicateWork": None,
                "duplicateUrl": None,
                "unavailable": None,
                "policyVersions": [],
                "countsComplete": False,
                "extractedSources": 1,
                "citedInVerifiedFinding": 0,
            },
        ],
        "extractionCalls": 2,
        "extractionOutcomes": {
            "succeeded": 1,
            "failed": 1,
            "uncertain": 0,
            "pending": 0,
            "other": 0,
        },
        "extractedSources": 2,
        "citedInVerifiedFinding": 1,
        "citationChecks": 2,
        "exactSpanVerifiedCitations": 1,
        "semanticReviewOutcomes": {
            "supports": 1,
            "partially_supports": 0,
            "contradicts": 0,
            "unrelated": 0,
            "notRecorded": 1,
        },
        "publishedClaims": 1,
        "answerUsefulness": "not_assessed",
        "dimensionRelevance": "not_assessed",
        "sourceIndependence": "not_assessed",
    }
    assert RetrievalAccounting.model_validate(result).model_dump(by_alias=True) == result


def test_retrieval_accounting_does_not_count_failed_discovery_or_unverified_citations():
    result = build_retrieval_accounting(
        calls=[
            {
                "provider": "openalex",
                "operation": "search",
                "outcome": "failed",
                "provider_usage": {"retrieval": {"discovered": 4, "shortlisted": 2, "excluded": 2}},
            }
        ],
        sources=[{"id": "source-1", "provider": "openalex"}],
        claim_checks=[
            {
                "publishedInReport": True,
                "citations": [
                    {
                        "sourceId": "source-1",
                        "exactSpanVerified": False,
                        "verdict": "supports",
                    }
                ],
            }
        ],
    )

    assert result["providers"] == [
        {
            "provider": "openalex",
            "searchCalls": 0,
            "discovered": None,
            "shortlisted": None,
            "excluded": None,
            "duplicateWork": None,
            "duplicateUrl": None,
            "unavailable": None,
            "policyVersions": [],
            "countsComplete": False,
            "extractedSources": 1,
            "citedInVerifiedFinding": 0,
        }
    ]
    assert result["extractionCalls"] == 0
    assert result["extractionOutcomes"]["failed"] == 0
    assert result["extractedSources"] == 1
    assert result["citedInVerifiedFinding"] == 0
    assert result["exactSpanVerifiedCitations"] == 0
    assert result["answerUsefulness"] == "not_assessed"


def test_extraction_and_semantic_outcomes_keep_uncertainty_and_partial_support_visible():
    result = build_retrieval_accounting(
        calls=[
            {"provider": "tavily", "operation": "extract", "outcome": "uncertain"},
            {"provider": "tavily", "operation": "extract", "outcome": "pending"},
            {"provider": "tavily", "operation": "extract", "outcome": "cancelled"},
        ],
        sources=[],
        claim_checks=[
            {
                "publishedInReport": True,
                "citations": [
                    {
                        "exactSpanVerified": True,
                        "verdict": "partially_supports",
                    },
                    {
                        "exactSpanVerified": True,
                        "verdict": "contradicts",
                    },
                ],
            }
        ],
    )
    assert result["extractionCalls"] == 3
    assert result["extractionOutcomes"] == {
        "succeeded": 0,
        "failed": 0,
        "uncertain": 1,
        "pending": 1,
        "other": 1,
    }
    assert result["semanticReviewOutcomes"]["partially_supports"] == 1
    assert result["semanticReviewOutcomes"]["contradicts"] == 1
    assert result["exactSpanVerifiedCitations"] == 2


def test_provider_source_counts_follow_persisted_sources_and_verified_citations():
    result = build_retrieval_accounting(
        calls=[],
        sources=[
            {"id": "a", "provider": "openalex"},
            {"id": "b", "provider": "openalex"},
            {"id": "c", "provider": "tavily"},
        ],
        claim_checks=[
            {
                "publishedInReport": True,
                "citations": [
                    {"sourceId": "a", "exactSpanVerified": True, "verdict": "supports"},
                    {"sourceId": "a", "exactSpanVerified": True, "verdict": "supports"},
                    {"sourceId": "c", "exactSpanVerified": False, "verdict": "supports"},
                ],
            }
        ],
    )

    assert result["providers"] == [
        {
            "provider": "openalex",
            "searchCalls": 0,
            "discovered": None,
            "shortlisted": None,
            "excluded": None,
            "duplicateWork": None,
            "duplicateUrl": None,
            "unavailable": None,
            "policyVersions": [],
            "countsComplete": False,
            "extractedSources": 2,
            "citedInVerifiedFinding": 1,
        },
        {
            "provider": "tavily",
            "searchCalls": 0,
            "discovered": None,
            "shortlisted": None,
            "excluded": None,
            "duplicateWork": None,
            "duplicateUrl": None,
            "unavailable": None,
            "policyVersions": [],
            "countsComplete": False,
            "extractedSources": 1,
            "citedInVerifiedFinding": 0,
        },
    ]
    assert result["citedInVerifiedFinding"] == 1


def test_search_provider_usage_persists_only_bounded_aggregate_candidate_counts():
    usage = search_provider_usage(
        provider="openalex",
        response={
            "results": [{"url": "https://papers.test/a"}],
            "usage": {
                "candidate_records_returned": 4,
                "selected_for_extraction": 1,
                "excluded": 3,
                "screening_policy": "academic-lexical-topk-v1",
            },
            "shortlist_policy": "academic-lexical-topk-v1",
            "discovery_candidates": [
                {"decision": "excluded", "exclusion_reason": "duplicate_work_identity"},
                {"decision": "excluded", "exclusion_reason": "no_extractable_location"},
                {"decision": "excluded", "exclusion_reason": "outside_source_allocation"},
                {"decision": "selected"},
            ],
        },
    )

    assert usage == {
        "candidate_records_returned": 4,
        "selected_for_extraction": 1,
        "excluded": 3,
        "screening_policy": "academic-lexical-topk-v1",
        "retrieval": {
            "discovered": 4,
            "shortlisted": 1,
            "excluded": 3,
            "duplicateWork": 1,
            "duplicateUrl": 0,
            "unavailable": 1,
            "policy": "academic-lexical-topk-v1",
        },
    }


def test_search_provider_usage_does_not_invent_screening_counts_for_tavily():
    usage = search_provider_usage(
        provider="tavily",
        response={"results": [{"url": "https://papers.test/a"}], "usage": None},
    )
    assert usage["retrieval"] == {
        "discovered": 1,
        "shortlisted": 1,
        "excluded": 0,
        "duplicateWork": None,
        "duplicateUrl": 0,
        "unavailable": None,
        "policy": None,
    }


def test_tavily_usage_counts_www_aliases_without_claiming_duplicate_works():
    usage = search_provider_usage(
        provider="tavily",
        response={
            "results": [
                {"url": "https://www.example.test/paper?utm_source=x"},
                {"url": "https://example.test/paper"},
                {"url": "https://example.test/other"},
            ],
        },
    )

    assert usage["retrieval"] == {
        "discovered": 3,
        "shortlisted": 2,
        "excluded": 1,
        "duplicateWork": None,
        "duplicateUrl": 1,
        "unavailable": None,
        "policy": None,
    }


def test_retrieval_accounting_counts_exact_content_duplicates_and_source_classes():
    result = build_retrieval_accounting(
        calls=[],
        sources=[
            {"id": "one", "provider": "tavily", "contentHash": "same", "sourceClass": "web"},
            {"id": "two", "provider": "tavily", "contentHash": "same", "sourceClass": "web"},
            {
                "id": "three",
                "provider": "openalex",
                "contentHash": "other",
                "sourceClass": "academic",
            },
        ],
        claim_checks=[],
    )

    assert result["schemaVersion"] == "1.2"
    assert result["exactDuplicateSources"] == 1
    assert result["sourceClasses"] == {"academic": 1, "web": 2}


def test_retrieval_accounting_is_valid_in_the_public_run_insights_contract():
    accounting = build_retrieval_accounting(calls=[], sources=[], claim_checks=[])
    result = RunInsights.model_validate(
        {
            "schemaVersion": "1.5",
            "tasks": [],
            "providerCalls": [],
            "gaps": [],
            "parentReportId": None,
            "parentRunId": None,
            "followupRuns": [],
            "reportVersions": [],
            "retrievalAccounting": accounting,
        }
    )

    assert result.retrieval_accounting is not None
    assert result.retrieval_accounting.dimension_relevance == "not_assessed"


def test_retrieval_accounting_v11_snapshots_remain_readable():
    accounting = build_retrieval_accounting(calls=[], sources=[], claim_checks=[])
    accounting["schemaVersion"] = "1.1"
    accounting.pop("exactDuplicateSources")
    accounting.pop("sourceClasses")

    parsed = RetrievalAccounting.model_validate(accounting)

    assert parsed.schema_version == "1.1"
    assert parsed.exact_duplicate_sources is None
    assert parsed.source_classes is None
