"""V3 report projection for observed source lineage and potential disagreements."""

import re
from copy import deepcopy
from typing import Any
from uuid import UUID

from research_api.coverage import CoverageResult
from research_api.report_document import _unique
from research_api.report_document_v2 import validate_report_document_v2


def validate_report_document_v3(document: dict[str, Any]) -> dict[str, Any]:
    from research_api.schemas.generated.report_document_v2 import ReportDocumentV2
    from research_api.schemas.generated.report_document_v3 import ReportDocumentV3

    doc = ReportDocumentV3.model_validate(deepcopy(document)).model_dump(mode="json", by_alias=True)
    v2_keys = {field.alias or name for name, field in ReportDocumentV2.model_fields.items()}
    validate_report_document_v2(
        {
            **{key: doc[key] for key in v2_keys},
            "version": 2,
            "assessmentVersion": "coverage-ledger-v1",
        }
    )

    report_sources = {source for finding in doc["findings"] for source in finding["sourceIds"]}
    relationship_keys = []
    for relationship in doc["sourceRelationships"]:
        left, right = relationship["fromSourceId"], relationship["toSourceId"]
        if left >= right or left not in report_sources or right not in report_sources:
            raise ValueError("Source relationship must link two report sources in canonical order")
        kind, basis, identifier = (
            relationship["kind"],
            relationship["basis"],
            relationship.get("identifier"),
        )
        if relationship["confidence"] != "observed":
            raise ValueError("Report provenance only supports directly observed confidence")
        expected = {
            "same_content": ("observed_content_hash_match", None),
            "same_work": ("observed_doi_match", "doi:"),
            "same_publisher": ("verified_publisher_metadata_match", "nonempty"),
        }[kind]
        if basis != expected[0]:
            raise ValueError("Relationship basis does not match its kind")
        if expected[1] is None:
            if identifier is not None:
                raise ValueError("Content hash values must not be disclosed in the report")
        elif not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Relationship requires an observed, kind-specific identifier")
        if kind == "same_work" and not re.fullmatch(
            r"doi:10\.\d{4,9}/[^\s\x00-\x1f\x7f]+", identifier, re.IGNORECASE
        ):
            raise ValueError("Same-work relationship requires a DOI identity")
        if kind == "same_publisher" and len(identifier) > 250:
            raise ValueError("Publisher identifier exceeds its persisted metadata bound")
        relationship_keys.append((left, right, kind))
    _unique(relationship_keys, "source relationships")

    dimensions = {row["id"]: row for row in doc["dimensions"]}
    _unique([row["id"] for row in doc["conflicts"]], "conflict IDs")
    conflict_keys = []
    for conflict in doc["conflicts"]:
        dimension = dimensions.get(conflict["dimensionId"])
        if dimension is None:
            raise ValueError("Conflict references an unknown dimension")
        _unique(conflict["criterionIds"], "conflict criteria")
        _unique(conflict["claimIds"], "conflict claims")
        criteria = {row["id"]: row for row in dimension["criteria"]}
        if not set(conflict["criterionIds"]) <= criteria.keys():
            raise ValueError("Conflict references an unknown criterion")
        if not set(conflict["claimIds"]) <= set(dimension["claimIds"]):
            raise ValueError("Conflict claims must belong to the linked dimension")
        criterion_claims = {
            claim_id
            for criterion_id in conflict["criterionIds"]
            for claim_id in criteria[criterion_id]["claimIds"]
        }
        if not set(conflict["claimIds"]) <= criterion_claims:
            raise ValueError("Conflict claims must be linked to its reviewed criterion")
        conflict_keys.append(
            (
                conflict["dimensionId"],
                tuple(sorted(conflict["criterionIds"])),
                tuple(sorted(conflict["claimIds"])),
            )
        )
    _unique(conflict_keys, "conflict assessments")
    return doc


def enhance_report_document_v3(
    document: dict[str, Any],
    *,
    source_relationships: list[dict[str, Any]],
    coverage: CoverageResult | dict[str, Any],
) -> dict[str, Any]:
    """Extend V2 without changing historical semantics or claiming adjudication."""
    from research_api.report_document_v2 import validate_report_document_v2

    base = validate_report_document_v2(document)
    result = CoverageResult.model_validate(coverage)
    if (result.run_id, result.plan_id, result.assessment_id) != (
        UUID(base["runId"]),
        UUID(base["planId"]),
        UUID(base["assessmentId"]),
    ):
        raise ValueError("Conflict assessment scope does not match the report")
    conflicts = [
        {
            "id": str(row.id),
            "dimensionId": str(row.dimension_id),
            "criterionIds": [str(value) for value in row.criterion_ids],
            "claimIds": [str(value) for value in row.claim_ids],
            "status": "potential",
            "basis": "criterion-review-v1",
            "reason": row.reason,
        }
        for row in result.conflicts
    ]
    return validate_report_document_v3(
        {
            **base,
            "version": 3,
            "assessmentVersion": "provenance-conflicts-v1",
            "sourceRelationships": source_relationships,
            "conflicts": conflicts,
            "sourceIndependence": {
                "status": "unknown",
                "reason": (
                    "Observed content, work, or publisher relationships do not establish "
                    "source or publisher independence."
                ),
            },
        }
    )
