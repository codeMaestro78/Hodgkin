"""V2 contract parity and pure construction: no infrastructure or providers."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from research_api.coverage import (
    CitationEvidence,
    ClaimEvidence,
    CoverageInput,
    CriterionAssessment,
    assess_coverage,
)
from research_api.mode_planning import attach_coverage_plan
from research_api.report_document import build_report_document, validate_report_document
from research_api.report_document_v2 import (
    enhance_report_document_v2,
    validate_report_document_v2,
)


def uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


@pytest.fixture
def v1() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[4]
        / "packages/contracts/fixtures/valid/report-document-v1.json"
    )
    return json.loads(path.read_text())


@pytest.fixture
def v2(v1: dict[str, Any]) -> dict[str, Any]:
    """Mirror packages/contracts/tests/report-v2.test.ts make() from shared V1."""
    claim = v1["findings"][0]["id"]
    return {
        **deepcopy(v1),
        "version": 2,
        "assessmentVersion": "coverage-ledger-v1",
        "runId": uid(400),
        "planId": uid(401),
        "assessmentId": uid(402),
        "modePolicyVersion": "research-mode-policy-v1",
        "dimensions": [
            {
                "id": uid(500),
                "label": "Costs",
                "requirementIds": ["question", "requirement-1"],
                "status": "verified_covered",
                "claimIds": [claim],
                "reason": "All planned criteria have reviewed evidence.",
                "basis": "criterion-review-v1",
                "criteria": [
                    {
                        "id": uid(600),
                        "outcome": "met",
                        "claimIds": [claim],
                        "basis": "criterion-review-v1",
                        "reason": "Reviewed cost evidence.",
                    }
                ],
            }
        ],
        "requirementOutcomes": [
            {
                "id": key,
                "outcome": "established",
                "dimensionIds": [uid(500)],
                "claimIds": [claim],
                "reason": "All mapped dimensions have reviewed evidence.",
            }
            for key in ("question", "requirement-1")
        ],
        "comparisons": [
            {
                "dimensionId": uid(500),
                "cells": [
                    {"alternative": "Approach A", "status": "supported", "claimIds": [claim]},
                    {"alternative": "Approach B", "status": "not_established", "claimIds": []},
                ],
            }
        ],
        "sourceIndependence": {
            "status": "unknown",
            "reason": "No independence assessment is established.",
        },
    }


def test_typescript_fixture_parity_and_dispatch_preserve_provenance(v1, v2):
    original = deepcopy(v2)
    assert validate_report_document_v2(v2) == original
    assert validate_report_document(v2) == original
    assert validate_report_document(v1) == v1
    assert v2 == original
    assert v2["requirements"] == v1["requirements"]
    assert v2["questionCoverage"] == v1["questionCoverage"]
    assert v2["requirements"][0]["status"] == "unresolved"
    assert v2["requirementOutcomes"][0]["outcome"] == "established"


def test_only_omitted_comparisons_default_to_empty(v2):
    del v2["comparisons"]
    assert validate_report_document_v2(v2)["comparisons"] == []
    v2["comparisons"] = None
    with pytest.raises(ValueError):
        validate_report_document_v2(v2)


@pytest.mark.parametrize("padding", [" ", " " * 300], ids=["spaces", "length-before-trim"])
def test_comparison_labels_are_trimmed_before_length_validation(v2, padding):
    v2["comparisons"][0]["cells"][0]["alternative"] = f"{padding}Approach A{padding}"
    parsed = validate_report_document_v2(v2)
    assert parsed["comparisons"][0]["cells"][0]["alternative"] == "Approach A"


def test_comparison_case_comparison_matches_typescript_lowercase(v2):
    # JS toLowerCase keeps these distinct; Python casefold incorrectly merges them.
    cells = v2["comparisons"][0]["cells"]
    cells[0]["alternative"] = "Straße"
    cells[1]["alternative"] = "STRASSE"
    assert validate_report_document_v2(v2) == v2


def test_insufficient_evidence_remains_valid_without_invented_assessment(v2):
    v2["findings"] = []
    for row in v2["sections"]:
        row["claimIds"] = []
    for row in v2["requirements"] + v2["questionCoverage"]:
        row.update(status="unresolved", claimIds=[], basis="not_established")
    v2["quality"].update(status="insufficient_evidence", verifiedFindings=0)
    v2["dimensions"] = []
    for row in v2["requirementOutcomes"]:
        row.update(outcome="not_assessed", dimensionIds=[], claimIds=[])
    v2["comparisons"] = []
    assert validate_report_document_v2(v2) == v2


@pytest.mark.parametrize(
    "path,value",
    [
        (("version",), 1),
        (("assessmentVersion",), "evidence-links-v1"),
        (("runId",), "invalid"),
        (("planId",), "invalid"),
        (("assessmentId",), "invalid"),
        (("modePolicyVersion",), "  "),
        (("quality", "status"), "answered"),
        (("quality", "verifiedFindings"), 0),
        (("quality", "status"), "insufficient_evidence"),
        (("sourceIndependence", "status"), "independent"),
        (("sourceIndependence", "reason"), "  "),
        (("dimensions", 0, "status"), "answered"),
        (("dimensions", 0, "basis"), "not_assessed"),
        (("dimensions", 0, "claimIds"), [uid(999)]),
        (("dimensions", 0, "claimIds"), [uid(1), uid(1)]),
        (("dimensions", 0, "requirementIds"), ["question", "question"]),
        (("dimensions", 0, "requirementIds"), ["requirement-2"]),
        (("dimensions", 0, "criteria"), []),
        (("dimensions", 0, "criteria", 0, "claimIds"), []),
        (("dimensions", 0, "criteria", 0, "claimIds"), [uid(999)]),
        (("dimensions", 0, "criteria", 0, "claimIds"), [uid(1), uid(1)]),
        (("dimensions", 0, "criteria", 0, "outcome"), "partial"),
        (("dimensions", 0, "criteria", 0, "basis"), "not_assessed"),
        (("dimensions", 0, "criteria", 0, "outcome"), "answered"),
        (("requirementOutcomes", 0, "id"), "requirement-2"),
        (("requirementOutcomes", 0, "dimensionIds"), [uid(999)]),
        (("requirementOutcomes", 0, "dimensionIds"), [uid(500), uid(500)]),
        (("requirementOutcomes", 0, "dimensionIds"), []),
        (("requirementOutcomes", 0, "claimIds"), [uid(999)]),
        (("requirementOutcomes", 0, "claimIds"), [uid(1), uid(1)]),
        (("requirementOutcomes", 0, "claimIds"), []),
        (("requirementOutcomes", 0, "outcome"), "not_assessed"),
        (("requirementOutcomes", 0, "outcome"), "answered"),
        (("comparisons", 0, "dimensionId"), uid(999)),
        (("comparisons", 0, "cells", 0, "claimIds"), []),
        (("comparisons", 0, "cells", 0, "claimIds"), [uid(999)]),
        (("comparisons", 0, "cells", 0, "claimIds"), [uid(1), uid(1)]),
        (("comparisons", 0, "cells", 1, "claimIds"), [uid(1)]),
        (("comparisons", 0, "cells", 1, "alternative"), "approach a"),
        (("comparisons", 0, "cells", 1, "alternative"), " approach a "),
        (("comparisons", 0, "cells", 1, "alternative"), "  "),
        (("sections", 0, "claimIds"), []),
        (("sections", 0, "claimIds"), [uid(999)]),
        (("sections", 1, "id"), "overview"),
        (("requirements", 0, "claimIds"), [uid(1)]),
        (("requirements", 1, "id"), "requirement-2"),
        (("requirements", 1, "basis"), "not_established"),
        (("questionCoverage", 0, "status"), "unresolved"),
    ],
)
def test_rejects_forged_fields_and_dangling_links(v2, path, value):
    target = v2
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_report_document_v2(v2)


@pytest.mark.parametrize("field", ["dimensions", "requirementOutcomes", "comparisons"])
def test_rejects_duplicate_row_identities(v2, field):
    v2[field].append(deepcopy(v2[field][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        validate_report_document_v2(v2)


def test_rejects_duplicate_criteria_across_different_dimensions(v2):
    duplicate = deepcopy(v2["dimensions"][0])
    duplicate["id"] = uid(501)
    v2["dimensions"].append(duplicate)
    for row in v2["requirementOutcomes"]:
        row["dimensionIds"].append(uid(501))
    with pytest.raises(ValueError, match="Duplicate criterion"):
        validate_report_document_v2(v2)


def test_rejects_missing_requirement_outcome(v2):
    v2["requirementOutcomes"].pop()
    with pytest.raises(ValueError, match="every requirement"):
        validate_report_document_v2(v2)


@pytest.mark.parametrize("collection", ["requirementOutcomes", "comparisons"])
def test_rejects_claims_belonging_only_to_another_dimension(v2, collection):
    second = deepcopy(v2["dimensions"][0])
    second.update(id=uid(501), claimIds=[], status="unresolved", basis="not_assessed")
    second["criteria"][0].update(id=uid(601), outcome="unknown", claimIds=[], basis="not_assessed")
    v2["dimensions"].append(second)
    if collection == "comparisons":
        for row in v2["requirementOutcomes"]:
            row.update(outcome="partially_established", dimensionIds=[uid(500), uid(501)])
        v2["comparisons"][0]["dimensionId"] = uid(501)
    else:
        v2["dimensions"][0]["requirementIds"] = ["requirement-1"]
        second["requirementIds"] = ["question"]
        v2["requirementOutcomes"][0].update(
            outcome="partially_established", dimensionIds=[uid(501)]
        )
    with pytest.raises(ValueError, match="claims must belong"):
        validate_report_document_v2(v2)


def test_no_support_does_not_make_a_comparison(v2):
    v2["comparisons"][0]["cells"][0].update(status="not_established", claimIds=[])
    with pytest.raises(ValueError, match="supported evidence"):
        validate_report_document_v2(v2)


def test_single_alternative_does_not_make_a_comparison(v2):
    v2["comparisons"][0]["cells"].pop()
    with pytest.raises(ValueError):
        validate_report_document_v2(v2)


def test_unknown_assessments_keep_provenance_without_certifying_coverage(v2):
    dim = v2["dimensions"][0]
    dim.update(status="evidence_found", basis="not_assessed")
    dim["criteria"][0].update(outcome="unknown", basis="not_assessed", claimIds=[])
    for row in v2["requirementOutcomes"]:
        row.update(outcome="not_assessed", claimIds=[])
    assert validate_report_document_v2(v2) == v2
    for row in v2["requirementOutcomes"]:
        row.update(outcome="partially_established", claimIds=[uid(1)])
    with pytest.raises(ValueError, match="reviewed support"):
        validate_report_document_v2(v2)


def test_partial_criterion_cannot_certify_established_requirement(v2):
    v2["dimensions"][0].update(status="unresolved")
    v2["dimensions"][0]["criteria"][0]["outcome"] = "partial"
    with pytest.raises(ValueError, match="all mapped dimensions covered"):
        validate_report_document_v2(v2)
    for row in v2["requirementOutcomes"]:
        row["outcome"] = "partially_established"
    assert validate_report_document_v2(v2) == v2


@pytest.fixture
def construction(v1):
    """Run the real planner and pure assessor, using already verified fixture evidence."""
    scope = {
        "tenant_id": UUID(uid(399)),
        "run_id": UUID(uid(400)),
        "plan_id": UUID(uid(401)),
        "assessment_id": UUID(uid(402)),
    }
    plan = attach_coverage_plan(
        run_id=scope["run_id"],
        question=v1["title"],
        requirements=[row["text"] for row in v1["requirements"][1:]],
        questions=[{"question": "Assess costs", "success_criteria": ["Verified cost evidence"]}],
        mode="deep",
        policy_version="research-mode-policy-v1",
        operations=2,
        sources=1,
    )
    finding = v1["findings"][0]
    evidence = ClaimEvidence(
        **scope,
        id=UUID(finding["id"]),
        status="supported",
        dimension_ids=tuple(dim.id for dim in plan.dimensions),
        citations=(
            CitationEvidence(
                id=UUID(finding["citationIds"][0]),
                source_id=UUID(finding["sourceIds"][0]),
                exact_span_verified=True,
                semantic_verdict="supports",
                review_count=1,
            ),
        ),
    )
    inputs = CoverageInput(
        **scope,
        dimensions=tuple(plan.dimensions),
        source_ids=(UUID(finding["sourceIds"][0]),),
        claims=(evidence,),
        criterion_assessments=tuple(
            CriterionAssessment(
                **scope,
                criterion_id=criterion.id,
                dimension_id=dim.id,
                outcome="met",
                claim_ids=(evidence.id,),
                basis="independent_review",
                assessor_version="criterion-review-v1",
                reason="Assessed against preserved exact supporting citations.",
            )
            for dim in plan.dimensions
            for criterion in dim.criteria
        ),
    )
    return {
        "document": v1,
        "run_id": scope["run_id"],
        "plan_id": scope["plan_id"],
        "assessment_id": scope["assessment_id"],
        "mode_policy_version": plan.policy_version,
        "coverage_plan": plan,
        "coverage": assess_coverage(inputs),
        "comparisons": [],
    }


def test_real_planner_assessor_and_enhancer_preserve_provenance(construction):
    original = deepcopy(construction["document"])
    doc = enhance_report_document_v2(**construction)
    assert construction["document"] == original
    assert doc["version"] == 2
    assert doc["assessmentVersion"] == "coverage-ledger-v1"
    assert doc["requirements"] == original["requirements"]
    assert doc["questionCoverage"] == original["questionCoverage"]
    assert {row["status"] for row in doc["dimensions"]} == {"verified_covered"}
    assert {row["outcome"] for row in doc["requirementOutcomes"]} == {"established"}
    assert doc["quality"]["status"] == "partial"
    assert doc["sourceIndependence"]["status"] == "unknown"
    assert validate_report_document(doc) == doc
    assert enhance_report_document_v2(**construction) == doc


def test_real_v1_builder_to_coverage_enhancer(construction):
    original = construction["document"]
    question = original["questionCoverage"][0]
    construction["document"] = build_report_document(
        question=original["title"],
        max_search_calls=20,
        requirements=[row["text"] for row in original["requirements"][1:]],
        findings=[
            {
                **original["findings"][0],
                "subQuestionId": question["id"],
                "requirementIndices": [0],
            }
        ],
        questions=[{"id": question["id"], "question": question["text"]}],
        excluded=original["quality"]["excludedFindings"],
        mode="deep",
    )
    doc = enhance_report_document_v2(**construction)
    assert doc["requirements"] == original["requirements"]
    assert doc["questionCoverage"] == original["questionCoverage"]
    assert {row["outcome"] for row in doc["requirementOutcomes"]} == {"established"}
    assert validate_report_document(doc) == doc


@pytest.mark.parametrize("as_json", [False, True])
def test_enhancer_accepts_coverage_models_and_json_aliases(construction, as_json):
    expected = enhance_report_document_v2(**construction)
    if as_json:
        construction["coverage_plan"] = construction["coverage_plan"].model_dump(mode="json")
        construction["coverage"] = construction["coverage"].model_dump(mode="json", by_alias=True)
    assert enhance_report_document_v2(**construction) == expected


@pytest.mark.parametrize("field", ["run_id", "plan_id", "assessment_id", "mode_policy_version"])
def test_enhancer_rejects_mismatched_scope_or_policy(construction, field):
    construction[field] = "different-policy" if field == "mode_policy_version" else UUID(uid(999))
    with pytest.raises(ValueError, match="identity or policy mismatch"):
        enhance_report_document_v2(**construction)


@pytest.mark.parametrize("tamper", ["missing_dimension", "missing_criterion", "forged_coverage"])
def test_enhancer_rejects_omitted_plan_rows_and_forged_status(construction, tamper):
    coverage = construction["coverage"].model_dump(mode="json", by_alias=True)
    if tamper == "missing_dimension":
        coverage["dimensions"].pop()
    elif tamper == "missing_criterion":
        coverage["dimensions"][0]["criteria"][0]["criterionId"] = uid(999)
    else:
        coverage["dimensions"][0]["criteria"][0]["outcome"] = "partial"
    construction["coverage"] = coverage
    with pytest.raises(ValueError):
        enhance_report_document_v2(**construction)


@pytest.mark.parametrize(
    "basis,version",
    [
        ("not_assessed", None),
        ("deterministic_rule", "criterion-review-v1"),
        ("independent_review", "unrecognized-review-v9"),
    ],
)
def test_unrecognized_criterion_assessments_never_become_established(construction, basis, version):
    coverage = construction["coverage"].model_dump(mode="json", by_alias=True)
    for dimension in coverage["dimensions"]:
        for criterion in dimension["criteria"]:
            criterion.update(assessmentBasis=basis, assessorVersion=version)
    construction["coverage"] = coverage
    doc = enhance_report_document_v2(**construction)
    assert {row["basis"] for row in doc["dimensions"]} == {"not_assessed"}
    assert {row["outcome"] for row in doc["requirementOutcomes"]} == {"not_assessed"}
    assert all(
        not criterion["claimIds"] for row in doc["dimensions"] for criterion in row["criteria"]
    )
