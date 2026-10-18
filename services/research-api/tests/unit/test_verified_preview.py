from uuid import uuid4

from research_api.verified_preview import verified_preview


def test_only_checked_bounded_findings_are_projected():
    source_id = str(uuid4())
    payload = {
        "verifiedClaimCount": 6,
        "findings": [{"text": "A supported statement.", "sourceIds": [source_id]}],
        "privatePrompt": "never expose this",
    }
    assert verified_preview("assessment.findings_verified", payload) == {
        "verifiedFindings": [{"text": "A supported statement.", "sourceIds": [source_id]}],
        "verifiedClaimCount": 6,
    }
    assert verified_preview("node.progress", payload) is None


def test_invalid_or_oversized_preview_is_withheld():
    source_id = str(uuid4())
    assert (
        verified_preview(
            "assessment.findings_verified",
            {"verifiedClaimCount": 1, "findings": [{"text": "x", "sourceIds": ["bad"]}]},
        )
        is None
    )
    assert (
        verified_preview(
            "assessment.findings_verified",
            {"verifiedClaimCount": 1, "findings": [{"text": "x" * 1201, "sourceIds": [source_id]}]},
        )
        is None
    )
    assert (
        verified_preview(
            "assessment.findings_verified",
            {"verifiedClaimCount": 4, "findings": [{"text": "x", "sourceIds": [source_id]}] * 4},
        )
        is None
    )
