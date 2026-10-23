"""Contract tests for review screening and record-flow reconciliation."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from research_api.scholarly.prisma import build_prisma_flow
from research_api.scholarly.screening import (
    ExclusionReason,
    FullTextReceipt,
    RetrievalStatus,
    ScreeningDecision,
    ScreeningOutcome,
    ScreeningStage,
    SearchExecution,
    SearchFilter,
    SearchRecord,
)


def record(number: int) -> SearchRecord:
    return SearchRecord(
        record_id=f"r{number}",
        search_id="query-1",
        provider="openalex",
        provider_record_id=f"W{number}",
        title=f"Study {number}",
        abstract="Index abstract, not retrieved source text",
        locator_url=f"https://example.org/{number}",
    )


def execution(**overrides: object) -> SearchExecution:
    values: dict[str, object] = {
        "search_id": "query-1",
        "query": '"heart failure" AND trial  ',
        "executed_at": datetime(2026, 10, 23, 9, 30, tzinfo=UTC),
        "database": "OpenAlex works",
        "filters": (SearchFilter(key="from_publication_date", value="2020-01-01"),),
        "result_record_ids": ("r1",),
        "reported_result_count": 500,
    }
    values.update(overrides)
    return SearchExecution(**values)


def test_search_execution_preserves_exact_query_and_has_deeply_immutable_filters():
    receipt = execution()
    assert receipt.query == '"heart failure" AND trial  '
    assert receipt.filters[0].value == "2020-01-01"
    assert receipt.model_dump(mode="json")["executed_at"] == "2026-10-23T09:30:00Z"
    with pytest.raises(ValidationError):
        receipt.query = "changed"
    with pytest.raises(ValidationError):
        receipt.filters[0].value = "changed"
    with pytest.raises(TypeError):
        receipt.result_record_ids[0] = "r2"


@pytest.mark.parametrize(
    "overrides",
    [
        {"query": "   "},
        {"database": "   "},
        {"executed_at": datetime(2026, 10, 23, 9, 30)},
        {"result_record_ids": ("r1", "r1")},
        {"result_record_ids": (" ",)},
        {"result_record_ids": ("x" * 201,)},
        {"reported_result_count": -1},
        {"reported_result_count": 0},
        {"reported_result_count": True},
        {
            "filters": (
                SearchFilter(key="year", value="2024"),
                SearchFilter(key="year", value="2025"),
            )
        },
        {"query": "x" * 10_001},
    ],
)
def test_search_execution_rejects_unsafe_or_inconsistent_receipts(overrides):
    with pytest.raises(ValidationError):
        execution(**overrides)


def test_filter_rejects_blank_values_and_execution_can_record_zero_results():
    with pytest.raises(ValidationError):
        SearchFilter(key=" ", value="2024")
    with pytest.raises(ValidationError):
        SearchFilter(key="year", value=" ")
    receipt = execution(result_record_ids=(), reported_result_count=0)
    assert receipt.result_record_ids == ()


def test_provider_reported_total_does_not_inflate_prisma_identified_count():
    receipt = execution(reported_result_count=100_000)
    assert receipt.reported_result_count == 100_000
    assert build_prisma_flow([record(1)]).records_identified == 1


def decision(
    number: int,
    stage: ScreeningStage,
    outcome: ScreeningOutcome,
    reason: ExclusionReason | None = None,
    source_id: str | None = None,
) -> ScreeningDecision:
    return ScreeningDecision(
        record_id=f"r{number}",
        stage=stage,
        outcome=outcome,
        exclusion_reason=reason,
        source_id=source_id,
    )


def test_search_records_are_immutable_and_forbid_unmodeled_claims():
    item = record(1)
    with pytest.raises(ValidationError):
        item.title = "Changed"
    with pytest.raises(ValidationError):
        SearchRecord(**item.model_dump(), full_text="index text")
    assert item.locator_url is not None


@pytest.mark.parametrize(
    ("outcome", "reason", "source_id"),
    [
        (ScreeningOutcome.EXCLUDE, None, None),
        (ScreeningOutcome.INCLUDE, ExclusionReason.OUT_OF_SCOPE, None),
        (ScreeningOutcome.MAYBE, None, "source-1"),
    ],
)
def test_title_decision_rejects_invalid_reason_or_source(outcome, reason, source_id):
    with pytest.raises(ValidationError):
        decision(1, ScreeningStage.TITLE_ABSTRACT, outcome, reason, source_id)


def test_full_text_decision_and_receipt_require_a_retrieved_source():
    with pytest.raises(ValidationError):
        decision(1, ScreeningStage.FULL_TEXT, ScreeningOutcome.INCLUDE)
    with pytest.raises(ValidationError):
        FullTextReceipt(record_id="r1", status=RetrievalStatus.RETRIEVED)
    with pytest.raises(ValidationError):
        FullTextReceipt(
            record_id="r1", status=RetrievalStatus.NOT_RETRIEVED, source_id="source-1"
        )


def test_flow_reconciles_all_terminal_and_pending_states_independent_of_input_order():
    records = [record(number) for number in range(1, 10)]
    decisions = [
        decision(
            2, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.EXCLUDE, ExclusionReason.OUT_OF_SCOPE
        ),
        decision(3, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.MAYBE),
        decision(4, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE),
        decision(5, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE),
        decision(6, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE),
        decision(7, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE),
        decision(8, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE),
        decision(
            6,
            ScreeningStage.FULL_TEXT,
            ScreeningOutcome.EXCLUDE,
            ExclusionReason.WRONG_STUDY_DESIGN,
            "s6",
        ),
        decision(7, ScreeningStage.FULL_TEXT, ScreeningOutcome.MAYBE, source_id="s7"),
        decision(8, ScreeningStage.FULL_TEXT, ScreeningOutcome.INCLUDE, source_id="s8"),
    ]
    receipts = [
        FullTextReceipt(record_id="r5", status=RetrievalStatus.NOT_RETRIEVED),
        FullTextReceipt(record_id="r6", status=RetrievalStatus.RETRIEVED, source_id="s6"),
        FullTextReceipt(record_id="r7", status=RetrievalStatus.RETRIEVED, source_id="s7"),
        FullTextReceipt(record_id="r8", status=RetrievalStatus.RETRIEVED, source_id="s8"),
    ]

    flow = build_prisma_flow(records, decisions, receipts, duplicate_record_ids=["r9"])
    assert flow == build_prisma_flow(
        reversed(records), reversed(decisions), reversed(receipts), duplicate_record_ids=["r9"]
    )
    assert (flow.records_identified, flow.duplicates_removed, flow.records_screened) == (9, 1, 7)
    assert (flow.records_excluded, flow.records_maybe, flow.records_awaiting_screening) == (1, 1, 1)
    assert (flow.reports_sought, flow.reports_retrieved, flow.reports_not_retrieved) == (5, 3, 1)
    assert (flow.reports_awaiting_retrieval, flow.reports_assessed) == (1, 3)
    assert (flow.reports_excluded, flow.reports_maybe, flow.studies_included) == (1, 1, 1)
    assert flow.title_abstract_exclusions == ((ExclusionReason.OUT_OF_SCOPE, 1),)
    assert flow.full_text_exclusions == ((ExclusionReason.WRONG_STUDY_DESIGN, 1),)
    assert flow.records_identified == (
        flow.duplicates_removed + flow.records_screened + flow.records_awaiting_screening
    )
    assert flow.reports_sought == (
        flow.reports_retrieved + flow.reports_not_retrieved + flow.reports_awaiting_retrieval
    )
    assert flow.reports_retrieved == flow.reports_assessed + flow.reports_awaiting_assessment


def test_index_locator_alone_never_counts_as_retrieval_or_inclusion():
    flow = build_prisma_flow(
        [record(1)], [decision(1, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE)]
    )
    assert flow.reports_sought == 1
    assert flow.reports_awaiting_retrieval == 1
    assert flow.reports_retrieved == flow.studies_included == 0


def test_identical_included_pdf_uploads_count_as_one_study_not_two_reports():
    records = [SearchRecord(
        record_id=f"r{number}", search_id=f"upload-{number}", provider="user_pdf_upload",
        provider_record_id="same-sha256", title="Same paper",
    ) for number in (1, 2)]
    decisions = [
        decision(number, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE)
        for number in (1, 2)
    ] + [
        decision(number, ScreeningStage.FULL_TEXT, ScreeningOutcome.INCLUDE,
                 source_id=f"pdf-{number}") for number in (1, 2)
    ]
    receipts = [FullTextReceipt(record_id=f"r{number}", status=RetrievalStatus.RETRIEVED,
                                source_id=f"pdf-{number}") for number in (1, 2)]
    flow = build_prisma_flow(records, decisions, receipts)
    assert flow.records_identified == 2
    assert flow.reports_retrieved == 2
    assert flow.studies_included == 1


@pytest.mark.parametrize(
    ("decisions", "receipts", "duplicates"),
    [
        ([decision(2, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE)], [], []),
        ([decision(1, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE)], [], ["r1"]),
        (
            [],
            [FullTextReceipt(record_id="r1", status=RetrievalStatus.RETRIEVED, source_id="s")],
            [],
        ),
        (
            [decision(1, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.MAYBE)],
            [FullTextReceipt(record_id="r1", status=RetrievalStatus.RETRIEVED, source_id="s")],
            [],
        ),
        (
            [
                decision(1, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE),
                decision(1, ScreeningStage.FULL_TEXT, ScreeningOutcome.INCLUDE, source_id="s"),
            ],
            [],
            [],
        ),
        (
            [
                decision(1, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE),
                decision(1, ScreeningStage.FULL_TEXT, ScreeningOutcome.INCLUDE, source_id="wrong"),
            ],
            [FullTextReceipt(record_id="r1", status=RetrievalStatus.RETRIEVED, source_id="s")],
            [],
        ),
    ],
)
def test_flow_rejects_invalid_transitions(decisions, receipts, duplicates):
    with pytest.raises(ValueError):
        build_prisma_flow([record(1)], decisions, receipts, duplicate_record_ids=duplicates)


def test_flow_rejects_duplicate_records_decisions_and_receipts():
    title = decision(1, ScreeningStage.TITLE_ABSTRACT, ScreeningOutcome.INCLUDE)
    receipt = FullTextReceipt(record_id="r1", status=RetrievalStatus.RETRIEVED, source_id="s")
    with pytest.raises(ValueError, match="duplicate search record"):
        build_prisma_flow([record(1), record(1)])
    with pytest.raises(ValueError, match="multiple title_abstract decisions"):
        build_prisma_flow([record(1)], [title, title])
    with pytest.raises(ValueError, match="multiple retrieval receipts"):
        build_prisma_flow([record(1)], [title], [receipt, receipt])


def test_flow_result_is_immutable():
    flow = build_prisma_flow([record(1)])
    with pytest.raises(FrozenInstanceError):
        flow.records_identified = 2
