"""Deterministic, local record flow for a dedicated review workflow.

The result is a process count, not a claim of PRISMA 2020 compliance. Search
engine total hits, candidate ranking and index metadata are never full-text
assessment or included-study evidence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from research_api.scholarly.screening import (
    ExclusionReason,
    FullTextReceipt,
    RetrievalStatus,
    ScreeningDecision,
    ScreeningOutcome,
    ScreeningStage,
    SearchRecord,
)


@dataclass(frozen=True, slots=True)
class PrismaFlow:
    records_identified: int
    duplicates_removed: int
    records_screened: int
    records_excluded: int
    records_maybe: int
    records_awaiting_screening: int
    reports_sought: int
    reports_retrieved: int
    reports_not_retrieved: int
    reports_awaiting_retrieval: int
    reports_assessed: int
    reports_excluded: int
    reports_maybe: int
    reports_awaiting_assessment: int
    studies_included: int
    title_abstract_exclusions: tuple[tuple[ExclusionReason, int], ...]
    full_text_exclusions: tuple[tuple[ExclusionReason, int], ...]


def _reason_counts(counts: Counter[ExclusionReason]) -> tuple[tuple[ExclusionReason, int], ...]:
    return tuple(sorted(counts.items(), key=lambda item: item[0].value))


def build_prisma_flow(
    records: Iterable[SearchRecord],
    decisions: Iterable[ScreeningDecision] = (),
    retrievals: Iterable[FullTextReceipt] = (),
    *,
    duplicate_record_ids: Iterable[str] = (),
) -> PrismaFlow:
    """Count observed records and explicit transitions, including unresolved work.

    Duplicate removal is explicit: matching titles/DOIs alone do not prove a
    duplicate. Each record is one search occurrence, so multiple occurrences
    of a study must be explicitly deduplicated by the review workflow.
    """
    records_by_id: dict[str, SearchRecord] = {}
    for record in records:
        if record.record_id in records_by_id:
            raise ValueError(f"duplicate search record for record_id {record.record_id!r}")
        records_by_id[record.record_id] = record
    duplicates = set(duplicate_record_ids)
    if not duplicates <= records_by_id.keys():
        raise ValueError("duplicate_record_ids contain an unknown record")

    decisions_by_key: dict[tuple[str, ScreeningStage], ScreeningDecision] = {}
    for decision in decisions:
        key = (decision.record_id, decision.stage)
        if key in decisions_by_key:
            raise ValueError(f"multiple {decision.stage} decisions for {decision.record_id!r}")
        if decision.record_id not in records_by_id or decision.record_id in duplicates:
            raise ValueError("decision refers to an unknown or duplicate record")
        decisions_by_key[key] = decision

    receipts: dict[str, FullTextReceipt] = {}
    for retrieval in retrievals:
        if retrieval.record_id in receipts:
            raise ValueError(f"multiple retrieval receipts for {retrieval.record_id!r}")
        if retrieval.record_id not in records_by_id or retrieval.record_id in duplicates:
            raise ValueError("retrieval refers to an unknown or duplicate record")
        receipts[retrieval.record_id] = retrieval

    screened = title_excluded = title_maybe = awaiting_screening = 0
    sought = retrieved = not_retrieved = awaiting_retrieval = 0
    assessed = full_excluded = full_maybe = awaiting_assessment = included = 0
    title_reasons: Counter[ExclusionReason] = Counter()
    full_reasons: Counter[ExclusionReason] = Counter()

    for record_id in sorted(records_by_id.keys() - duplicates):
        title = decisions_by_key.get((record_id, ScreeningStage.TITLE_ABSTRACT))
        full = decisions_by_key.get((record_id, ScreeningStage.FULL_TEXT))
        receipt = receipts.get(record_id)
        if title is None:
            if full or receipt:
                raise ValueError("full-text activity requires title_abstract inclusion")
            awaiting_screening += 1
            continue
        screened += 1
        if title.outcome == ScreeningOutcome.EXCLUDE:
            if full or receipt:
                raise ValueError("excluded record cannot proceed to retrieval")
            title_excluded += 1
            if title.exclusion_reason is None:
                raise ValueError("excluded record requires a reason")
            title_reasons[title.exclusion_reason] += 1
            continue
        if title.outcome == ScreeningOutcome.MAYBE:
            if full or receipt:
                raise ValueError("maybe record cannot proceed to retrieval")
            title_maybe += 1
            continue

        sought += 1
        if receipt is None:
            if full:
                raise ValueError("full-text decision requires a retrieval receipt")
            awaiting_retrieval += 1
            continue
        if receipt.status == RetrievalStatus.NOT_RETRIEVED:
            if full:
                raise ValueError("not_retrieved report cannot be assessed")
            not_retrieved += 1
            continue
        retrieved += 1
        if full is None:
            awaiting_assessment += 1
            continue
        if full.source_id != receipt.source_id:
            raise ValueError("full-text decision source_id differs from retrieval receipt")
        assessed += 1
        if full.outcome == ScreeningOutcome.EXCLUDE:
            full_excluded += 1
            if full.exclusion_reason is None:
                raise ValueError("excluded report requires a reason")
            full_reasons[full.exclusion_reason] += 1
        elif full.outcome == ScreeningOutcome.MAYBE:
            full_maybe += 1
        else:
            included += 1

    return PrismaFlow(
        records_identified=len(records_by_id),
        duplicates_removed=len(duplicates),
        records_screened=screened,
        records_excluded=title_excluded,
        records_maybe=title_maybe,
        records_awaiting_screening=awaiting_screening,
        reports_sought=sought,
        reports_retrieved=retrieved,
        reports_not_retrieved=not_retrieved,
        reports_awaiting_retrieval=awaiting_retrieval,
        reports_assessed=assessed,
        reports_excluded=full_excluded,
        reports_maybe=full_maybe,
        reports_awaiting_assessment=awaiting_assessment,
        studies_included=included,
        title_abstract_exclusions=_reason_counts(title_reasons),
        full_text_exclusions=_reason_counts(full_reasons),
    )
