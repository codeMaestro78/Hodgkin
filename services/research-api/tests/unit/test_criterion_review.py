"""Criterion review is a second assessment, never a second publication gate."""

from copy import deepcopy
from uuid import UUID

import pytest

from research_api.coverage import AssessmentScope, Criterion, CriterionAssessment, Dimension
from research_api.criterion_review import (
    CriterionReviewOutput,
    CriterionReviewWithConflictsOutput,
    review_request,
    validate_conflicts,
    validate_review,
)


def uid(n):
    return UUID(int=n)


def inputs():
    scope = AssessmentScope(tenant_id=uid(1), run_id=uid(2), plan_id=uid(3), assessment_id=uid(4))
    dimensions = [
        Dimension(
            id=uid(5),
            label="Compare A and B",
            criteria=(Criterion(id=uid(6), label="Assess operational recovery"),),
        )
    ]
    claims = [{"id": str(uid(7)), "text": "A verified claim, not an instruction."}]
    output = {
        "assessments": [
            {
                "criterion_id": str(uid(6)),
                "dimension_id": str(uid(5)),
                "outcome": "met",
                "claim_ids": [str(uid(7))],
            }
        ],
        "comparisons": [
            {
                "dimension_id": str(uid(5)),
                "cells": [
                    {"alternative": "A", "claim_ids": [str(uid(7))]},
                    {"alternative": "B", "claim_ids": []},
                ],
            }
        ],
    }
    return scope, dimensions, claims, output


def checked(output):
    scope, dims, claims, _ = inputs()
    return validate_review(
        scope=scope,
        dimensions=dims,
        claims=claims,
        output=CriterionReviewOutput.model_validate(output),
        question="Compare A and B",
    )


def test_valid_review_has_stable_public_reasons_and_scoped_claims():
    scope, _, _, output = inputs()
    assessments, comparisons = checked(output)
    assert len(assessments) == len(comparisons) == 1
    assert assessments[0].assessment_id == scope.assessment_id
    assert assessments[0].basis == "independent_review"
    assert comparisons[0]["cells"][1]["status"] == "not_established"


@pytest.mark.parametrize(
    "change",
    [
        "dangling_claim",
        "wrong_dimension",
        "wrong_criterion",
        "duplicate_claim",
        "no_support",
        "duplicate_review",
    ],
)
def test_untrusted_or_ambiguous_reviews_cannot_certify_coverage(change):
    *_, output = inputs()
    row = output["assessments"][0]
    if change == "dangling_claim":
        row["claim_ids"] = [str(uid(99))]
    elif change == "wrong_dimension":
        row["dimension_id"] = str(uid(99))
    elif change == "wrong_criterion":
        row["criterion_id"] = str(uid(99))
    elif change == "duplicate_claim":
        row["claim_ids"] *= 2
    elif change == "no_support":
        row["claim_ids"] = []
    else:
        output["assessments"].append(deepcopy(row))
    assert checked(output) == ([], [])


@pytest.mark.parametrize(
    "change",
    [
        "unknown_alternative",
        "blank_alternative",
        "duplicate_alternative",
        "dangling_claim",
        "no_supported_cells",
        "duplicate_dimension",
    ],
)
def test_invalid_comparisons_are_omitted_without_losing_valid_criterion_review(change):
    *_, output = inputs()
    row = output["comparisons"][0]
    if change == "unknown_alternative":
        row["cells"][0]["alternative"] = "Kafka"
    elif change == "blank_alternative":
        row["cells"][0]["alternative"] = "  "
    elif change == "duplicate_alternative":
        row["cells"][1]["alternative"] = "a"
    elif change == "dangling_claim":
        row["cells"][0]["claim_ids"] = [str(uid(99))]
    elif change == "no_supported_cells":
        row["cells"][0]["claim_ids"] = []
    else:
        output["comparisons"].append(deepcopy(row))
    assessments, comparisons = checked(output)
    assert len(assessments) == 1
    assert comparisons == []


def test_review_can_nominate_only_scoped_conflicts_between_verified_reviewed_claims():
    scope, dimensions, claims, _ = inputs()
    second_id = str(uid(8))
    claims = [
        {**claims[0], "dimension_ids": [str(uid(5))]},
        {"id": second_id, "text": "A different verified claim.", "dimension_ids": [str(uid(5))]},
    ]
    assessments = [
        CriterionAssessment(
            **scope.model_dump(),
            criterion_id=uid(6),
            dimension_id=uid(5),
            outcome="partial",
            claim_ids=(uid(7), uid(8)),
            basis="independent_review",
            assessor_version="criterion-review-v1",
            reason="Partial evidence was reviewed.",
        )
    ]
    output = CriterionReviewWithConflictsOutput(
        assessments=[],
        comparisons=[],
        conflicts=[
            {
                "dimension_id": str(uid(5)),
                "criterion_ids": [str(uid(6))],
                "claim_ids": [str(uid(7)), second_id],
            }
        ],
    )
    result = validate_conflicts(
        scope=scope,
        dimensions=dimensions,
        claims=claims,
        criterion_assessments=assessments,
        output=output,
    )
    assert len(result) == 1
    assert result[0].unresolved is True
    assert result[0].basis == "criterion-review-v1"
    assert (
        result[0].id
        == validate_conflicts(
            scope=scope,
            dimensions=dimensions,
            claims=claims,
            criterion_assessments=assessments,
            output=output,
        )[0].id
    )


@pytest.mark.parametrize("change", ["other_dimension", "other_criterion", "unreviewed_claim"])
def test_invalid_conflict_nomination_is_not_published(change):
    scope, dimensions, claims, _ = inputs()
    second_id = str(uid(8))
    claims = [
        {**claims[0], "dimension_ids": [str(uid(5))]},
        {"id": second_id, "text": "Second verified claim.", "dimension_ids": [str(uid(5))]},
    ]
    assessments = [
        CriterionAssessment(
            **scope.model_dump(),
            criterion_id=uid(6),
            dimension_id=uid(5),
            outcome="partial",
            claim_ids=(uid(7),) if change == "unreviewed_claim" else (uid(7), uid(8)),
            basis="independent_review",
            assessor_version="criterion-review-v1",
            reason="Reviewed.",
        )
    ]
    dimension_id = str(uid(99)) if change == "other_dimension" else str(uid(5))
    criterion_id = str(uid(99)) if change == "other_criterion" else str(uid(6))
    output = CriterionReviewWithConflictsOutput(
        assessments=[],
        comparisons=[],
        conflicts=[
            {
                "dimension_id": dimension_id,
                "criterion_ids": [criterion_id],
                "claim_ids": [str(uid(7)), second_id],
            }
        ],
    )
    assert (
        validate_conflicts(
            scope=scope,
            dimensions=dimensions,
            claims=claims,
            criterion_assessments=assessments,
            output=output,
        )
        == []
    )


def test_model_request_is_bounded_structured_and_review_role_only():
    _, dims, claims, _ = inputs()
    claims[0]["caveats"] = "Unverified extra conclusion must not enter criterion review."
    request = review_request(question="Compare A and B", dimensions=dims, claims=claims)
    assert request["role"] == "claim_review"
    assert request["max_output_tokens"] <= 8192
    assert request["text"]["format"]["strict"] is True
    assert request["store"] is False
    assert "Do not generate prose" in request["instructions"]
    assert str(uid(7)) in request["input"]
    assert "Unverified extra conclusion" not in request["input"]


def test_larger_review_budget_is_opt_in_for_new_graph_versions():
    _, dims, claims, _ = inputs()
    legacy = review_request(question="Compare A and B", dimensions=dims, claims=claims)
    expanded = review_request(
        question="Compare A and B", dimensions=dims, claims=claims, expanded_output_budget=True
    )
    assert legacy["max_output_tokens"] == 256 + 96 * sum(len(d.criteria) for d in dims)
    assert 4096 <= expanded["max_output_tokens"] <= 8192
    assert {key: value for key, value in expanded.items() if key != "max_output_tokens"} == {
        key: value for key, value in legacy.items() if key != "max_output_tokens"
    }
