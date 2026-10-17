"""Pure, conservative coverage assessment and advisory repair admission.

Public entry points: ``assess_coverage(CoverageInput)`` and
``decide_repair(RepairInput)``. Callers allocate/persist all UUIDs and supply an
immutable assessment scope. JSON uses camelCase aliases and UUID strings.

Trust boundary: the caller must resolve source IDs/hashes, verify exact spans
against preserved artifacts, and authenticate independent criterion assessments.
These records validate their integrity, not the truth of caller-supplied verdicts.
Writer nominations and collection provenance cannot certify a criterion. No
result certifies that a research question is answered.

Repair allowances include collection AND subsequent assessment. They are declared
upper bounds, not forecasts or reservations. The integration owner must pin the
evidence fingerprint, atomically persist decisions, reserve against the live
ledger, and enforce these bounds at dispatch. This module reads no clock, calls
no model/database/provider, and never generates IDs.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from pydantic.alias_generators import to_camel

_Text = Annotated[str, Field(min_length=1, max_length=1000, pattern=r"\S")]
_Version = Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
_Count = Annotated[StrictInt, Field(ge=0, le=10**12)]
_Money = Annotated[Decimal, Field(ge=0, le=10**9, max_digits=20, decimal_places=9)]
_Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_IDs = Annotated[tuple[UUID, ...], Field(max_length=40)]
CoverageState = Literal[
    "not_started", "searching", "evidence_found", "verified_covered", "unresolved", "blocked"
]
CriterionOutcome = Literal["met", "partial", "not_met", "unknown"]
ClaimStatus = Literal[
    "supported", "partially_supported", "contradicted", "insufficient_evidence", "not_checked"
]
ResourceLimit = Literal[
    "operations", "sources", "time_ms", "input_tokens", "output_tokens", "cost_usd"
]
RejectionReason = Literal[
    "already_covered",
    "optional_disabled",
    "dimension_already_selected",
    "task_limit",
    "round_task_limit",
    "attempt_limit",
    "attempt_in_flight",
    "no_progress",
    "unchanged_evidence",
    "missing_allowance",
    "invalid_allowance",
    "collection_in_flight",
    "operations",
    "sources",
    "time_ms",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "repair_operations",
    "repair_sources",
    "repair_time_ms",
    "repair_input_tokens",
    "repair_output_tokens",
    "repair_cost_usd",
]


class CoverageModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        alias_generator=to_camel,
        allow_inf_nan=False,
    )


class AssessmentScope(CoverageModel):
    tenant_id: UUID
    run_id: UUID
    plan_id: UUID
    assessment_id: UUID


def _unique(values: Iterable[object], name: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise ValueError(f"Duplicate {name}")


def _same_scope(left: AssessmentScope, right: AssessmentScope) -> None:
    for name in ("tenant_id", "run_id", "plan_id", "assessment_id"):
        if getattr(left, name) != getattr(right, name):
            raise ValueError(f"Mismatched {name}")


class Criterion(CoverageModel):
    id: UUID
    label: _Text
    mandatory: StrictBool = True


class Dimension(CoverageModel):
    id: UUID
    label: _Text
    mandatory: StrictBool = True
    # Smaller numbers have higher priority. UUID order breaks ties.
    priority: Annotated[StrictInt, Field(ge=0, le=100)] = 0
    criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def criteria_integrity(self) -> Self:
        _unique((item.id for item in self.criteria), "criterion IDs")
        if not any(item.mandatory for item in self.criteria):
            raise ValueError("A dimension needs at least one mandatory criterion")
        return self


class CitationEvidence(CoverageModel):
    id: UUID
    source_id: UUID
    exact_span_verified: StrictBool
    semantic_verdict: Literal[
        "supports", "partially_supports", "contradicts", "unrelated", "not_recorded"
    ]
    review_count: Annotated[StrictInt, Field(ge=0, le=100)]


class ClaimEvidence(AssessmentScope):
    id: UUID
    status: ClaimStatus
    # Proposed relevance only, never a criterion assessment.
    dimension_ids: _IDs = ()
    citations: Annotated[tuple[CitationEvidence, ...], Field(max_length=8)] = ()


def _supported(claim: ClaimEvidence) -> bool:
    return (
        claim.status == "supported"
        and bool(claim.citations)
        and all(
            citation.exact_span_verified
            and citation.semantic_verdict == "supports"
            and citation.review_count == 1
            for citation in claim.citations
        )
    )


class CriterionAssessment(AssessmentScope):
    criterion_id: UUID
    dimension_id: UUID
    outcome: CriterionOutcome
    claim_ids: _IDs = ()
    basis: Literal["independent_review", "deterministic_rule"]
    assessor_version: _Version
    reason: _Text


class TaskState(AssessmentScope):
    id: UUID
    dimension_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=32)]
    status: Literal["pending", "running", "complete", "failed", "skipped"]
    source_ids: Annotated[tuple[UUID, ...], Field(max_length=50)] = ()


class MaterialConflict(AssessmentScope):
    id: UUID
    dimension_id: UUID
    criterion_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=16)]
    claim_ids: Annotated[tuple[UUID, ...], Field(min_length=2, max_length=40)]
    unresolved: StrictBool
    basis: Literal["criterion-review-v1"]
    reason: _Text


class CoverageInput(AssessmentScope):
    dimensions: Annotated[tuple[Dimension, ...], Field(max_length=32)]
    source_ids: Annotated[tuple[UUID, ...], Field(max_length=50)] = ()
    claims: Annotated[tuple[ClaimEvidence, ...], Field(max_length=40)] = ()
    criterion_assessments: Annotated[tuple[CriterionAssessment, ...], Field(max_length=512)] = ()
    task_states: Annotated[tuple[TaskState, ...], Field(max_length=128)] = ()
    conflicts: Annotated[tuple[MaterialConflict, ...], Field(max_length=128)] = ()

    @model_validator(mode="after")
    def references(self) -> Self:
        for records, name in (
            (self.dimensions, "dimension"),
            (self.claims, "claim"),
            (self.task_states, "task"),
            (self.conflicts, "conflict"),
        ):
            _unique((record.id for record in records), f"{name} IDs")
        _unique(self.source_ids, "source IDs")
        criteria = {criterion.id: dim.id for dim in self.dimensions for criterion in dim.criteria}
        if len(criteria) != sum(len(dim.criteria) for dim in self.dimensions):
            raise ValueError("Duplicate criterion IDs across dimensions")
        dimensions = {dim.id for dim in self.dimensions}
        sources = set(self.source_ids)
        claims = {claim.id: claim for claim in self.claims}
        assessments_by_criterion = {
            item.criterion_id: set(item.claim_ids) for item in self.criterion_assessments
        }
        _unique(
            (citation.id for claim in self.claims for citation in claim.citations), "citation IDs"
        )
        for claim in self.claims:
            _same_scope(self, claim)
            _unique(claim.dimension_ids, "claim dimension links")
            if not set(claim.dimension_ids) <= dimensions:
                raise ValueError("Unknown claim dimension")
            if any(citation.source_id not in sources for citation in claim.citations):
                raise ValueError("Unknown citation source")
            if claim.status == "supported" and not _supported(claim):
                raise ValueError("Supported claim requires exact, uniquely reviewed support")
        _unique((item.criterion_id for item in self.criterion_assessments), "criterion assessments")
        for item in self.criterion_assessments:
            _same_scope(self, item)
            _unique(item.claim_ids, "assessment claim links")
            if criteria.get(item.criterion_id) != item.dimension_id:
                raise ValueError("Unknown or mismatched assessment criterion")
            if any(
                claim_id not in claims or not _supported(claims[claim_id])
                for claim_id in item.claim_ids
            ):
                raise ValueError("Criterion assessment requires supported claim references")
            if item.outcome in {"met", "partial"} and not item.claim_ids:
                raise ValueError("Met/partial criterion requires supported claims")
        for task in self.task_states:
            _same_scope(self, task)
            _unique(task.dimension_ids, "task dimension links")
            _unique(task.source_ids, "task source links")
            if not set(task.dimension_ids) <= dimensions or not set(task.source_ids) <= sources:
                raise ValueError("Unknown task dimension/source")
        for conflict in self.conflicts:
            _same_scope(self, conflict)
            _unique(conflict.criterion_ids, "conflict criterion links")
            _unique(conflict.claim_ids, "conflict claim links")
            if any(criteria.get(key) != conflict.dimension_id for key in conflict.criterion_ids):
                raise ValueError("Unknown or mismatched conflict criterion")
            if any(
                not set(conflict.claim_ids) <= assessments_by_criterion.get(key, set())
                for key in conflict.criterion_ids
            ):
                raise ValueError("Conflict claims must be linked to a reviewed criterion")
            if not conflict.unresolved:
                raise ValueError("Only unresolved potential conflicts are publishable")
            if any(
                key not in claims
                or not _supported(claims[key])
                or conflict.dimension_id not in claims[key].dimension_ids
                for key in conflict.claim_ids
            ):
                raise ValueError("Conflict claims must be verified and linked to its dimension")
        return self


class CriterionResult(CoverageModel):
    criterion_id: UUID
    mandatory: StrictBool
    outcome: CriterionOutcome
    claim_ids: _IDs
    assessment_basis: Literal["not_assessed", "independent_review", "deterministic_rule"]
    assessor_version: _Version | None
    conflict_ids: Annotated[tuple[UUID, ...], Field(max_length=128)]
    reason: _Text


class DimensionCoverage(CoverageModel):
    dimension_id: UUID
    mandatory: StrictBool
    priority: Annotated[StrictInt, Field(ge=0, le=100)]
    state: CoverageState
    criteria: Annotated[tuple[CriterionResult, ...], Field(min_length=1, max_length=16)]
    verified_claim_ids: _IDs
    source_ids: Annotated[tuple[UUID, ...], Field(max_length=50)]
    reason: _Text


class CoverageResult(AssessmentScope):
    dimensions: Annotated[tuple[DimensionCoverage, ...], Field(max_length=32)]
    conflicts: Annotated[tuple[MaterialConflict, ...], Field(max_length=128)] = ()
    # This quality vocabulary deliberately has no "answered" value.
    quality: Literal["partial", "insufficient_evidence"]


def assess_coverage(inputs: CoverageInput) -> CoverageResult:
    """Assess only validated criterion records; evidence associations alone do not cover."""
    assessments = {item.criterion_id: item for item in inputs.criterion_assessments}
    supported = {claim.id: claim for claim in inputs.claims if _supported(claim)}
    rows = []
    for dim in sorted(inputs.dimensions, key=lambda item: item.id):
        results = []
        relevant = {claim.id for claim in supported.values() if dim.id in claim.dimension_ids}
        for criterion in sorted(dim.criteria, key=lambda item: item.id):
            assessment = assessments.get(criterion.id)
            conflicts = tuple(
                sorted(
                    conflict.id
                    for conflict in inputs.conflicts
                    if conflict.unresolved and criterion.id in conflict.criterion_ids
                )
            )
            linked = tuple(sorted(assessment.claim_ids)) if assessment else ()
            relevant.update(linked)
            results.append(
                CriterionResult(
                    criterion_id=criterion.id,
                    mandatory=criterion.mandatory,
                    outcome=assessment.outcome if assessment else "unknown",
                    claim_ids=linked,
                    assessment_basis=assessment.basis if assessment else "not_assessed",
                    assessor_version=assessment.assessor_version if assessment else None,
                    conflict_ids=conflicts,
                    reason=assessment.reason
                    if assessment
                    else "No independent criterion assessment.",
                )
            )
        required = [result for result in results if result.mandatory]
        tasks = [task for task in inputs.task_states if dim.id in task.dimension_ids]
        sources = {source for task in tasks for source in task.source_ids}
        sources.update(
            citation.source_id for key in relevant for citation in supported[key].citations
        )
        state: CoverageState
        if any(result.conflict_ids for result in required):
            state, reason = "blocked", "Unresolved material conflict affects a mandatory criterion."
        elif all(result.outcome == "met" for result in required):
            state, reason = "verified_covered", "Every mandatory criterion has assessed support."
        elif any(task.status == "running" for task in tasks):
            state, reason = (
                "searching",
                "Collection is running; mandatory coverage is unestablished.",
            )
        elif any(task.status in {"complete", "failed", "skipped"} for task in tasks) or any(
            result.assessment_basis != "not_assessed" for result in results
        ):
            state, reason = (
                "unresolved",
                "Collection/assessment did not establish mandatory coverage.",
            )
        elif sources or relevant:
            state, reason = (
                "evidence_found",
                "Evidence links exist; criterion satisfaction is unassessed.",
            )
        else:
            state, reason = "not_started", "No assessed coverage or collected evidence."
        rows.append(
            DimensionCoverage(
                dimension_id=dim.id,
                mandatory=dim.mandatory,
                priority=dim.priority,
                state=state,
                criteria=tuple(results),
                verified_claim_ids=tuple(sorted(relevant)),
                source_ids=tuple(sorted(sources)),
                reason=reason,
            )
        )
    return CoverageResult(
        **inputs.model_dump(include={"tenant_id", "run_id", "plan_id", "assessment_id"}),
        dimensions=tuple(rows),
        conflicts=inputs.conflicts,
        quality="partial" if supported else "insufficient_evidence",
    )


class ResourceAllowance(CoverageModel):
    operations: _Count = 0
    sources: _Count = 0
    time_ms: _Count = 0
    input_tokens: _Count = 0
    output_tokens: _Count = 0
    cost_usd: _Money = Decimal(0)


_RESOURCE_FIELDS: tuple[ResourceLimit, ...] = (
    "operations",
    "sources",
    "time_ms",
    "input_tokens",
    "output_tokens",
    "cost_usd",
)


def _add(*items: ResourceAllowance) -> ResourceAllowance:
    # Called only after both budgets admit the sum, so public bounds still hold.
    return ResourceAllowance(
        **{key: sum(getattr(item, key) for item in items) for key in _RESOURCE_FIELDS}
    )


class BudgetSnapshot(CoverageModel):
    limits: ResourceAllowance
    used: ResourceAllowance = ResourceAllowance()
    reserved: ResourceAllowance = ResourceAllowance()


class RepairPolicy(CoverageModel):
    max_tasks: Annotated[StrictInt, Field(ge=0, le=128)]
    max_rounds: Annotated[StrictInt, Field(ge=0, le=128)]
    max_tasks_per_round: Annotated[StrictInt, Field(ge=0, le=32)]
    max_attempts_per_dimension: Annotated[StrictInt, Field(ge=0, le=128)]
    max_no_progress_attempts: Annotated[StrictInt, Field(ge=1, le=128)] = 1
    allow_optional: StrictBool = False


class RepairAttempt(CoverageModel):
    id: UUID
    candidate_id: UUID
    dimension_id: UUID
    round_number: Annotated[StrictInt, Field(ge=1, le=128)]
    evidence_fingerprint: _Fingerprint
    status: Literal["pending", "succeeded", "failed", "uncertain", "cancelled"]
    # None means assessment unavailable, NOT zero yield.
    verified_criteria_gained: Annotated[StrictInt, Field(ge=0, le=512)] | None = None

    @model_validator(mode="after")
    def measured_yield(self) -> Self:
        if self.status != "succeeded" and self.verified_criteria_gained is not None:
            raise ValueError("Only assessed successful attempts may report yield")
        return self


class RepairCandidate(CoverageModel):
    id: UUID
    dimension_id: UUID
    query: _Text
    collection_allowance: ResourceAllowance | None = None
    assessment_allowance: ResourceAllowance | None = None


class RepairInput(AssessmentScope):
    coverage: CoverageResult
    evidence_fingerprint: _Fingerprint
    policy: RepairPolicy
    budget: BudgetSnapshot
    repair_budget: BudgetSnapshot
    tasks_used: Annotated[StrictInt, Field(ge=0, le=128)] = 0
    tasks_reserved: Annotated[StrictInt, Field(ge=0, le=128)] = 0
    rounds_used: Annotated[StrictInt, Field(ge=0, le=128)] = 0
    rounds_reserved: Annotated[StrictInt, Field(ge=0, le=128)] = 0
    attempts: Annotated[tuple[RepairAttempt, ...], Field(max_length=128)] = ()
    candidates: Annotated[tuple[RepairCandidate, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def references(self) -> Self:
        _same_scope(self, self.coverage)
        _unique((row.dimension_id for row in self.coverage.dimensions), "coverage dimension IDs")
        _unique((item.id for item in self.attempts), "attempt IDs")
        _unique((item.candidate_id for item in self.attempts), "attempt candidate IDs")
        _unique(
            ((item.dimension_id, item.round_number) for item in self.attempts),
            "dimension/round attempts",
        )
        _unique((item.id for item in self.candidates), "candidate IDs")
        known = {row.dimension_id for row in self.coverage.dimensions}
        if any(item.dimension_id not in known for item in self.attempts) or any(
            item.dimension_id not in known for item in self.candidates
        ):
            raise ValueError("Unknown repair dimension")
        return self


class RepairProposal(CoverageModel):
    candidate_id: UUID
    dimension_id: UUID
    query: _Text
    allowance: ResourceAllowance


class CandidateRejection(CoverageModel):
    candidate_id: UUID
    reasons: Annotated[tuple[RejectionReason, ...], Field(min_length=1, max_length=32)]


class RepairDecision(AssessmentScope):
    evidence_fingerprint: _Fingerprint
    outcome: Literal["propose", "stop"]
    proposals: Annotated[tuple[RepairProposal, ...], Field(max_length=32)]
    allocated: ResourceAllowance
    rejections: Annotated[tuple[CandidateRejection, ...], Field(max_length=32)]
    stop_reason: (
        Literal[
            "no_eligible_gap",
            "task_limit",
            "round_limit",
            "no_candidates",
            "no_admissible_candidate",
        ]
        | None
    )


def _budget_reasons(
    budget: BudgetSnapshot, *proposed: ResourceAllowance, repair: bool = False
) -> list[RejectionReason]:
    # Do not subtract/clamp: an existing overspend blocks admission, including a
    # candidate that declares zero additional use in the overspent unit.
    from typing import cast

    return [
        cast(RejectionReason, f"repair_{key}" if repair else key)
        for key in _RESOURCE_FIELDS
        if getattr(budget.used, key)
        + getattr(budget.reserved, key)
        + sum(getattr(item, key) for item in proposed)
        > getattr(budget.limits, key)
    ]


def decide_repair(inputs: RepairInput) -> RepairDecision:
    """Return stable proposals within both budgets; never reserve or dispatch work."""
    scope = inputs.model_dump(include={"tenant_id", "run_id", "plan_id", "assessment_id"})
    rows = {row.dimension_id: row for row in inputs.coverage.dimensions}
    eligible = {
        key
        for key, row in rows.items()
        if row.state != "verified_covered" and (row.mandatory or inputs.policy.allow_optional)
    }
    tasks = max(inputs.tasks_used + inputs.tasks_reserved, len(inputs.attempts))
    rounds = max(
        inputs.rounds_used + inputs.rounds_reserved,
        max((item.round_number for item in inputs.attempts), default=0),
    )
    stop: (
        Literal[
            "no_eligible_gap",
            "task_limit",
            "round_limit",
            "no_candidates",
            "no_admissible_candidate",
        ]
        | None
    ) = None
    if not eligible:
        stop = "no_eligible_gap"
    elif tasks >= inputs.policy.max_tasks:
        stop = "task_limit"
    elif rounds >= inputs.policy.max_rounds:
        stop = "round_limit"
    elif not inputs.candidates:
        stop = "no_candidates"
    allocated = ResourceAllowance()
    proposals: list[RepairProposal] = []
    rejections = []
    selected = set()
    if stop is None:
        for candidate in sorted(
            inputs.candidates,
            key=lambda item: (
                not rows[item.dimension_id].mandatory,
                rows[item.dimension_id].priority,
                item.dimension_id,
                item.id,
            ),
        ):
            row = rows[candidate.dimension_id]
            history = sorted(
                (item for item in inputs.attempts if item.dimension_id == candidate.dimension_id),
                key=lambda item: (item.round_number, item.id),
            )
            reasons: list[RejectionReason] = []
            if row.state == "verified_covered":
                reasons.append("already_covered")
            if row.state == "searching":
                reasons.append("collection_in_flight")
            if not row.mandatory and not inputs.policy.allow_optional:
                reasons.append("optional_disabled")
            if candidate.dimension_id in selected:
                reasons.append("dimension_already_selected")
            if tasks + len(proposals) >= inputs.policy.max_tasks:
                reasons.append("task_limit")
            if len(proposals) >= inputs.policy.max_tasks_per_round:
                reasons.append("round_task_limit")
            if len(history) >= inputs.policy.max_attempts_per_dimension:
                reasons.append("attempt_limit")
            if any(item.status in {"pending", "uncertain"} for item in history):
                reasons.append("attempt_in_flight")
            if any(item.candidate_id == candidate.id for item in inputs.attempts) or any(
                item.evidence_fingerprint == inputs.evidence_fingerprint for item in history
            ):
                reasons.append("unchanged_evidence")
            no_progress = 0
            for item in reversed(history):
                if item.status != "succeeded" or item.verified_criteria_gained != 0:
                    break
                no_progress += 1
            if no_progress >= inputs.policy.max_no_progress_attempts:
                reasons.append("no_progress")
            collection, assessment = candidate.collection_allowance, candidate.assessment_allowance
            allowance = None
            if collection is None or assessment is None:
                reasons.append("missing_allowance")
            elif (
                collection.operations < 1
                or collection.time_ms < 1
                or assessment.time_ms < 1
                or assessment.input_tokens < 1
                or assessment.output_tokens < 1
            ):
                reasons.append("invalid_allowance")
            else:
                reasons.extend(_budget_reasons(inputs.budget, allocated, collection, assessment))
                reasons.extend(
                    _budget_reasons(
                        inputs.repair_budget, allocated, collection, assessment, repair=True
                    )
                )
                if not reasons:
                    allowance = _add(collection, assessment)
            if reasons:
                rejections.append(
                    CandidateRejection(candidate_id=candidate.id, reasons=tuple(reasons))
                )
            elif allowance is not None:
                proposals.append(
                    RepairProposal(
                        candidate_id=candidate.id,
                        dimension_id=candidate.dimension_id,
                        query=candidate.query,
                        allowance=allowance,
                    )
                )
                allocated = _add(allocated, allowance)
                selected.add(candidate.dimension_id)
        if not proposals:
            stop = "no_admissible_candidate"
    return RepairDecision(
        **scope,
        evidence_fingerprint=inputs.evidence_fingerprint,
        outcome="propose" if proposals else "stop",
        proposals=tuple(proposals),
        allocated=allocated,
        rejections=tuple(rejections),
        stop_reason=stop,
    )
