from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.config import Settings
from research_api.graph import builder
from research_api.reports import ReportFinding, render_report, report_policy, select_passages


def test_report_modes_have_distinct_bounded_depth():
    policies = [report_policy(calls) for calls in (6, 12, 20)]
    assert [p.mode for p in policies] == ["focused", "balanced", "deep"]
    assert [p.source_count for p in policies] == [6, 12, 20]
    assert [p.candidate_count for p in policies] == [12, 24, 40]
    assert policies[0].context_chars < policies[1].context_chars < policies[2].context_chars


@pytest.mark.parametrize("calls", [6, 12, 20])
def test_verified_findings_form_sections_not_a_flat_two_heading_report(calls):
    findings = [
        ReportFinding("Literal verified overview.", (1,), "overview"),
        ReportFinding("Literal verified mechanism.", (2,), "mechanisms"),
        ReportFinding("Literal verified risk.", (1,), "risks"),
    ]
    report = render_report(report_policy(calls), findings, [("Source", "https://example.test")], 2)
    assert "## Executive summary" in report
    assert "## Methodology" in report
    assert "Literal verified mechanism. [2]" in report
    assert "Literal verified risk. [1]" in report
    assert report.count("Literal verified overview.") == 1
    assert "Evidence-backed findings\n-" not in report


def test_empty_report_is_explicitly_limited_not_padded_with_facts():
    report = render_report(report_policy(20), [], [], 4)
    assert "No factual findings were published" in report
    assert "limited evidence record" in report


def test_passage_selection_finds_relevant_text_beyond_the_first_3500_characters():
    text = (
        "Navigation and boilerplate. " * 250 + "\n\nLedger idempotency prevents duplicate postings."
    )
    selected = select_passages(text, "ledger idempotency", 1200)
    assert "Ledger idempotency prevents duplicate postings." in selected
    assert len(selected) <= 1200


@pytest.mark.parametrize("calls,expected", [(6, 6), (12, 12), (20, 20)])
async def test_real_evidence_bundle_uses_depth_and_late_relevant_passages(
    monkeypatch, calls, expected
):
    content = "Unrelated navigation. " * 250 + "\n\nLedger idempotency prevents duplicate postings."
    read = AsyncMock(return_value=content.encode())
    monkeypatch.setattr(
        builder, "S3ArtifactStore", lambda **_: SimpleNamespace(get_for_verification=read)
    )
    sources = [
        SimpleNamespace(
            id=i,
            content_hash=str(i),
            artifact_ref=str(i),
            title=f"Source {i}",
            canonical_url=f"https://example.test/{i}",
        )
        for i in range(20)
    ]
    materials, context = await builder._read_source_context(
        Settings(), sources=sources, max_search_calls=calls, question="ledger idempotency"
    )
    assert len(materials) == read.await_count == expected
    assert "Ledger idempotency prevents duplicate postings." in context
    assert len(context) <= report_policy(calls).context_chars + 6000
    assert all(material.content == content for material in materials)
