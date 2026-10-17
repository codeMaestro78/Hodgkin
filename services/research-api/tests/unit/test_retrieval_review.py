import copy
import os

import pytest

from research_api.retrieval_review import (
    _write_json,
    prepare_blind_review,
    score_retrieval_pool,
)


def _pool():
    return {
        "schemaVersion": "retrieval-candidate-pool-v1",
        "cases": [
            {
                "caseId": "R01",
                "domain": "clinical",
                "candidates": [
                    {
                        "candidateId": "private-oa-1",
                        "title": "Direct randomized comparison",
                        "abstract": "Adults with the specified condition were randomized.",
                        "year": 2025,
                        "documentType": "article",
                        "url": "https://private.example/one",
                        "workIdentity": "doi:10.1000/shared-work",
                        "versionGroup": "version-1",
                    },
                    {
                        "candidateId": "private-web-2",
                        "title": "Adjacent observational cohort",
                        "abstract": "A related population was observed.",
                        "year": 2024,
                        "documentType": "preprint",
                        "url": "https://private.example/two",
                        "workIdentity": "doi:10.1000/other-work",
                        "versionGroup": "version-2",
                    },
                    {
                        "candidateId": "private-oa-3",
                        "title": "Published version of direct comparison",
                        "abstract": "The same randomized comparison was published.",
                        "year": 2026,
                        "documentType": "article",
                        "url": "https://private.example/three",
                        "workIdentity": "doi:10.1000/shared-work",
                        "versionGroup": "version-1",
                    },
                ],
                "rankings": {
                    "route_alpha": ["private-oa-1", "private-web-2", "private-oa-3"],
                    "route_beta": ["private-web-2", "private-oa-1", "private-oa-3"],
                },
            }
        ],
    }


def _reviewer(reviewer_id, labels, packet_hash):
    return {
        "reviewerId": reviewer_id,
        "packetSha256": packet_hash,
        "cases": [{"caseId": "R01", "labels": labels}],
    }


def _two_packets(pool, case):
    packet_a, mapping = prepare_blind_review(pool, {"R01": case}, seed=7)
    packet_b, _ = prepare_blind_review(pool, {"R01": case}, seed=31)
    return packet_a, packet_b, mapping


def _labels(mapping, *, second_relevance="partial"):
    case_mapping = mapping["cases"][0]
    candidate_ids = {row["candidateId"]: row["blindId"] for row in case_mapping["candidateMap"]}
    return [
        {
            "blindId": candidate_ids["private-oa-1"],
            "relevance": "direct",
            "reason": "The abstract directly studies the stated population and comparison.",
            "requirementMatches": {"population": "yes", "comparison": "yes"},
            "requirementReasons": {
                "population": "The abstract names the specified population.",
                "comparison": "The abstract compares both interventions.",
            },
            "confidence": "high",
        },
        {
            "blindId": candidate_ids["private-web-2"],
            "relevance": second_relevance,
            "reason": "The study is adjacent but does not establish the requested comparison.",
            "requirementMatches": {"population": "partial", "comparison": "no"},
            "requirementReasons": {
                "population": "The cohort is related but not the specified population.",
                "comparison": "The abstract does not compare both interventions.",
            },
            "confidence": "medium",
        },
        {
            "blindId": candidate_ids["private-oa-3"],
            "relevance": "direct",
            "reason": "This record reports the requested comparison.",
            "requirementMatches": {"population": "yes", "comparison": "yes"},
            "requirementReasons": {
                "population": "The abstract names the specified population.",
                "comparison": "The abstract compares both interventions.",
            },
            "confidence": "high",
        },
    ]


def test_blind_packet_hides_method_rank_urls_and_internal_candidate_identity():
    case = {
        "id": "R01",
        "domain": "clinical",
        "question": "Compare interventions for this population.",
        "requirements": [
            {"id": "population", "text": "Use the specified population."},
            {"id": "comparison", "text": "Compare both interventions."},
        ],
    }
    packet, private_map = prepare_blind_review(_pool(), {"R01": case}, seed=31)

    serialized_packet = str(packet)
    assert packet["cases"][0]["question"] == case["question"]
    assert len(packet["cases"][0]["candidates"]) == 3
    assert "route_alpha" not in serialized_packet
    assert "route_beta" not in serialized_packet
    assert "private-oa-1" not in serialized_packet
    assert "private.example" not in serialized_packet
    assert "workIdentity" not in serialized_packet
    assert "rank" not in serialized_packet
    assert private_map["cases"][0]["rankings"]["route_alpha"]
    assert prepare_blind_review(_pool(), {"R01": case}, seed=31) == (packet, private_map)
    second_packet, second_map = prepare_blind_review(_pool(), {"R01": case}, seed=83)
    assert [row["blindId"] for row in packet["cases"][0]["candidates"]] != [
        row["blindId"] for row in second_packet["cases"][0]["candidates"]
    ]
    assert second_map["cases"][0]["candidateMap"] == private_map["cases"][0]["candidateMap"]


def test_same_pool_scoring_reports_precision_requirement_coverage_and_duplicate_versions():
    case = {
        "id": "R01",
        "domain": "clinical",
        "question": "Compare interventions for this population.",
        "requirements": [
            {"id": "population", "text": "Use the specified population."},
            {"id": "comparison", "text": "Compare both interventions."},
        ],
    }
    packet_a, packet_b, mapping = _two_packets(_pool(), case)
    labels = _labels(mapping)
    result = score_retrieval_pool(
        _pool(),
        [mapping],
        [
            _reviewer("reviewer-a", labels, packet_a["packetSha256"]),
            _reviewer("reviewer-b", labels, packet_b["packetSha256"]),
        ],
        [packet_a, packet_b],
        cutoff=2,
    )

    alpha = result["methods"]["route_alpha"]["cases"][0]
    beta = result["methods"]["route_beta"]["cases"][0]
    assert alpha["directPrecisionAtK"] == 0.5
    assert alpha["candidatePoolRecallAtK"] == 0.5
    assert alpha["requirementCoverageAtK"] == 1.0
    assert alpha["duplicateWorkRateAtK"] == 0.0
    assert beta["directPrecisionAtK"] == 0.5
    assert beta["candidatePoolRecallAtK"] == 0.5
    assert result["reviewAgreement"]["overallLabelAgreement"] == 1.0
    assert result["reviewAgreement"]["overallLabelsCompared"] == 3
    assert result["reviewAgreement"]["requirementLabelsCompared"] == 6
    assert result["scopeNote"] == "candidate-pool recall is not corpus recall"


def test_candidate_pool_mutation_is_rejected_before_scoring():
    case = {
        "id": "R01",
        "domain": "clinical",
        "question": "Compare interventions for this population.",
        "requirements": [{"id": "population", "text": "Use the specified population."}],
    }
    pool = _pool()
    packet_a, packet_b, mapping = _two_packets(pool, case)
    changed_pool = _pool()
    changed_pool["cases"][0]["candidates"][0]["title"] = "Changed after review packet freeze"
    with pytest.raises(ValueError, match="does not match frozen candidate pool"):
        score_retrieval_pool(
            changed_pool,
            [mapping],
            [
                {"reviewerId": "reviewer-a", "cases": [{"caseId": "R01"}]},
                {"reviewerId": "reviewer-b", "cases": [{"caseId": "R01"}]},
            ],
            [packet_a, packet_b],
            cutoff=2,
        )


def test_disagreement_requires_explicit_third_party_adjudication():
    case = {
        "id": "R01",
        "domain": "clinical",
        "question": "Compare interventions for this population.",
        "requirements": [
            {"id": "population", "text": "Use the specified population."},
            {"id": "comparison", "text": "Compare both interventions."},
        ],
    }
    packet_a, packet_b, mapping = _two_packets(_pool(), case)
    with pytest.raises(ValueError, match="requires adjudication"):
        score_retrieval_pool(
            _pool(),
            [mapping],
            [
                _reviewer("reviewer-a", _labels(mapping), packet_a["packetSha256"]),
                _reviewer(
                    "reviewer-b",
                    _labels(mapping, second_relevance="not_relevant"),
                    packet_b["packetSha256"],
                ),
            ],
            [packet_a, packet_b],
            cutoff=2,
        )


def test_disputed_labels_are_scored_only_after_independent_adjudication():
    case = {
        "id": "R01",
        "domain": "clinical",
        "question": "Compare interventions for this population.",
        "requirements": [
            {"id": "population", "text": "Use the specified population."},
            {"id": "comparison", "text": "Compare both interventions."},
        ],
    }
    pool = _pool()
    packet_a, packet_b, mapping = _two_packets(pool, case)
    left_labels = _labels(mapping)
    right_labels = copy.deepcopy(left_labels)
    blind_by_id = {
        row["candidateId"]: row["blindId"] for row in mapping["cases"][0]["candidateMap"]
    }
    disputed = next(row for row in right_labels if row["blindId"] == blind_by_id["private-web-2"])
    disputed["relevance"] = "not_relevant"
    adju_label = copy.deepcopy(disputed)
    adju_label["relevance"] = "partial"
    adju_label["reason"] = "Adjudicator confirms it is adjacent but not directly on target."
    result = score_retrieval_pool(
        pool,
        [mapping],
        [
            _reviewer("reviewer-a", left_labels, packet_a["packetSha256"]),
            _reviewer("reviewer-b", right_labels, packet_b["packetSha256"]),
        ],
        [packet_a, packet_b],
        cutoff=2,
        adjudication={
            "adjudicatorId": "reviewer-c",
            "cases": [{"caseId": "R01", "labels": [adju_label]}],
        },
    )
    assert result["reviewAgreement"]["disputedCandidatesAdjudicated"] == 1


def test_evaluation_artifacts_are_private_and_never_overwritten(tmp_path):
    artifact = tmp_path / "review.json"
    _write_json(artifact, {"review": "fixture"}, private=True)
    assert os.stat(artifact).st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        _write_json(artifact, {"review": "replacement"}, private=True)
