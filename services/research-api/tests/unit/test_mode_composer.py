"""Factual prose may organize a verified ledger, not expand it unchecked."""

from copy import deepcopy
from uuid import UUID

import pytest

from research_api.mode_composer import FactualBlock, compose_report, validate_alignment
from research_api.report_document import build_report_document, report_diagnostics


def uid(n):
    return str(UUID(int=(4 << 76) | (2 << 62) | n))


def document(mode="focused", empty=False):
    finding = {
        "id": uid(1),
        "text": "Recorded evidence supports this narrow claim.",
        "section": "mechanisms",
        "citationIds": [uid(2)],
        "sourceIds": [uid(3)],
        "subQuestionId": uid(4),
        "requirementIndices": [],
    }
    base = build_report_document(
        question="Compare A and B",
        max_search_calls=6,
        requirements=[],
        findings=[] if empty else [finding],
        questions=[{"id": uid(4), "question": "Compare recovery"}],
        excluded=0,
        mode=mode,
    )
    keys = [] if empty else [uid(1)]
    return {
        **base,
        "version": 2,
        "assessmentVersion": "coverage-ledger-v1",
        "runId": uid(5),
        "planId": uid(6),
        "assessmentId": uid(7),
        "modePolicyVersion": "research-mode-policy-v1",
        "dimensions": [
            {
                "id": uid(8),
                "label": "Recovery",
                "requirementIds": ["question"],
                "status": "unresolved",
                "claimIds": keys,
                "reason": "Not established.",
                "basis": "not_assessed",
                "criteria": [
                    {
                        "id": uid(9),
                        "outcome": "unknown",
                        "claimIds": [],
                        "basis": "not_assessed",
                        "reason": "Not assessed.",
                    }
                ],
            }
        ],
        "requirementOutcomes": [
            {
                "id": "question",
                "outcome": "not_assessed",
                "dimensionIds": [uid(8)],
                "claimIds": [],
                "reason": "Not assessed.",
            }
        ],
        "comparisons": [],
        "sourceIndependence": {"status": "unknown", "reason": "Unknown."},
    }


SOURCES = [(uid(3), "Original source", "https://example.org/source")]


@pytest.mark.parametrize("mode", ["focused", "balanced", "deep"])
def test_composer_keeps_literal_findings_citations_and_honest_coverage(mode):
    doc = document(mode)
    before = deepcopy(doc)
    markdown = compose_report(doc, sources=SOURCES)
    assert markdown.count(doc["findings"][0]["text"]) == 1
    assert doc["findings"][0]["text"] + " [1]" in markdown
    assert "Not assessed" in markdown
    assert "Source independence remains unknown" in markdown
    assert doc == before
    assert markdown == compose_report(doc, sources=SOURCES)
    if mode == "deep":
        assert "## Scope and research questions" in markdown
    elif mode == "focused":
        assert "## Direct findings" in markdown
        assert "## Scope and research questions" not in markdown


def test_empty_evidence_never_gets_empty_analysis_or_fake_summary():
    markdown = compose_report(document("deep", empty=True), sources=[])
    assert "## Answer not established" in markdown
    assert "## Executive findings" not in markdown
    assert "## Evidence comparison" not in markdown
    assert "## Source links" not in markdown


@pytest.mark.parametrize(
    "block",
    [
        FactualBlock("A novel unsupported conclusion.", (uid(1),)),
        FactualBlock("Recorded evidence supports this narrow claim.", (uid(99),)),
        FactualBlock("Recorded evidence supports this narrow claim.", ()),
        FactualBlock("Recorded evidence supports this narrow claim.", (uid(1), uid(1))),
    ],
)
def test_alignment_rejects_unchecked_new_prose_even_with_a_valid_claim_id(block):
    with pytest.raises(ValueError):
        validate_alignment(document(), [block])


def test_missing_or_duplicate_source_identity_cannot_be_published():
    with pytest.raises(ValueError, match="unavailable"):
        compose_report(document(), sources=[])
    with pytest.raises(ValueError, match="Duplicate"):
        compose_report(document(), sources=SOURCES * 2)


def test_comparison_preserves_not_established_cells_and_claim_links():
    doc = document("balanced")
    doc["comparisons"] = [
        {
            "dimensionId": uid(8),
            "cells": [
                {"alternative": "A", "status": "supported", "claimIds": [uid(1)]},
                {"alternative": "B", "status": "not_established", "claimIds": []},
            ],
        }
    ]
    markdown = compose_report(doc, sources=SOURCES)
    assert "| B | Not established |" in markdown
    assert "| A | Recorded evidence supports this narrow claim. [1] |" in markdown


def test_benchmark_dual_read_does_not_confuse_legacy_links_with_assessed_coverage():
    v2 = document()
    diagnostic = report_diagnostics(v2)
    assert diagnostic["documentVersion"] == 2
    assert diagnostic["assessed"]["dimensionsVerifiedCovered"] == 0
    assert diagnostic["assessed"]["requirementsUnassessed"] == 1
    v1 = build_report_document(
        question="Compare A and B",
        max_search_calls=6,
        requirements=[],
        findings=[],
        questions=[],
        excluded=0,
    )
    diagnostic = report_diagnostics(v1)
    assert diagnostic["documentVersion"] == 1
    assert diagnostic["assessed"] is None
    assert diagnostic["humanQualityAssessed"] is False
