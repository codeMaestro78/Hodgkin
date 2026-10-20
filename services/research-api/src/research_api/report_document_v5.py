"""V5 technical-result projection over a complete, immutable V4 evidence ledger."""

from copy import deepcopy
from typing import Any

from research_api.report_document_v4 import validate_report_document_v4


def validate_report_document_v5(document: dict[str, Any]) -> dict[str, Any]:
    from research_api.schemas.generated.report_document_v4 import ReportDocumentV4
    from research_api.schemas.generated.report_document_v5 import ReportDocumentV5

    doc = ReportDocumentV5.model_validate(deepcopy(document)).model_dump(mode="json", by_alias=True)
    v4_keys = {field.alias or name for name, field in ReportDocumentV4.model_fields.items()}
    validate_report_document_v4(
        {
            **{key: doc[key] for key in v4_keys},
            "version": 4,
            "assessmentVersion": "evidence-narrative-v1",
        }
    )
    findings = {finding["id"]: finding for finding in doc["findings"]}
    for result in doc["technicalResults"]:
        finding = findings.get(result["claimId"])
        if finding is None:
            raise ValueError("Unknown technical claim")
        if not set(result["citationIds"]) <= set(finding["citationIds"]):
            raise ValueError("Technical citation is not verified")
        if not set(result["sourceIds"]) <= set(finding["sourceIds"]):
            raise ValueError("Technical source is not verified")
    return doc


def enhance_report_document_v5(
    document: dict[str, Any], *, technical_results: list[dict[str, Any]]
) -> dict[str, Any]:
    base = validate_report_document_v4(document)
    return validate_report_document_v5(
        {
            **base,
            "version": 5,
            "assessmentVersion": "technical-results-v1",
            "technicalResults": technical_results,
        }
    )
