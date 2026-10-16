from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.config import Settings
from research_api.graph import builder
from research_api.reports import (
    ReportFigure,
    ReportFinding,
    render_report,
    report_policy,
    select_passages,
    verified_figures,
)


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


@pytest.mark.parametrize("calls", [6, 12, 20])
def test_empty_report_is_explicitly_limited_not_padded_with_facts(calls):
    report = render_report(report_policy(calls), [], SOURCES, 4)
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Research finished—answer not established",
        "## Limitations",
        "## Sources",
    ]
    assert "No findings passed the evidence checks" in report
    assert "4 candidate assertions were excluded" in report
    assert "https://a.test" in report
    assert "published share" not in report


def test_empty_report_without_sources_has_no_empty_source_section():
    report = render_report(report_policy(6), [], [], 0)
    assert "Reviewed 0 source extracts" in report
    assert "## Sources" not in report


def test_populated_report_omits_empty_analysis_sections():
    report = render_report(
        report_policy(12),
        [ReportFinding("Summary.", (1,), "overview"), ReportFinding("Risk.", (2,), "risks")],
        SOURCES,
        0,
    )
    assert "## Executive summary" in report
    assert "## Risks and operational trade-offs" in report
    assert "## Comparative analysis" not in report
    assert "## How the approaches work" not in report
    assert "This section is incomplete" not in report


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


def _figure(subject, metric, value, citation_index=0):
    return SimpleNamespace(
        subject=subject, metric=metric, value=value, citation_index=citation_index
    )


QUOTE = "Model A reached 47.2% accuracy, while the 2019 baseline scored 14.5%."
CLAIM = "Model A reached 47.2% accuracy."


def test_figures_are_published_only_when_literally_present_in_the_verified_evidence():
    cites = [(3, QUOTE)]
    kept = verified_figures(CLAIM, [_figure("Model A", "accuracy", "47.2%")], cites)
    assert kept == (ReportFigure("Model A", "accuracy", "47.2%", 3),)
    rejected = [
        _figure("Model A", "accuracy", "48%"),  # not in the quote
        _figure("Model A", "accuracy", "4.5%"),  # only inside 14.5%
        _figure("Model A", "accuracy", "47.2"),  # drops the percent sign
        _figure("Model A", "accuracy", "47"),  # stops before the decimal part
        _figure("Model A", "accuracy", "14.5%"),  # not stated by the claim
        _figure("Model B", "accuracy", "47.2%"),  # subject absent from the evidence
        _figure("Model A", "latency", "47.2%"),  # metric absent from the evidence
        _figure("Model A", "accuracy", "47.2%", 1),  # citation does not exist
        _figure("Model A", "accuracy", "accurate"),  # not a number
    ]
    assert verified_figures(CLAIM, rejected, cites) == ()
    duplicate = [_figure("Model A", "accuracy", "47.2%")] * 2
    assert len(verified_figures(CLAIM, duplicate, cites)) == 1


def _finding(subject, value, source, metric="accuracy", section="comparison"):
    figure = ReportFigure(subject, metric, value, source)
    return ReportFinding(f"{subject} reached {value} {metric}.", (source,), section, (figure,))


SOURCES = [("Paper | one", "https://a.test"), ("Two [x]", "https://b.test"), ("C", "https://c")]


def test_figure_tables_group_one_metric_each_and_escape_markdown():
    findings = [
        _finding("Model A", "47.2%", 1),
        _finding("Model *B*", "51%", 2),
        _finding("Model A", "120 ms", 1, metric="latency"),  # single row: no table
    ]
    report = render_report(report_policy(6), findings, SOURCES, 0)
    assert "## Key figures" in report
    assert "### Accuracy\n\n| Subject | Accuracy | Source |" in report
    assert "| Model A | 47.2% | [1] |" in report
    assert "| Model \\*B\\* | 51% | [2] |" in report
    assert "### Latency" not in report


def test_figure_tables_are_capped_per_mode():
    findings = [
        _finding(name, f"{rank}%", 1 + rank % 2, metric=f"metric {metric}")
        for metric in range(8)
        for rank, name in enumerate(("Alpha", "Beta"), 1)
    ]
    for calls, cap in ((6, 2), (12, 4), (20, 6)):
        assert render_report(report_policy(calls), findings, SOURCES, 0).count("### ") == cap


def test_no_figures_means_no_key_figures_section():
    report = render_report(report_policy(20), [ReportFinding("Plain.", (1,))], SOURCES, 0)
    assert "## Key figures" not in report


def test_source_table_is_deterministic_and_depth_dependent():
    findings = [
        ReportFinding("Overview.", (1,), "overview"),
        ReportFinding("Shared comparison.", (2, 1), "comparison"),
        ReportFinding("Risk.", (2,), "risks"),
    ]
    focused = render_report(report_policy(6), findings, SOURCES, 1)
    assert "## Evidence by source" not in focused
    assert "## Evidence coverage" not in focused
    balanced = render_report(report_policy(12), findings, SOURCES, 1)
    assert "| Source | Findings | Shared findings | Sections |" in balanced
    assert "| Paper \\| one [1] | 2 | 1 | Executive summary; Comparative analysis |" in balanced
    assert (
        "| Two \\[x\\] [2] | 2 | 1 | Comparative analysis; Risks and operational trade-offs |"
        in balanced
    )
    assert "| C [3]" not in balanced  # collected but not cited by a published finding
    assert "## Evidence coverage" not in balanced
    deep = render_report(report_policy(20), findings, SOURCES, 1)
    assert "| Executive summary | 1 | 1 |" in deep
    assert "| Cross-source comparative analysis | 1 | 2 |" in deep
    assert "| Detailed mechanisms and architecture | 0 | 0 |" in deep


def test_single_cited_source_has_no_comparison_table():
    report = render_report(report_policy(12), [ReportFinding("Only.", (1,))], SOURCES, 0)
    assert "## Evidence by source" not in report


@pytest.mark.parametrize("calls", [6, 12, 20])
def test_reports_keep_evidence_counts_without_publication_share_formula(calls):
    findings = [ReportFinding("One.", (1,)), ReportFinding("Two.", (2,))]
    report = render_report(report_policy(calls), findings, SOURCES, 1)
    assert "published 2 verified findings" in report
    assert "1 candidate assertions were excluded" in report
    assert "published share" not in report
    assert "$$" not in report


@pytest.mark.parametrize("calls", [6, 12, 20])
def test_limitations_and_sources_keep_their_place(calls):
    findings = [_finding("Model A", "47.2%", 1), _finding("Model B", "51%", 2)]
    report = render_report(report_policy(calls), findings, SOURCES, 2)
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings[-3:] == ["## Limitations", "## Methodology", "## Sources"]
    assert "## Limitations\n" in report
