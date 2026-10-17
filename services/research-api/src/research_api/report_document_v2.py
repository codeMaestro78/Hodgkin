"""Project authenticated criterion assessments onto a verified, immutable ledger.

V1 evidence associations keep their original meaning. These additional outcomes
are not a second factual writing channel and never certify an answered report.
"""

from copy import deepcopy
from typing import Any
from uuid import UUID

from research_api.coverage import CoverageResult
from research_api.mode_planning import CoveragePlan
from research_api.report_document import _unique, _validate_report_document_v1


def validate_report_document_v2(document: dict[str, Any]) -> dict[str, Any]:
    # Lazy import keeps historical readers usable during contract regeneration.
    from research_api.schemas.generated.report_document_v2 import ReportDocumentV2

    # JSON Schema omits Zod transforms. Mirror trim-before-bounds without
    # mutating caller-owned immutable report data.
    normalized = deepcopy(document)
    comparisons = normalized.get("comparisons")
    if isinstance(comparisons, list):
        for comparison in comparisons:
            if not isinstance(comparison, dict) or not isinstance(comparison.get("cells"), list):
                continue
            for cell in comparison["cells"]:
                if isinstance(cell, dict) and isinstance(cell.get("alternative"), str):
                    cell["alternative"] = cell["alternative"].strip()
    doc = ReportDocumentV2.model_validate(normalized).model_dump(mode="json", by_alias=True)
    from research_api.schemas.generated.report_document_v1 import ReportDocumentV1

    keys = {f.alias or name for name, f in ReportDocumentV1.model_fields.items()}
    _validate_report_document_v1(
        {**{key: doc[key] for key in keys}, "version": 1, "assessmentVersion": "evidence-links-v1"}
    )
    claims = {row["id"] for row in doc["findings"]}
    requirements = {row["id"] for row in doc["requirements"]}
    dimensions = {row["id"]: row for row in doc["dimensions"]}
    _unique([row["id"] for row in doc["dimensions"]], "dimension IDs")
    _unique([c["id"] for d in dimensions.values() for c in d["criteria"]], "criterion IDs")

    def linked(ids: list[str]) -> None:
        _unique(ids, "assessed claim links")
        if not set(ids) <= claims:
            raise ValueError("Dangling assessed claim link")

    for dim in dimensions.values():
        linked(dim["claimIds"])
        _unique(dim["requirementIds"], "dimension requirement links")
        if not set(dim["requirementIds"]) <= requirements:
            raise ValueError("Unknown dimension requirement")
        for criterion in dim["criteria"]:
            linked(criterion["claimIds"])
            if not set(criterion["claimIds"]) <= set(dim["claimIds"]):
                raise ValueError("Criterion claims must belong to dimension")
            reviewed = criterion["basis"] == "criterion-review-v1"
            if not reviewed and (criterion["outcome"] != "unknown" or criterion["claimIds"]):
                raise ValueError("Unassessed criterion cannot certify an outcome")
            if criterion["outcome"] in {"met", "partial"} and (
                not reviewed or not criterion["claimIds"]
            ):
                raise ValueError("Met/partial criterion needs reviewed support")
        reviewed = any(c["basis"] == "criterion-review-v1" for c in dim["criteria"])
        if (dim["basis"] == "criterion-review-v1") != reviewed:
            raise ValueError("Dimension basis must match criterion reviews")
        if dim["status"] == "verified_covered" and (
            not reviewed
            or not dim["claimIds"]
            or any(c["outcome"] != "met" for c in dim["criteria"])
        ):
            raise ValueError("Verified coverage requires every criterion to be met")
    _unique([row["id"] for row in doc["requirementOutcomes"]], "requirement outcomes")
    if {row["id"] for row in doc["requirementOutcomes"]} != requirements:
        raise ValueError("Requirement outcomes must cover every requirement")
    for row in doc["requirementOutcomes"]:
        linked(row["claimIds"])
        _unique(row["dimensionIds"], "outcome dimension links")
        mapped = {d["id"] for d in dimensions.values() if row["id"] in d["requirementIds"]}
        if set(row["dimensionIds"]) != mapped:
            raise ValueError("Requirement outcome must retain all mapped dimensions")
        dims = [dimensions[key] for key in row["dimensionIds"]]
        if not set(row["claimIds"]) <= {key for d in dims for key in d["claimIds"]}:
            raise ValueError("Outcome claims must belong to linked dimensions")
        if row["outcome"] == "not_assessed" and row["claimIds"]:
            raise ValueError("Unassessed requirement cannot certify support")
        if row["outcome"] in {"established", "partially_established"}:
            reviewed_claims = {
                key
                for d in dims
                for c in d["criteria"]
                if c["basis"] == "criterion-review-v1" and c["outcome"] in {"met", "partial"}
                for key in c["claimIds"]
            }
            if not dims or not row["claimIds"] or not set(row["claimIds"]) <= reviewed_claims:
                raise ValueError("Established requirement needs reviewed support")
            if row["outcome"] == "established" and any(
                d["status"] != "verified_covered" for d in dims
            ):
                raise ValueError("Established requirement needs all mapped dimensions covered")
    _unique([row["dimensionId"] for row in doc["comparisons"]], "comparison dimensions")
    for row in doc["comparisons"]:
        dim = dimensions.get(row["dimensionId"])
        if dim is None:
            raise ValueError("Unknown comparison dimension")
        _unique([c["alternative"].lower() for c in row["cells"]], "comparison alternatives")
        if not any(c["status"] == "supported" for c in row["cells"]):
            raise ValueError("Comparison needs supported evidence")
        for cell in row["cells"]:
            linked(cell["claimIds"])
            if (cell["status"] == "supported") != bool(cell["claimIds"]):
                raise ValueError("Comparison cell support must match claim links")
            if not set(cell["claimIds"]) <= set(dim["claimIds"]):
                raise ValueError("Comparison claims must belong to dimension")
    return doc


def enhance_report_document_v2(
    document: dict[str, Any],
    *,
    run_id: UUID,
    plan_id: UUID,
    assessment_id: UUID,
    mode_policy_version: str,
    coverage_plan: CoveragePlan | dict[str, Any],
    coverage: CoverageResult | dict[str, Any],
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    base = _validate_report_document_v1(document)
    plan = CoveragePlan.model_validate(coverage_plan)
    result = CoverageResult.model_validate(coverage)
    if (
        (result.run_id, result.plan_id, result.assessment_id)
        != (UUID(str(run_id)), UUID(str(plan_id)), UUID(str(assessment_id)))
        or plan.policy_version != mode_policy_version
        or plan.mode != base["mode"]
    ):
        raise ValueError("Assessment identity or policy mismatch")
    by_id = {d.id: d for d in plan.dimensions}
    if {d.dimension_id for d in result.dimensions} != set(by_id):
        raise ValueError("Coverage must retain every planned dimension")
    dimensions: list[dict[str, Any]] = []
    for dim in result.dimensions:
        planned = by_id[dim.dimension_id]
        if {c.criterion_id for c in dim.criteria} != {c.id for c in planned.criteria}:
            raise ValueError("Coverage must retain every planned criterion")
        criteria = []
        for criterion in dim.criteria:
            reviewed = (
                criterion.assessment_basis == "independent_review"
                and criterion.assessor_version == "criterion-review-v1"
            )
            criteria.append(
                {
                    "id": str(criterion.criterion_id),
                    "outcome": criterion.outcome if reviewed else "unknown",
                    "claimIds": [str(key) for key in criterion.claim_ids] if reviewed else [],
                    "basis": "criterion-review-v1" if reviewed else "not_assessed",
                    "reason": criterion.reason
                    if reviewed
                    else "Criterion satisfaction was not assessed.",
                }
            )
        mapped = [key for key, ids in plan.requirement_dimensions.items() if planned.id in ids]
        # Task dimensions contextualize the main question, not extra requirements.
        dimensions.append(
            {
                "id": str(planned.id),
                "label": planned.label,
                "requirementIds": mapped or ["question"],
                "status": dim.state
                if all(c["basis"] != "not_assessed" for c in criteria)
                else ("evidence_found" if dim.verified_claim_ids else "unresolved"),
                "claimIds": [str(key) for key in dim.verified_claim_ids],
                "reason": dim.reason,
                "basis": "criterion-review-v1"
                if any(c["basis"] != "not_assessed" for c in criteria)
                else "not_assessed",
                "criteria": criteria,
            }
        )
    outcomes = []
    for requirement in base["requirements"]:
        dims = [d for d in dimensions if requirement["id"] in d["requirementIds"]]
        supported = list(
            dict.fromkeys(
                key
                for d in dims
                for c in d["criteria"]
                if c["basis"] == "criterion-review-v1" and c["outcome"] in {"met", "partial"}
                for key in c["claimIds"]
            )
        )
        outcome = (
            "established"
            if dims and all(d["status"] == "verified_covered" for d in dims) and supported
            else "partially_established"
            if supported
            else "not_established"
            if any(d["basis"] == "criterion-review-v1" for d in dims)
            else "not_assessed"
        )
        outcomes.append(
            {
                "id": requirement["id"],
                "outcome": outcome,
                "dimensionIds": [d["id"] for d in dims],
                "claimIds": supported,
                "reason": {
                    "established": "All mapped criteria were established by reviewed findings.",
                    "partially_established": (
                        "Reviewed findings establish only part of this requirement."
                    ),
                    "not_established": "Reviewed evidence did not establish this requirement.",
                    "not_assessed": "Requirement satisfaction was not assessed.",
                }[outcome],
            }
        )
    return validate_report_document_v2(
        {
            **base,
            "version": 2,
            "assessmentVersion": "coverage-ledger-v1",
            "runId": str(run_id),
            "planId": str(plan_id),
            "assessmentId": str(assessment_id),
            "modePolicyVersion": mode_policy_version,
            "dimensions": dimensions,
            "requirementOutcomes": outcomes,
            "comparisons": comparisons,
            "sourceIndependence": {
                "status": "unknown",
                "reason": (
                    "Content and bibliographic identity relationships do not establish "
                    "publisher independence."
                ),
            },
            "quality": {
                **base["quality"],
                "reason": (
                    "Criterion reviews distinguish supported coverage from unresolved "
                    "requirements; "
                    "this report is not certified as a complete answer."
                ),
            },
        }
    )
