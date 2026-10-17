"""Coverage and repair policy only: no fixtures connect to infrastructure/providers."""

from decimal import Decimal
from itertools import permutations
from uuid import UUID

import pytest
from pydantic import ValidationError

from research_api.coverage import (
    BudgetSnapshot,
    CitationEvidence,
    ClaimEvidence,
    CoverageInput,
    Criterion,
    CriterionAssessment,
    Dimension,
    MaterialConflict,
    RepairAttempt,
    RepairCandidate,
    RepairInput,
    RepairPolicy,
    ResourceAllowance,
    TaskState,
    assess_coverage,
    decide_repair,
)


def uid(number):
    return UUID(int=number)


SCOPE = dict(tenant_id=uid(1), run_id=uid(2), plan_id=uid(3), assessment_id=uid(4))
SOURCE = uid(5)
FINGERPRINT = "a" * 64
OLD_FINGERPRINT = "b" * 64


def dimension(number=10, **overrides):
    return Dimension(
        **dict(
            id=uid(number),
            label=f"Dimension {number}",
            criteria=(Criterion(id=uid(number + 100), label="Mandatory criterion"),),
        )
        | overrides
    )


def claim(number=20, **overrides):
    return ClaimEvidence(
        **dict(
            **SCOPE,
            id=uid(number),
            status="supported",
            dimension_ids=(uid(10),),
            citations=(
                CitationEvidence(
                    id=uid(number + 1000),
                    source_id=SOURCE,
                    exact_span_verified=True,
                    semantic_verdict="supports",
                    review_count=1,
                ),
            ),
        )
        | overrides
    )


def assessment(**overrides):
    return CriterionAssessment(
        **dict(
            **SCOPE,
            criterion_id=uid(110),
            dimension_id=uid(10),
            outcome="met",
            claim_ids=(uid(20),),
            basis="independent_review",
            assessor_version="criterion-review-v1",
            reason="Independently assessed mandatory criterion against supported findings.",
        )
        | overrides
    )


def coverage_input(**overrides):
    return CoverageInput(
        **dict(**SCOPE, dimensions=(dimension(),), source_ids=(SOURCE,)) | overrides
    )


def allowance(**overrides):
    return ResourceAllowance(
        **dict(
            operations=2,
            sources=1,
            time_ms=100,
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0.01"),
        )
        | overrides
    )


def candidate(number=30, **overrides):
    return RepairCandidate(
        **dict(
            id=uid(number),
            dimension_id=uid(10),
            query="Find exact primary evidence.",
            collection_allowance=allowance(input_tokens=0, output_tokens=0),
            assessment_allowance=allowance(operations=0, sources=0),
        )
        | overrides
    )


def repair_input(**overrides):
    limits = allowance(
        operations=20,
        sources=10,
        time_ms=1000,
        input_tokens=100,
        output_tokens=50,
        cost_usd=Decimal("0.10"),
    )
    return RepairInput(
        **dict(
            **SCOPE,
            coverage=assess_coverage(coverage_input()),
            evidence_fingerprint=FINGERPRINT,
            policy=RepairPolicy(
                max_tasks=4, max_rounds=4, max_tasks_per_round=4, max_attempts_per_dimension=4
            ),
            budget=BudgetSnapshot(limits=limits),
            repair_budget=BudgetSnapshot(limits=limits),
            candidates=(candidate(),),
        )
        | overrides
    )


def attempt(number=40, **overrides):
    return RepairAttempt(
        **dict(
            id=uid(number),
            candidate_id=uid(number + 100),
            dimension_id=uid(10),
            round_number=1,
            evidence_fingerprint=OLD_FINGERPRINT,
            status="succeeded",
            verified_criteria_gained=1,
        )
        | overrides
    )


def test_only_independently_assessed_mandatory_criteria_establish_coverage():
    extra = Criterion(id=uid(111), label="Second mandatory criterion")
    dim = dimension(criteria=(dimension().criteria[0], extra))
    source = coverage_input(dimensions=(dim,), claims=(claim(),))
    assert assess_coverage(source).dimensions[0].state == "evidence_found"
    one = coverage_input(
        dimensions=(dim,), claims=(claim(),), criterion_assessments=(assessment(),)
    )
    assert assess_coverage(one).dimensions[0].state == "unresolved"
    both = coverage_input(
        dimensions=(dim,),
        claims=(claim(),),
        criterion_assessments=(
            assessment(),
            assessment(criterion_id=uid(111), basis="deterministic_rule"),
        ),
    )
    result = assess_coverage(both)
    assert result.dimensions[0].state == "verified_covered"
    assert result.dimensions[0].verified_claim_ids == (uid(20),)
    assert result.dimensions[0].source_ids == (SOURCE,)
    assert result.quality == "partial"


@pytest.mark.parametrize("outcome", ["partial", "not_met", "unknown"])
def test_non_met_criterion_never_establishes_coverage(outcome):
    result = assess_coverage(
        coverage_input(
            claims=(claim(),),
            criterion_assessments=(assessment(outcome=outcome),),
        )
    )
    assert result.dimensions[0].state == "unresolved"


@pytest.mark.parametrize(
    "status,expected",
    [
        ("pending", "not_started"),
        ("running", "searching"),
        ("complete", "unresolved"),
        ("failed", "unresolved"),
        ("skipped", "unresolved"),
    ],
)
def test_collection_execution_is_not_criterion_satisfaction(status, expected):
    task = TaskState(**SCOPE, id=uid(50), dimension_ids=(uid(10),), status=status)
    assert assess_coverage(coverage_input(task_states=(task,))).dimensions[0].state == expected


def test_provenance_and_model_nominations_do_not_establish_coverage():
    task = TaskState(
        **SCOPE, id=uid(50), dimension_ids=(uid(10),), status="pending", source_ids=(SOURCE,)
    )
    result = assess_coverage(coverage_input(claims=(claim(),), task_states=(task,)))
    row = result.dimensions[0]
    assert row.state == "evidence_found"
    assert row.criteria[0].outcome == "unknown"
    assert row.criteria[0].assessment_basis == "not_assessed"
    assert row.source_ids == (SOURCE,)


@pytest.mark.parametrize(
    "changes",
    [
        dict(exact_span_verified=False),
        dict(semantic_verdict="partially_supports"),
        dict(semantic_verdict="contradicts"),
        dict(semantic_verdict="unrelated"),
        dict(semantic_verdict="not_recorded"),
        dict(review_count=0),
        dict(review_count=2),
    ],
)
def test_supported_flag_cannot_override_citation_gate(changes):
    citation = claim().citations[0].model_dump() | changes
    with pytest.raises(ValidationError, match="exact, uniquely reviewed"):
        coverage_input(claims=(claim(citations=(CitationEvidence(**citation),)),))


@pytest.mark.parametrize(
    "status",
    [
        "partially_supported",
        "contradicted",
        "insufficient_evidence",
        "not_checked",
    ],
)
def test_rejected_claims_cannot_back_criterion_assessments(status):
    rejected = claim(status=status)
    result = assess_coverage(coverage_input(claims=(rejected,)))
    assert result.quality == "insufficient_evidence"
    assert result.dimensions[0].verified_claim_ids == ()
    with pytest.raises(ValidationError, match="supported claim references"):
        coverage_input(claims=(rejected,), criterion_assessments=(assessment(),))


@pytest.mark.parametrize("outcome", ["met", "partial"])
def test_establishment_without_claims_is_rejected(outcome):
    with pytest.raises(ValidationError, match="requires supported claims"):
        coverage_input(criterion_assessments=(assessment(outcome=outcome, claim_ids=()),))


def test_optional_criterion_cannot_hide_missing_mandatory_criterion():
    dim = dimension(
        criteria=(
            dimension().criteria[0],
            Criterion(id=uid(111), label="Optional", mandatory=False),
        )
    )
    inputs = coverage_input(
        dimensions=(dim,),
        claims=(claim(),),
        criterion_assessments=(assessment(criterion_id=uid(111)),),
    )
    assert assess_coverage(inputs).dimensions[0].state == "unresolved"
    inputs = coverage_input(
        dimensions=(dim,), claims=(claim(),), criterion_assessments=(assessment(),)
    )
    assert assess_coverage(inputs).dimensions[0].state == "verified_covered"


@pytest.mark.parametrize("unresolved,expected", [(True, "blocked"), (False, "verified_covered")])
def test_material_conflict_blocks_mandatory_coverage(unresolved, expected):
    conflict = MaterialConflict(
        **SCOPE,
        id=uid(60),
        dimension_id=uid(10),
        criterion_ids=(uid(110),),
        claim_ids=(uid(20), uid(21)),
        unresolved=unresolved,
        basis="criterion-review-v1",
        reason="Independent assessment found material conflict.",
    )
    result = assess_coverage(
        coverage_input(
            claims=(claim(), claim(21)),
            criterion_assessments=(assessment(claim_ids=(uid(20), uid(21))),),
            conflicts=(conflict,) if unresolved else (),
        )
    )
    assert result.dimensions[0].state == expected
    assert bool(result.dimensions[0].criteria[0].conflict_ids) is unresolved


@pytest.mark.parametrize("record", ["claim", "assessment", "task", "conflict"])
@pytest.mark.parametrize("field", ["tenant_id", "run_id", "plan_id", "assessment_id"])
def test_foreign_or_stale_records_fail_closed(record, field):
    fields = {field: uid(999)}
    if record == "claim":
        overrides = dict(claims=(claim(**fields),))
    elif record == "assessment":
        overrides = dict(claims=(claim(),), criterion_assessments=(assessment(**fields),))
    elif record == "task":
        overrides = dict(
            task_states=(
                TaskState(
                    **(SCOPE | fields), id=uid(50), dimension_ids=(uid(10),), status="pending"
                ),
            )
        )
    else:
        overrides = dict(
            claims=(claim(), claim(21)),
            conflicts=(
                MaterialConflict(
                    **(SCOPE | fields),
                    id=uid(60),
                    dimension_id=uid(10),
                    criterion_ids=(uid(110),),
                    claim_ids=(uid(20), uid(21)),
                    unresolved=True,
                    basis="criterion-review-v1",
                    reason="Conflict",
                ),
            ),
        )
    with pytest.raises(ValidationError, match="Mismatched"):
        coverage_input(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        dict(dimensions=(dimension(), dimension())),
        dict(claims=(claim(), claim())),
        dict(source_ids=(SOURCE, SOURCE)),
        dict(claims=(claim(dimension_ids=(uid(999),)),)),
        dict(claims=(claim(),), source_ids=()),
        dict(criterion_assessments=(assessment(),)),
        dict(claims=(claim(),), criterion_assessments=(assessment(criterion_id=uid(999)),)),
        dict(claims=(claim(),), criterion_assessments=(assessment(), assessment())),
        dict(claims=(claim(),), criterion_assessments=(assessment(claim_ids=(uid(20), uid(20))),)),
        dict(claims=(claim(citations=()),)),
        dict(dimensions=(dimension(), dimension(11, criteria=dimension().criteria))),
    ],
)
def test_ambiguous_or_dangling_identity_rejected(overrides):
    with pytest.raises(ValidationError):
        coverage_input(**overrides)


def test_empty_plan_is_honest_and_never_answered():
    result = assess_coverage(coverage_input(dimensions=()))
    assert result.dimensions == () and result.quality == "insufficient_evidence"
    assert (
        decide_repair(repair_input(coverage=result, candidates=())).stop_reason == "no_eligible_gap"
    )
    with pytest.raises(ValidationError):
        type(result).model_validate(result.model_dump() | {"quality": "answered"})


def test_json_aliases_uuid_roundtrip_immutable_and_extra_fields_forbidden():
    inputs = coverage_input(claims=(claim(),), criterion_assessments=(assessment(),))
    result = assess_coverage(inputs)
    encoded = result.model_dump(mode="json", by_alias=True)
    assert encoded["runId"] == str(SCOPE["run_id"])
    assert encoded["dimensions"][0]["criteria"][0]["criterionId"] == str(uid(110))
    assert CoverageInput.model_validate_json(inputs.model_dump_json(by_alias=True)) == inputs
    assert type(result).model_validate(encoded) == result
    with pytest.raises(ValidationError):
        result.quality = "insufficient_evidence"
    with pytest.raises(ValidationError):
        CoverageInput.model_validate(inputs.model_dump() | {"answered": True})


def test_coverage_is_independent_of_input_iteration_order():
    dims = (dimension(), dimension(11))
    claims = (claim(), claim(21, dimension_ids=(uid(11),)))
    reviews = (
        assessment(),
        assessment(criterion_id=uid(111), dimension_id=uid(11), claim_ids=(uid(21),)),
    )
    baseline = assess_coverage(
        coverage_input(dimensions=dims, claims=claims, criterion_assessments=reviews)
    )
    for dim_order in permutations(dims):
        for claim_order in permutations(claims):
            for review_order in permutations(reviews):
                assert (
                    assess_coverage(
                        coverage_input(
                            dimensions=dim_order,
                            claims=claim_order,
                            criterion_assessments=review_order,
                        )
                    )
                    == baseline
                )


def test_repair_proposes_collection_plus_assessment_without_mutating_inputs():
    inputs = repair_input()
    before = inputs.model_dump_json()
    result = decide_repair(inputs)
    assert result.outcome == "propose" and result.stop_reason is None
    assert result.proposals[0].candidate_id == uid(30)
    assert result.allocated == allowance(time_ms=200, cost_usd=Decimal("0.02"))
    assert inputs.model_dump_json() == before
    assert decide_repair(inputs) == result
    assert type(result).model_validate_json(result.model_dump_json(by_alias=True)) == result


@pytest.mark.parametrize("budget_name,prefix", [("budget", ""), ("repair_budget", "repair_")])
@pytest.mark.parametrize(
    "unit,needed",
    [
        ("operations", 2),
        ("sources", 1),
        ("time_ms", 200),
        ("input_tokens", 10),
        ("output_tokens", 5),
        ("cost_usd", Decimal("0.02")),
    ],
)
def test_all_resource_caps_include_used_reserved_and_exact_boundary(
    budget_name, prefix, unit, needed
):
    inputs = repair_input()
    old = getattr(inputs, budget_name)
    delta = Decimal("0.000000001") if unit == "cost_usd" else 1
    limits = old.limits.model_dump() | {unit: needed + delta + delta}
    usage = ResourceAllowance(**{unit: delta})
    exact = BudgetSnapshot(limits=ResourceAllowance(**limits), used=usage, reserved=usage)
    accepted = repair_input(**{budget_name: exact})
    assert decide_repair(accepted).outcome == "propose"
    exceeded = BudgetSnapshot(
        limits=ResourceAllowance(**(limits | {unit: needed + delta})),
        used=usage,
        reserved=usage,
    )
    result = decide_repair(repair_input(**{budget_name: exceeded}))
    assert result.outcome == "stop"
    assert result.rejections[0].reasons == (prefix + unit,)


def test_existing_overspend_is_not_clamped_away():
    limits = repair_input().budget.limits
    budget = BudgetSnapshot(limits=limits, used=ResourceAllowance(operations=21))
    result = decide_repair(repair_input(budget=budget))
    assert result.outcome == "stop" and "operations" in result.rejections[0].reasons


@pytest.mark.parametrize(
    "overrides,reason",
    [
        (dict(collection_allowance=None), "missing_allowance"),
        (dict(assessment_allowance=None), "missing_allowance"),
        (dict(collection_allowance=allowance(operations=0)), "invalid_allowance"),
        (dict(collection_allowance=allowance(time_ms=0)), "invalid_allowance"),
        (dict(assessment_allowance=allowance(time_ms=0)), "invalid_allowance"),
        (dict(assessment_allowance=allowance(input_tokens=0)), "invalid_allowance"),
        (dict(assessment_allowance=allowance(output_tokens=0)), "invalid_allowance"),
    ],
)
def test_unknown_or_incomplete_allowances_are_ineligible(overrides, reason):
    result = decide_repair(repair_input(candidates=(candidate(**overrides),)))
    assert result.outcome == "stop" and result.rejections[0].reasons == (reason,)


@pytest.mark.parametrize(
    "counters,reason",
    [
        (dict(tasks_used=4), "task_limit"),
        (dict(tasks_used=3, tasks_reserved=1), "task_limit"),
        (dict(rounds_used=4), "round_limit"),
        (dict(rounds_used=3, rounds_reserved=1), "round_limit"),
        (dict(candidates=()), "no_candidates"),
    ],
)
def test_persisted_task_round_and_candidate_stop_conditions(counters, reason):
    result = decide_repair(repair_input(**counters))
    assert result.outcome == "stop" and result.stop_reason == reason


@pytest.mark.parametrize("status", ["pending", "uncertain"])
def test_unsettled_attempts_block_redispatch(status):
    result = decide_repair(
        repair_input(attempts=(attempt(status=status, verified_criteria_gained=None),))
    )
    assert result.rejections[0].reasons == ("attempt_in_flight",)


def test_attempt_cap_and_history_prevent_stale_counter_bypass():
    inputs = repair_input()
    policy = RepairPolicy(**(inputs.policy.model_dump() | {"max_attempts_per_dimension": 1}))
    result = decide_repair(repair_input(policy=policy, attempts=(attempt(),)))
    assert result.rejections[0].reasons == ("attempt_limit",)
    policy = RepairPolicy(**(inputs.policy.model_dump() | {"max_tasks": 1}))
    assert (
        decide_repair(repair_input(policy=policy, attempts=(attempt(),))).stop_reason
        == "task_limit"
    )
    assert (
        decide_repair(repair_input(attempts=(attempt(round_number=4),))).stop_reason
        == "round_limit"
    )


@pytest.mark.parametrize(
    "changes", [dict(evidence_fingerprint=FINGERPRINT), dict(candidate_id=uid(30))]
)
def test_same_evidence_or_same_candidate_cannot_be_retried(changes):
    result = decide_repair(repair_input(attempts=(attempt(**changes),)))
    assert result.rejections[0].reasons == ("unchanged_evidence",)


def test_zero_yield_stops_but_missing_assessment_is_not_zero_yield():
    zero = decide_repair(repair_input(attempts=(attempt(verified_criteria_gained=0),)))
    assert zero.rejections[0].reasons == ("no_progress",)
    unknown = decide_repair(repair_input(attempts=(attempt(verified_criteria_gained=None),)))
    assert unknown.outcome == "propose"
    inputs = repair_input()
    policy = RepairPolicy(**(inputs.policy.model_dump() | {"max_no_progress_attempts": 2}))
    assert (
        decide_repair(
            repair_input(policy=policy, attempts=(attempt(verified_criteria_gained=0),))
        ).outcome
        == "propose"
    )
    assert decide_repair(
        repair_input(
            policy=policy,
            attempts=(
                attempt(verified_criteria_gained=0),
                attempt(41, round_number=2, verified_criteria_gained=0),
            ),
        )
    ).rejections[0].reasons == ("no_progress",)


def test_repair_order_is_mandatory_priority_dimension_then_candidate_uuid():
    dims = (
        dimension(13, mandatory=False),
        dimension(12, priority=5),
        dimension(11, priority=0),
        dimension(10, priority=0),
    )
    coverage = assess_coverage(coverage_input(dimensions=dims))
    candidates = tuple(candidate(30 + index, dimension_id=dim.id) for index, dim in enumerate(dims))
    base = repair_input()
    policy = RepairPolicy(**(base.policy.model_dump() | {"allow_optional": True}))
    expected = (uid(10), uid(11), uid(12), uid(13))
    for order in permutations(candidates):
        result = decide_repair(repair_input(coverage=coverage, candidates=order, policy=policy))
        assert tuple(item.dimension_id for item in result.proposals) == expected


def test_multiple_proposals_consume_cumulative_budget_and_continue_after_expensive_candidate():
    coverage = assess_coverage(
        coverage_input(dimensions=(dimension(), dimension(11), dimension(12)))
    )
    candidates = (
        candidate(collection_allowance=allowance(operations=21)),
        candidate(31, dimension_id=uid(11)),
        candidate(32, dimension_id=uid(12)),
    )
    base = repair_input()
    budget = BudgetSnapshot(
        limits=ResourceAllowance(**(base.budget.limits.model_dump() | {"operations": 3}))
    )
    result = decide_repair(repair_input(coverage=coverage, candidates=candidates, budget=budget))
    assert tuple(item.candidate_id for item in result.proposals) == (uid(31),)
    assert result.allocated.operations == 2
    assert result.rejections[0].candidate_id == uid(30)
    assert result.rejections[1].candidate_id == uid(32)
    assert "operations" in result.rejections[1].reasons


def test_one_task_per_dimension_and_round_task_cap():
    coverage = assess_coverage(coverage_input(dimensions=(dimension(), dimension(11))))
    candidates = (candidate(31), candidate(30), candidate(32, dimension_id=uid(11)))
    base = repair_input()
    policy = RepairPolicy(**(base.policy.model_dump() | {"max_tasks_per_round": 1}))
    result = decide_repair(repair_input(coverage=coverage, candidates=candidates, policy=policy))
    assert tuple(item.candidate_id for item in result.proposals) == (uid(30),)
    assert "dimension_already_selected" in result.rejections[0].reasons
    assert "round_task_limit" in result.rejections[1].reasons


def test_covered_optional_and_running_dimensions_do_not_dispatch():
    covered = assess_coverage(
        coverage_input(claims=(claim(),), criterion_assessments=(assessment(),))
    )
    assert decide_repair(repair_input(coverage=covered)).stop_reason == "no_eligible_gap"
    optional = assess_coverage(coverage_input(dimensions=(dimension(mandatory=False),)))
    assert decide_repair(repair_input(coverage=optional)).stop_reason == "no_eligible_gap"
    running = TaskState(**SCOPE, id=uid(50), dimension_ids=(uid(10),), status="running")
    active = assess_coverage(coverage_input(task_states=(running,)))
    assert decide_repair(repair_input(coverage=active)).rejections[0].reasons == (
        "collection_in_flight",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("operations", True),
        ("time_ms", 1.5),
        ("sources", -1),
        ("input_tokens", 10**12 + 1),
        ("cost_usd", "NaN"),
        ("cost_usd", "Infinity"),
        ("cost_usd", "-0.01"),
        ("cost_usd", "0.0000000001"),
    ],
)
def test_invalid_resource_units_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ResourceAllowance(**{field: value})


def test_intermediate_sum_over_input_bound_rejects_without_overflow_or_clamping():
    large = allowance(operations=10**12, cost_usd=Decimal("1000000000"))
    result = decide_repair(
        repair_input(
            candidates=(
                candidate(
                    collection_allowance=large,
                    assessment_allowance=large,
                ),
            )
        )
    )
    assert result.outcome == "stop"
    assert "operations" in result.rejections[0].reasons
    assert "cost_usd" in result.rejections[0].reasons


def test_repair_rejects_foreign_scope_unknown_dimensions_and_duplicate_history():
    base = repair_input()
    with pytest.raises(ValidationError, match="Mismatched"):
        repair_input(run_id=uid(999))
    with pytest.raises(ValidationError, match="Unknown repair dimension"):
        repair_input(candidates=(candidate(dimension_id=uid(999)),))
    with pytest.raises(ValidationError, match="Duplicate"):
        repair_input(attempts=(attempt(), attempt()))
    with pytest.raises(ValidationError):
        RepairInput.model_validate(base.model_dump() | {"evidence_fingerprint": "unversioned"})
    with pytest.raises(ValidationError):
        attempt(status="uncertain", verified_criteria_gained=0)


def test_collection_bounds_are_explicit():
    with pytest.raises(ValidationError):
        coverage_input(dimensions=tuple(dimension(i) for i in range(33)))
    with pytest.raises(ValidationError):
        repair_input(candidates=tuple(candidate(i + 100) for i in range(33)))
    with pytest.raises(ValidationError):
        dimension(criteria=(Criterion(id=uid(100), label="Optional", mandatory=False),))


def test_main_plan_with_twenty_seven_dimensions_and_five_criteria_each_fits():
    dims = tuple(
        dimension(
            300 + index,
            criteria=tuple(
                Criterion(id=uid(10000 + index * 5 + offset), label=f"Success criterion {offset}")
                for offset in range(5)
            ),
        )
        for index in range(27)
    )
    linked_claim = claim(dimension_ids=tuple(item.id for item in dims))
    reviews = tuple(
        assessment(dimension_id=dim.id, criterion_id=criterion.id)
        for dim in dims
        for criterion in dim.criteria
    )
    result = assess_coverage(
        coverage_input(
            dimensions=dims,
            claims=(linked_claim,),
            criterion_assessments=reviews,
        )
    )
    assert len(result.dimensions) == 27
    assert all(row.state == "verified_covered" for row in result.dimensions)
    assert result.quality == "partial"


def test_two_attempts_for_one_dimension_in_one_round_are_ambiguous():
    with pytest.raises(ValidationError, match="dimension/round attempts"):
        repair_input(attempts=(attempt(), attempt(41)))
