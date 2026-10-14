"""Depth choices must have explicit, bounded time as well as source budgets."""

import pytest

from research_api.api import _budget_from_request
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest


@pytest.mark.parametrize("calls,expected", [(6, 180_000), (12, 300_000), (20, 600_000)])
def test_depth_deadline_matches_workload(calls, expected):
    request = CreateResearchRunRequest(
        question="Compare architectural options", budgetOverrides={"maxSearchCalls": calls}
    )
    assert _budget_from_request(request).max_wall_clock_ms == expected


def test_explicit_deadline_is_not_silently_increased():
    request = CreateResearchRunRequest(
        question="Compare architectural options",
        budgetOverrides={"maxSearchCalls": 20, "maxWallClockMs": 10_000},
    )
    assert _budget_from_request(request).max_wall_clock_ms == 10_000
