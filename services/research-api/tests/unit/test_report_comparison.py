import uuid
from datetime import UTC, datetime

from research_api.report_comparison import ComparisonInput, bounded_text_diff, compare_reports


def snapshot(texts, *, section="comparison", url="https://example.test/a", hash_="a" * 64):
    sources = {}
    findings = []
    for text in texts:
        source = str(uuid.uuid4())
        sources[source] = (url, hash_)
        findings.append(
            {
                "id": str(uuid.uuid4()),
                "text": text,
                "section": section,
                "citationIds": [str(uuid.uuid4())],
                "sourceIds": [source],
            }
        )
    return ComparisonInput(
        metadata={
            "id": str(uuid.uuid4()),
            "runId": str(uuid.uuid4()),
            "version": 1,
            "title": "Question",
            "publishedAt": datetime.now(UTC).isoformat(),
            "quality": "partial",
            "structured": True,
        },
        markdown="\n".join(texts),
        document={"findings": findings},
        sources=sources,
    )


def test_literal_changes_preserve_both_claim_ids_and_compare_source_content():
    left = snapshot(["Retained fact", "Removed fact"])
    right = snapshot(["Retained   fact", "Added fact"], hash_="b" * 64)
    result = compare_reports(left, right)
    assert [item.text for item in result.added] == ["Added fact"]
    assert [item.text for item in result.removed] == ["Removed fact"]
    assert str(result.retained[0].left_finding_id) == left.document["findings"][0]["id"]
    assert str(result.retained[0].right_finding_id) == right.document["findings"][0]["id"]
    assert result.retained[0].source_evidence_changed
    assert result.sources.shared_urls == 1
    assert result.sources.shared_content_hashes == 0
    assert "+Added fact" in result.text_diff.unified


def test_new_run_ids_do_not_imply_source_evidence_changed():
    result = compare_reports(snapshot(["Same"]), snapshot(["Same"]))
    assert not result.retained[0].source_evidence_changed
    assert result.sources.shared_content_hashes == 1


def test_duplicate_text_matches_one_to_one_and_section_changes_remain_visible():
    result = compare_reports(snapshot(["Repeat", "Repeat"]), snapshot(["Repeat"]))
    assert len(result.retained) == 1
    assert len(result.removed) == 1
    moved = compare_reports(snapshot(["Repeat"]), snapshot(["Repeat"], section="risks"))
    assert len(moved.added) == len(moved.removed) == 1
    assert not moved.retained


def test_legacy_comparison_does_not_report_all_findings_as_added():
    left = snapshot([])
    legacy = ComparisonInput(
        metadata={**left.metadata, "structured": False, "quality": "not_assessed"},
        markdown="Historical prose",
        document=None,
        sources={},
    )
    result = compare_reports(legacy, snapshot(["Current fact"]))
    assert not result.findings_available
    assert not result.added and not result.removed
    assert result.left.quality == "not_assessed"
    assert result.text_diff.status == "available"


def test_diff_bounds_inputs_pairwise_work_and_output_without_partial_diff():
    assert bounded_text_diff("same", "same") == {"status": "available", "unified": ""}
    for left, right in (
        ("x" * 128001, "small"),
        ("x\n" * 2001, "small"),
        ("x\n" * 1001, "y\n" * 1001),
        ("a" * 65000, "b" * 65000),
    ):
        assert bounded_text_diff(left, right) == {"status": "size_limit", "unified": ""}
