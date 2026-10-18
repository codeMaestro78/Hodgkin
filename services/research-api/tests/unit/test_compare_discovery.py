"""Synthetic measurements only; no external credentials or provider calls."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "compare_discovery",
    Path(__file__).parents[2] / "scripts/compare_discovery.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record(provider, **changes):
    return {
        "discoveryProvider": provider,
        "mode": "focused",
        "workloadFingerprint": "a" * 64,
        "status": "completed",
        "errorCode": None,
        "elapsedMs": 40000,
        "firstSourceFromCreationMs": 10000,
        "firstVerifiedFindingFromCreationMs": 20000,
        "sources": 5,
        "sourceUtility": {
            "sourcesExtracted": 5,
            "sourcesCitedInVerifiedFindings": 3,
            "independenceAssessed": False,
        },
        "assessmentCoverage": {
            "criteriaTotal": 4,
            "criteriaAssessed": 3,
            "criteriaMet": 2,
            "criteriaPartial": 1,
            "independentAssessment": True,
        },
        "citationQuality": {
            "verifiedCitations": 7,
            "exactSpanVerified": 7,
            "semanticSupport": 7,
            "unassessed": 0,
        },
        "providerOperations": 6,
        "quality": {"status": "partial", "verifiedFindings": 5},
        "coverage": {
            "requirementsTotal": 2,
            "requirementsAddressed": 1,
            "questionsTotal": 3,
            "questionsAddressed": 2,
        },
        "sourceDiversity": {
            "distinctHosts": 4,
            "distinctPublishers": 3,
            "independenceAssessed": False,
        },
        "modelCalls": [{"role": "writer", "outcome": "uncertain"}],
        "accountedEstimatedCostUsd": "0.050000",
        **changes,
    }


def test_compare_matching_pair_preserves_quality_limits():
    result = module.compare([record("tavily"), record("serper", elapsedMs=39000)])
    assert result["candidateMinusBaseline"]["totalMs"] == -1000
    assert result["candidate"]["qualityStatus"] == "partial"
    assert result["candidateMinusBaseline"]["questionsAddressed"] == 0
    assert result["candidateMinusBaseline"]["firstVerifiedFindingMs"] == 0
    assert result["candidateMinusBaseline"]["sourcesCitedInVerifiedFindings"] == 0
    assert "not completeness" in result["interpretation"]


def test_compare_shared_pool_pair_keeps_discovery_fixed_and_metrics_complete():
    result = module.compare(
        [
            record("tavily", httpClientMode="worker"),
            record("tavily", httpClientMode="shared", elapsedMs=39000),
        ]
    )
    assert result["comparisonDimension"] == "http_client_pooling"
    assert result["candidateMinusBaseline"]["totalMs"] == -1000
    assert result["candidate"]["citationQuality"]["verifiedCitations"] == 7


def test_compare_http_client_pair_rejects_discovery_route_mismatch():
    with pytest.raises(ValueError):
        module.compare(
            [
                record("tavily", httpClientMode="worker"),
                record("serper", httpClientMode="shared"),
            ]
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"workloadFingerprint": "b" * 64},
        {"elapsedMs": float("nan")},
        {"accountedEstimatedCostUsd": "NaN"},
        {"quality": None},
        {"coverage": None},
    ],
)
def test_compare_rejects_unmatched_or_invalid_results(changes):
    with pytest.raises(ValueError):
        module.compare([record("tavily"), record("serper", **changes)])


def test_compare_rejects_duplicate_route():
    with pytest.raises(ValueError):
        module.compare([record("tavily"), record("tavily")])


def test_missing_first_source_is_reported_as_unavailable_not_a_bad_pair():
    result = module.compare(
        [
            record("tavily", firstSourceFromCreationMs=None),
            record("serper", firstSourceFromCreationMs=None),
        ]
    )
    assert result["baseline"]["firstSourceMs"] is None
    assert result["candidateMinusBaseline"]["firstSourceMs"] is None


def test_coverage_delta_is_visible():
    result = module.compare(
        [
            record("tavily"),
            record(
                "serper",
                coverage={
                    "requirementsTotal": 2,
                    "requirementsAddressed": 2,
                    "questionsTotal": 3,
                    "questionsAddressed": 3,
                },
            ),
        ]
    )
    assert result["candidateMinusBaseline"]["requirementsAddressed"] == 1
    assert result["candidateMinusBaseline"]["questionsAddressed"] == 1


def test_first_verified_finding_and_criterion_assessment_deltas_are_visible():
    result = module.compare(
        [
            record("tavily"),
            record(
                "serper",
                firstVerifiedFindingFromCreationMs=15000,
                assessmentCoverage={
                    "criteriaTotal": 4,
                    "criteriaAssessed": 4,
                    "criteriaMet": 3,
                    "criteriaPartial": 1,
                    "independentAssessment": True,
                },
            ),
        ]
    )
    assert result["candidateMinusBaseline"]["firstVerifiedFindingMs"] == -5000
    assert result["candidateMinusBaseline"]["criteriaAssessed"] == 1


def test_failed_arm_keeps_partial_cost_latency_and_sources_without_quality_claim():
    result = module.compare(
        [
            record("tavily"),
            record(
                "serper",
                status="failed",
                errorCode="graph_execution_failed",
                quality=None,
                coverage=None,
                elapsedMs=42000,
                sources=4,
            ),
        ]
    )
    assert result["comparisonStatus"] == "partial_pair_with_failure"
    assert result["candidate"]["errorCode"] == "graph_execution_failed"
    assert result["candidate"]["sources"] == 4
    assert result["candidate"]["qualityStatus"] is None
    assert result["candidate"]["execution"]["modelCalls"] == [
        {"role": "writer", "outcome": "uncertain"}
    ]
    assert result["candidateMinusBaseline"]["verifiedFindings"] is None
    assert result["candidateMinusBaseline"]["requirementsAddressed"] is None
