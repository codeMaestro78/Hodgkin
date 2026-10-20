from copy import deepcopy

import pytest

from research_api.mode_composer import compose_report
from research_api.report_document import validate_report_document
from research_api.report_document_v5 import enhance_report_document_v5
from tests.unit.test_report_document_v3 import v3 as v3  # noqa: F401 -- fixture import
from tests.unit.test_report_document_v4 import v4 as v4  # noqa: F401 -- fixture import


def result(v4):
    finding = v4["findings"][0]
    return {
        "kind": "theorem",
        "title": "Theorem 2",
        "claimId": finding["id"],
        "citationIds": finding["citationIds"][:1],
        "sourceIds": finding["sourceIds"][:1],
        "sourceArtifactHash": "a" * 64,
        "assumptions": ["reversible continuous-time chains"],
        "notation": [],
        "sourceLocation": "Theorem 2",
        "expression": {
            "sourceText": "t_mix <= log(1/pi_min)/lambda",
            "representation": "plain_text",
            "transformation": "none",
        },
        "verification": "exact_passage_and_scoped_semantic_claim_review_v2",
    }


def test_v5_preserves_v4_and_renders_literal_expression(v4):
    doc = enhance_report_document_v5(v4, technical_results=[result(v4)])
    assert validate_report_document(doc) == doc
    source_ids = list(
        dict.fromkeys(
            source_id for finding in doc["findings"] for source_id in finding["sourceIds"]
        )
    )
    markdown = compose_report(
        doc,
        sources=[(source_id, "Source", "https://example.org") for source_id in source_ids],
    )
    assert "Source-stated technical results" in markdown
    assert "t_mix <= log(1/pi_min)/lambda" in markdown


def test_v5_rejects_unlinked_claim_or_citation(v4):
    row = result(v4)
    row["claimId"] = "00000000-0000-4000-8000-000000000777"
    with pytest.raises(ValueError, match="Unknown technical claim"):
        enhance_report_document_v5(v4, technical_results=[row])
    row = result(v4)
    row["citationIds"] = ["00000000-0000-4000-8000-000000000777"]
    with pytest.raises(ValueError, match="Technical citation is not verified"):
        enhance_report_document_v5(v4, technical_results=[row])


def test_v5_does_not_mutate_v4(v4):
    before = deepcopy(v4)
    enhance_report_document_v5(v4, technical_results=[])
    assert v4 == before
