"""Immutable records and human/reviewer decisions for a standalone review workflow.

Search records are index metadata. A locator URL or abstract is not retrieved
source text and cannot support a full-text eligibility decision.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchFilter(ReviewModel):
    """An exact database filter parameter; key and value are not normalized."""

    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def reject_blank(self) -> SearchFilter:
        if not self.key.strip() or not self.value.strip():
            raise ValueError("filter key and value must not be blank")
        return self


class SearchExecution(ReviewModel):
    """Exact, immutable receipt for one search, separate from observed records.

    reported_result_count is the database's total-hit claim. It can exceed the
    IDs actually returned and must never be used as a PRISMA identified count.
    """

    search_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=10_000)
    executed_at: datetime
    database: str = Field(min_length=1, max_length=200)
    filters: tuple[SearchFilter, ...] = Field(default=(), max_length=50)
    result_record_ids: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(
        max_length=10_000
    )
    reported_result_count: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_receipt(self) -> SearchExecution:
        if not self.search_id.strip() or not self.query.strip() or not self.database.strip():
            raise ValueError("search_id, query and database must not be blank")
        if self.executed_at.tzinfo is None or self.executed_at.utcoffset() is None:
            raise ValueError("executed_at must have a timezone offset")
        keys = [item.key for item in self.filters]
        if len(keys) != len(set(keys)):
            raise ValueError("filter keys must be unique")
        if any(not record_id.strip() for record_id in self.result_record_ids):
            raise ValueError("result_record_ids must not contain blank IDs")
        if len(self.result_record_ids) != len(set(self.result_record_ids)):
            raise ValueError("result_record_ids must be unique")
        if self.reported_result_count is not None and (
            self.reported_result_count < len(self.result_record_ids)
        ):
            raise ValueError("reported_result_count cannot be smaller than returned record IDs")
        return self


class SearchRecord(ReviewModel):
    """One observed result of one search; provider result totals are not records."""

    record_id: str = Field(min_length=1)
    search_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_record_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    abstract: str | None = None
    doi: str | None = None
    locator_url: str | None = None


class ScreeningStage(StrEnum):
    TITLE_ABSTRACT = "title_abstract"
    FULL_TEXT = "full_text"


class ScreeningOutcome(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    MAYBE = "maybe"


class ExclusionReason(StrEnum):
    OUT_OF_SCOPE = "out_of_scope"
    WRONG_POPULATION = "wrong_population"
    WRONG_INTERVENTION = "wrong_intervention"
    WRONG_OUTCOME = "wrong_outcome"
    WRONG_STUDY_DESIGN = "wrong_study_design"
    WRONG_PUBLICATION_TYPE = "wrong_publication_type"
    OUTSIDE_DATE_RANGE = "outside_date_range"
    NON_PRIMARY_SOURCE = "non_primary_source"


class ScreeningDecision(ReviewModel):
    record_id: str = Field(min_length=1)
    stage: ScreeningStage
    outcome: ScreeningOutcome
    exclusion_reason: ExclusionReason | None = None
    # Required for full-text review; must match a retrieved FullTextReceipt.
    source_id: str | None = None

    @model_validator(mode="after")
    def validate_basis(self) -> ScreeningDecision:
        if (self.outcome == ScreeningOutcome.EXCLUDE) != (self.exclusion_reason is not None):
            raise ValueError("exclusion_reason is required exactly for exclude decisions")
        if self.stage == ScreeningStage.FULL_TEXT:
            if not self.source_id:
                raise ValueError("full_text decisions require a retrieved source_id")
        elif self.source_id is not None:
            raise ValueError("title_abstract decisions cannot claim a source_id")
        return self


class RetrievalStatus(StrEnum):
    RETRIEVED = "retrieved"
    NOT_RETRIEVED = "not_retrieved"


class FullTextReceipt(ReviewModel):
    record_id: str = Field(min_length=1)
    status: RetrievalStatus
    # This identifies a source verified/retrieved by the caller, not an index URL.
    source_id: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> FullTextReceipt:
        if self.status == RetrievalStatus.RETRIEVED and not self.source_id:
            raise ValueError("retrieved reports require source_id")
        if self.status == RetrievalStatus.NOT_RETRIEVED and self.source_id is not None:
            raise ValueError("not_retrieved reports cannot claim source_id")
        return self
