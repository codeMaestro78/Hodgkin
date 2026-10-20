"""Typed measurement projection over the immutable V5 evidence report."""

from copy import deepcopy
from typing import Any

from research_api.measurements import (
    _plot_value,
    compatible_measurement_charts,
    measurement_comparisons,
)
from research_api.report_document_v5 import validate_report_document_v5


def validate_report_document_v6(document: dict[str, Any]) -> dict[str, Any]:
    from research_api.schemas.generated.report_document_v5 import ReportDocumentV5
    from research_api.schemas.generated.report_document_v6 import ReportDocumentV6

    doc = ReportDocumentV6.model_validate(deepcopy(document)).model_dump(mode="json", by_alias=True)
    v5_keys = {field.alias or name for name, field in ReportDocumentV5.model_fields.items()}
    validate_report_document_v5(
        {
            **{key: doc[key] for key in v5_keys},
            "version": 5,
            "assessmentVersion": "technical-results-v1",
        }
    )
    findings = {row["id"]: row for row in doc["findings"]}
    measurements = {row["id"]: row for row in doc["measurements"]}
    if len(measurements) != len(doc["measurements"]):
        raise ValueError("Duplicate measurement IDs")
    for row in doc["measurements"]:
        finding = findings.get(row["claimId"])
        if (
            finding is None
            or row["citationId"] not in finding["citationIds"]
            or row["sourceId"] not in finding["sourceIds"]
        ):
            raise ValueError("Measurement provenance must link to its verified finding")
        if row["plotValue"] != _plot_value(row["value"]):
            raise ValueError("Measurement plot coordinate must match its exact numeric literal")
    if doc["measurementComparisons"] != measurement_comparisons(doc["measurements"]):
        raise ValueError("Measurement comparisons must be deterministic projections")
    if doc["measurementCharts"] != compatible_measurement_charts(doc["measurements"]):
        raise ValueError("Measurement charts must be deterministic projections")
    if len({row["id"] for row in doc["measurementCharts"]}) != len(doc["measurementCharts"]):
        raise ValueError("Duplicate measurement chart IDs")
    for chart in doc["measurementCharts"]:
        rows = [measurements.get(key) for key in chart["measurementIds"]]
        fields = ("metric", "unit", "population", "period", "method", "definition")
        if any(row is None for row in rows):
            raise ValueError("Chart references missing or unplottable measurements")
        selected = [row for row in rows if row is not None]
        if any(row["plotValue"] is None for row in selected):
            raise ValueError("Chart references missing or unplottable measurements")
        if any(any(row[field] != chart[field] for field in fields) for row in selected):
            raise ValueError("Chart measurement definitions are incompatible")
        if len({row["subject"] for row in selected}) != len(selected):
            raise ValueError("Chart subjects must be unique")
    return doc


def enhance_report_document_v6(
    document: dict[str, Any],
    *,
    measurements: list[dict[str, Any]],
    measurement_comparisons: list[dict[str, Any]],
    measurement_charts: list[dict[str, Any]],
) -> dict[str, Any]:
    base = validate_report_document_v5(document)
    return validate_report_document_v6(
        {
            **base,
            "version": 6,
            "assessmentVersion": "typed-measurements-v1",
            "measurements": measurements,
            "measurementComparisons": measurement_comparisons,
            "measurementCharts": measurement_charts,
        }
    )
