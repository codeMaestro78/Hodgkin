import pytest

from research_api.research_limits import source_allocations, source_limit


@pytest.mark.parametrize(
    "calls,questions,expected", [(6, 3, [2, 2, 2]), (12, 6, [2] * 6), (20, 8, [3] * 4 + [2] * 4)]
)
def test_mode_allocations_bound_entire_run(calls: int, questions: int, expected: list[int]) -> None:
    assert source_allocations(source_limit(calls), questions) == expected
    assert sum(expected) <= calls


def test_existing_sources_consume_slots_before_parallel_dispatch() -> None:
    assert source_allocations(6, 3, existing=5) == [1, 0, 0]
    assert source_allocations(6, 3, existing=18) == [0, 0, 0]


def test_quick_explainer_and_empty_plan_are_bounded() -> None:
    assert source_limit(20, quick_mode=True) == 2
    assert source_allocations(2, 1) == [2]
    assert source_allocations(6, 0) == []


@pytest.mark.parametrize("limit", range(1, 51))
def test_allocations_never_overbook_slots(limit: int) -> None:
    for questions in range(1, 9):
        for existing in (0, 1, limit, limit + 1):
            slots = source_allocations(limit, questions, existing)
            assert sum(slots) <= max(0, limit - existing)
            assert all(0 <= slot <= 6 for slot in slots)
