from research_api.report_retrieval_snapshot import (
    build_report_retrieval_snapshot,
    retrieval_accounting_markdown,
)


def test_report_snapshot_captures_publication_time_source_lifecycle():
    snapshot = build_report_retrieval_snapshot(
        calls=[
            {
                "provider": "openalex",
                "operation": "search",
                "outcome": "succeeded",
                "provider_usage": {
                    "retrieval": {
                        "discovered": 4,
                        "shortlisted": 2,
                        "excluded": 2,
                        "duplicateWork": 1,
                        "unavailable": 0,
                        "policy": "openalex-screening-v1",
                    }
                },
            }
        ],
        sources=[
            {"id": "source-1", "provider": "openalex"},
            {"id": "source-2", "provider": "openalex"},
        ],
        claim_checks=[
            {
                "publishedInReport": True,
                "citations": [
                    {
                        "sourceId": "source-1",
                        "exactSpanVerified": True,
                        "verdict": "supports",
                    }
                ],
            },
            {
                "publishedInReport": False,
                "citations": [
                    {
                        "sourceId": "source-2",
                        "exactSpanVerified": True,
                        "verdict": "partially_supports",
                    }
                ],
            },
        ],
    )

    provider = snapshot["providers"][0]
    assert provider["discovered"] == 4
    assert provider["shortlisted"] == 2
    assert provider["extractedSources"] == 2
    assert provider["citedInVerifiedFinding"] == 1
    assert snapshot["extractedSources"] == 2
    assert snapshot["citedInVerifiedFinding"] == 1
    assert snapshot["semanticReviewOutcomes"]["partially_supports"] == 1
    assert snapshot["answerUsefulness"] == "not_assessed"
    markdown = retrieval_accounting_markdown(snapshot)
    assert "Retrieval accounting (recorded at publication)" in markdown
    assert "4 discovered; 2 shortlisted; 2 excluded; 2 extracted" in markdown
    assert (
        "Answer usefulness, dimension relevance, and source independence were not assessed."
        in markdown
    )


def test_report_snapshot_does_not_invent_legacy_candidate_counts():
    snapshot = build_report_retrieval_snapshot(
        calls=[
            {
                "provider": "tavily",
                "operation": "search",
                "outcome": "succeeded",
                "provider_usage": {},
            }
        ],
        sources=[],
        claim_checks=[],
    )

    provider = snapshot["providers"][0]
    assert provider["discovered"] is None
    assert provider["shortlisted"] is None
    assert provider["countsComplete"] is False
