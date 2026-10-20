from copy import deepcopy

import pytest

from research_api.measurements import (
    compatible_measurement_charts,
    measurement_comparisons,
)
from research_api.mode_composer import compose_report
from research_api.report_document_v5 import enhance_report_document_v5
from research_api.report_document_v6 import enhance_report_document_v6
from tests.unit.test_report_document_v3 import v3 as v3  # noqa: F401 -- pytest fixture import
from tests.unit.test_report_document_v4 import v4 as v4


def measurement(v4_document, index, subject, value):
    finding = v4_document["findings"][0]
    return {
        "id": f"measurement-{index}",
        "title": f"Outcome for {subject}",
        "claimId": finding["id"],
        "citationId": finding["citationIds"][0],
        "sourceId": finding["sourceIds"][0],
        "sourceArtifactHash": "a" * 64,
        "subject": subject,
        "metric": "response rate",
        "value": value,
        "unit": "%",
        "population": "adults",
        "period": "2024",
        "method": "randomized trial",
        "definition": "participants with response",
        "sourcePassage": f"Outcome for {subject}: response rate {value}% in adults, 2024.",
        "sourceLocation": "Table 2",
        "plotValue": value,
        "verification": "exact_passage_and_scoped_semantic_claim_review_v1",
    }


def base_report(v4_document):
    v5 = enhance_report_document_v5(v4_document, technical_results=[])
    rows = [measurement(v5, 1, "Group A", "47.2"), measurement(v5, 2, "Group B", "51.0")]
    return v5, rows


def chart(rows):
    return compatible_measurement_charts(rows)[0]


def test_v6_admits_explicit_source_measurements_and_compatible_chart(v4):
    before = deepcopy(v4)
    base, rows = base_report(v4)
    doc = enhance_report_document_v6(
        base,
        measurements=rows,
        measurement_comparisons=measurement_comparisons(rows),
        measurement_charts=[chart(rows)],
    )
    assert doc["version"] == 6
    assert doc["measurements"][0]["value"] == "47.2"
    assert doc["measurementCharts"][0]["measurementIds"] == ["measurement-1", "measurement-2"]
    markdown = compose_report(
        doc,
        sources=[
            (source_id, "Study", "https://example.org/study")
            for source_id in dict.fromkeys(
                source_id for finding in doc["findings"] for source_id in finding["sourceIds"]
            )
        ],
    )
    assert "Comparable within recorded scope" in markdown
    assert v4 == before


def test_v6_rejects_mismatched_scope_or_modified_plot_coordinate(v4):
    base, rows = base_report(v4)
    incompatible = deepcopy(rows)
    incompatible[1]["population"] = "children"
    with pytest.raises(ValueError, match="deterministic projections"):
        enhance_report_document_v6(
            base,
            measurements=incompatible,
            measurement_comparisons=measurement_comparisons(incompatible),
            measurement_charts=[chart(rows)],
        )

    altered = deepcopy(rows)
    altered[0]["plotValue"] = "48.2"
    with pytest.raises(ValueError, match="exact numeric literal"):
        enhance_report_document_v6(
            base,
            measurements=altered,
            measurement_comparisons=measurement_comparisons(altered),
            measurement_charts=[],
        )


def test_v6_keeps_table_rows_but_does_not_chart_unknown_scope(v4):
    base, rows = base_report(v4)
    rows[0]["population"] = None
    comparisons = measurement_comparisons(rows)
    doc = enhance_report_document_v6(
        base,
        measurements=rows,
        measurement_comparisons=comparisons,
        measurement_charts=[],
    )
    assert doc["measurements"][0]["population"] is None
    assert doc["measurementCharts"] == []
    assert doc["measurementComparisons"][0]["status"] == "not_established"
    markdown = compose_report(
        doc,
        sources=[
            (source_id, "Study", "https://example.org/study")
            for source_id in dict.fromkeys(
                source_id for finding in doc["findings"] for source_id in finding["sourceIds"]
            )
        ],
    )
    assert "Not established — scope is missing or incompatible" in markdown


def test_v6_does_not_mutate_v5_document(v4):
    base, rows = base_report(v4)
    before = deepcopy(base)
    enhance_report_document_v6(
        base,
        measurements=rows,
        measurement_comparisons=measurement_comparisons(rows),
        measurement_charts=compatible_measurement_charts(rows),
    )
    assert base == before
