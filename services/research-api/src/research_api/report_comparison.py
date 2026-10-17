"""Bounded literal report comparisons. No model calls or semantic judgments."""

import difflib
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from research_api.schemas.generated.report_comparison import ReportComparison


@dataclass(frozen=True)
class ComparisonInput:
    metadata: dict[str, Any]
    markdown: str
    document: dict[str, Any] | None
    # Source ID -> (canonical URL, preserved content hash), authorized by the caller.
    sources: dict[str, tuple[str, str]]


def _text_key(finding: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(unicodedata.normalize("NFC", finding["text"]).split())
    return finding["section"], text


def _source_evidence(finding: dict[str, Any], report: ComparisonInput) -> set[tuple[str, str]]:
    return {report.sources[source_id] for source_id in finding["sourceIds"]}


def bounded_text_diff(left: str, right: str) -> dict[str, str]:
    # Bound input before allocating line lists and bound the worst pairwise work.
    unavailable = {"status": "size_limit", "unified": ""}
    if len(left) > 128000 or len(right) > 128000:
        return unavailable
    before, after = left.splitlines(), right.splitlines()
    if max(len(before), len(after)) > 2000 or len(before) * len(after) > 1000000:
        return unavailable
    output: list[str] = []
    length = 0
    for line in difflib.unified_diff(
        before, after, fromfile="Earlier report", tofile="Later report", lineterm=""
    ):
        length += len(line) + 1
        if length > 120000:
            return unavailable
        output.append(line)
    return {"status": "available", "unified": "\n".join(output)}


def compare_reports(left: ComparisonInput, right: ComparisonInput) -> ReportComparison:
    """Both snapshots and every referenced source must already be authorized."""
    available = left.document is not None and right.document is not None
    before = left.document["findings"] if available and left.document else []
    after = right.document["findings"] if available and right.document else []
    # Match repeated text one-to-one; section moves remain an explicit removal/addition.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for finding in before:
        groups[_text_key(finding)].append(finding)
    added, retained = [], []
    matched: set[str] = set()
    for finding in after:
        candidates = groups[_text_key(finding)]
        if not candidates:
            added.append(finding)
            continue
        previous = candidates.pop(0)
        matched.add(previous["id"])
        retained.append(
            {
                "leftFindingId": previous["id"],
                "rightFindingId": finding["id"],
                "text": finding["text"],
                "sourceEvidenceChanged": _source_evidence(previous, left)
                != _source_evidence(finding, right),
            }
        )
    removed = [finding for finding in before if finding["id"] not in matched]
    left_urls = {url for url, _ in left.sources.values()}
    right_urls = {url for url, _ in right.sources.values()}
    left_hashes = {hash_ for _, hash_ in left.sources.values()}
    right_hashes = {hash_ for _, hash_ in right.sources.values()}
    limitations = [
        "Findings are matched by section and literal text after whitespace normalization. "
        "Wording changes do not establish agreement or contradiction.",
        "Shared URLs and content hashes show overlap, not independent corroboration. "
        "Source counts include only evidence linked to the selected structured reports.",
    ]
    if not available:
        limitations.append(
            "Finding changes are unavailable because a selected report "
            "has no structured assessment."
        )
    return ReportComparison.model_validate(
        {
            "version": 1,
            "left": left.metadata,
            "right": right.metadata,
            "findingsAvailable": available,
            "added": added,
            "removed": removed,
            "retained": retained,
            "sources": {
                "left": len(left.sources),
                "right": len(right.sources),
                "sharedUrls": len(left_urls & right_urls),
                "sharedContentHashes": len(left_hashes & right_hashes),
            },
            "textDiff": bounded_text_diff(left.markdown, right.markdown),
            "limitations": limitations,
        }
    )
