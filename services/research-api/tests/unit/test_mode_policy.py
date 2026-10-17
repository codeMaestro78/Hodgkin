from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from research_api.api import _budget_from_request
from research_api.mode_policy import resolve_mode_budget
from research_api.research_limits import is_run_quick, operation_limit, run_source_limit
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest


@pytest.mark.parametrize(
    "mode,ceiling,wall",
    [
        ("focused", 6, 180_000),
        ("balanced", 12, 300_000),
        ("deep", 20, 600_000),
    ],
)
def test_explicit_mode_defaults(mode, ceiling, wall):
    result = resolve_mode_budget(mode)
    assert operation_limit(result) == result.max_search_calls == ceiling
    assert run_source_limit(result) == ceiling
    assert result.max_wall_clock_ms == wall
    assert not is_run_quick(mode=mode, question="What is gravity?")


def test_partial_override_does_not_apply_generated_search_default():
    request = CreateResearchRunRequest.model_validate(
        {
            "question": "What is gravity?",
            "mode": "focused",
            "budgetOverrides": {"maxProviderOperations": 2, "maxSources": 1},
        }
    )
    result = _budget_from_request(request)
    assert result.max_search_calls == operation_limit(result) == 2
    assert run_source_limit(result) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"maxSearchCalls": 20},
        {"maxProviderOperations": 7},
        {"maxSources": 7},
        {"maxWallClockMs": 180_001},
        {"maxInputTokens": 100_001},
        {"maxOutputTokens": 20_001},
        {"maxEstimatedCostUsd": 5.01},
        {"maxSearchCalls": 3, "maxProviderOperations": 2},
    ],
)
def test_explicit_overrides_cannot_loosen_policy(override):
    request = CreateResearchRunRequest.model_validate(
        {
            "question": "Compare two approaches",
            "mode": "focused",
            "budgetOverrides": override,
        }
    )
    with pytest.raises(HTTPException) as error:
        _budget_from_request(request)
    assert error.value.status_code == 422


def test_tightened_deep_limits_preserve_explicit_mode_semantics():
    result = resolve_mode_budget(
        "deep",
        SimpleNamespace(
            model_fields_set={"max_provider_operations", "max_sources", "max_wall_clock_ms"},
            max_provider_operations=2,
            max_sources=1,
            max_wall_clock_ms=1000,
        ),
    )
    assert operation_limit(result) == 2
    assert run_source_limit(result) == 1
    assert not is_run_quick(SimpleNamespace(mode="deep", original_question="What is gravity?"))


def test_legacy_conversion_and_helper_fallback_are_unchanged():
    request = CreateResearchRunRequest.model_validate(
        {
            "question": "What is gravity?",
            "budgetOverrides": {"maxWallClockMs": 1000},
        }
    )
    result = _budget_from_request(request)
    assert result.max_search_calls == 12
    assert result.max_provider_operations is result.max_sources is None
    assert is_run_quick(mode=None, question=request.question)
    assert run_source_limit(result, True) == 2
    assert operation_limit(result) == 12


def test_new_fields_are_independent_of_legacy_compatibility_field():
    budget = SimpleNamespace(max_search_calls=20, max_provider_operations=2, max_sources=6)
    assert operation_limit(budget) == 2
    assert run_source_limit(budget) == 6
