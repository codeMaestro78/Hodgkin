from dataclasses import replace
from uuid import UUID

import pytest

from research_api import mode_planning
from research_api.mode_planning import CoveragePlan, attach_coverage_plan, planning_admission
from research_api.mode_policy import resolve_mode_budget


def plan(**kwargs):
    inputs = dict(
        run_id=UUID(int=1),
        question="Compare approaches",
        requirements=["Risk", "Cost", "Recovery"],
        questions=[
            {"question": "How does recovery work?", "success_criteria": ["Recovery evidence"]},
            {"question": "What are the risks?", "success_criteria": ["Risk evidence"]},
        ],
        mode="deep",
        policy_version="research-mode-policy-v1",
        operations=6,
        sources=4,
        repair_operations=2,
    )
    return attach_coverage_plan(**(inputs | kwargs))


def test_every_requirement_has_stable_identity_and_routing():
    result = plan()
    assert result == plan()
    assert set(result.requirement_dimensions) == {
        "question",
        "requirement-1",
        "requirement-2",
        "requirement-3",
    }
    assigned = {dim for row in result.question_dimensions for dim in row}
    assert {dim.id for dim in result.dimensions} == assigned
    assert sum(result.operations_per_question) + result.repair_operations_reserved == 6
    assert sum(result.sources_per_question) + result.repair_sources_reserved == 4


def test_low_budget_plan_rejects_before_dispatch():
    with pytest.raises(ValueError, match="operation budget"):
        plan(operations=3)


def test_duplicate_questions_do_not_create_duplicate_dimension_identity():
    with pytest.raises(ValueError, match="duplicate"):
        plan(questions=[{"question": "Same?", "success_criteria": ["Evidence"]}] * 2)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_dimension",
        "duplicate_dimension",
        "unknown_requirement",
        "no_main_question",
        "missing_allocation",
        "boolean_allocation",
    ],
)
def test_persisted_plan_rejects_broken_links_or_coercive_allocations(change):
    value = plan().model_dump(mode="json")
    if change == "unknown_dimension":
        value["question_dimensions"][0] = [str(UUID(int=99))]
    elif change == "duplicate_dimension":
        value["dimensions"].append(value["dimensions"][0])
    elif change == "unknown_requirement":
        value["requirement_dimensions"]["requirement-99"] = value["question_dimensions"][0]
    elif change == "no_main_question":
        del value["requirement_dimensions"]["question"]
    elif change == "missing_allocation":
        value["operations_per_question"].pop()
    else:
        value["sources_per_question"][0] = True
    with pytest.raises(ValueError):
        CoveragePlan.model_validate(value)


@pytest.mark.parametrize("classes", [["trusted_because_title_says_so"], ["primary", "primary"], []])
def test_invalid_source_class_requests_reject_before_dispatch(classes):
    with pytest.raises(ValueError, match="source class"):
        plan(
            questions=[
                {
                    "question": "What is the source?",
                    "success_criteria": ["Evidence"],
                    "source_classes": classes,
                }
            ]
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("operations_per_question", [10000, 2]),
        ("sources_per_question", [10000, 1]),
        ("repair_operations_reserved", 10000),
        ("repair_sources_reserved", 10000),
        ("sources_per_question", [1, 0]),
        ("sources_per_question", [3, 1]),
        ("max_provider_operations", 3),
        ("max_sources", 2),
        ("max_provider_operations", 21),
        ("max_sources", 21),
        ("policy_version", "invented-policy"),
    ],
)
def test_persisted_allocations_enforce_frozen_ceilings(field, value):
    payload = plan().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValueError):
        CoveragePlan.model_validate(payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sources": -1},
        {"sources": 1},
        {"sources": 21},
        {"operations": 21},
        {"operations": True},
        {"sources": 1.5},
        {"repair_operations": -2},
        {"repair_operations": 1},
        {"repair_sources": 0},
    ],
)
def test_attach_rejects_invalid_or_unfunded_resource_allocations(kwargs):
    with pytest.raises(ValueError):
        plan(**kwargs)


def test_allocations_and_ceiling_fields_are_frozen():
    value = plan()
    with pytest.raises(ValueError):
        value.max_sources = 20
    with pytest.raises(TypeError):
        value.sources_per_question[0] = 20
    budget = replace(
        resolve_mode_budget("deep"), max_search_calls=6, max_provider_operations=6, max_sources=4
    )
    assert value.validate_budget(budget, mode="deep", policy_version=value.policy_version) is value
    with pytest.raises(ValueError, match="does not match"):
        value.validate_budget(
            replace(budget, max_sources=5), mode="deep", policy_version=value.policy_version
        )


@pytest.mark.parametrize(
    "mode,operations,sources,rounds,expected",
    [
        ("focused", 6, 6, 1, (2, 2, 1, 5)),
        ("balanced", 12, 12, 1, (4, 4, 2, 10)),
        ("deep", 20, 20, 1, (6, 8, 4, 16)),
        ("deep", 4, 1, 1, (1, 0, 0, 1)),
        ("deep", 4, 2, 0, (2, 0, 0, 2)),
        ("focused", 6, 6, 0, (3, 0, 0, 6)),
        ("deep", 2, 20, 1, (1, 0, 0, 20)),
    ],
)
def test_shared_admission_keeps_initial_and_repair_tasks_funded(
    monkeypatch, mode, operations, sources, rounds, expected
):
    monkeypatch.setattr(mode_planning, "EXPLICIT_REPAIR_ENABLED", True)
    budget = replace(
        resolve_mode_budget(mode),
        max_search_calls=operations,
        max_provider_operations=operations,
        max_sources=sources,
        max_reflection_rounds=rounds,
    )
    value = planning_admission(budget, mode=mode, quick_mode=True)
    assert (
        value.max_initial_questions,
        value.repair_operations_reserved,
        value.repair_sources_reserved,
        value.initial_source_limit,
    ) == expected


@pytest.mark.parametrize(
    "mode,operations,sources,expected",
    [
        ("focused", 6, 6, 3),
        ("balanced", 12, 12, 4),
        ("deep", 20, 20, 6),
        ("deep", 4, 20, 2),
        ("deep", 20, 1, 1),
        ("focused", 2, 6, 1),
    ],
)
def test_disabled_repair_never_reserves_initial_collection_capacity(
    mode, operations, sources, expected
):
    assert mode_planning.EXPLICIT_REPAIR_ENABLED is False
    budget = replace(
        resolve_mode_budget(mode),
        max_search_calls=operations,
        max_provider_operations=operations,
        max_sources=sources,
        max_reflection_rounds=1,
    )
    admission = planning_admission(budget, mode=mode)
    assert admission.max_initial_questions == expected
    assert admission.initial_source_limit == sources
    assert admission.repair_operations_reserved == admission.repair_sources_reserved == 0


@pytest.mark.parametrize(
    "mode,rounds,expected",
    [
        ("focused", 1, (3, 0, 0, 6)),
        ("balanced", 1, (4, 4, 2, 10)),
        ("deep", 1, (6, 8, 4, 16)),
        ("balanced", 0, (4, 0, 0, 12)),
    ],
)
def test_bounded_repair_reserves_only_for_balanced_and_deep(mode, rounds, expected):
    assert mode_planning.EXPLICIT_REPAIR_ENABLED is False
    budget = replace(resolve_mode_budget(mode), max_reflection_rounds=rounds)
    value = planning_admission(budget, mode=mode, repair=True)
    assert (
        value.max_initial_questions,
        value.repair_operations_reserved,
        value.repair_sources_reserved,
        value.initial_source_limit,
    ) == expected
