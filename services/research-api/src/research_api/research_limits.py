"""Source ceilings derived from the persisted provider-call budget.

The UI presets use the same numeric ceiling for sources and provider operations.
Search and extraction each consume one operation, not one source.
"""

from typing import Protocol

from research_api.query_intelligence import is_quick_explainer


class LimitBudget(Protocol):
    @property
    def max_search_calls(self) -> int: ...

    @property
    def max_provider_operations(self) -> int | None: ...

    @property
    def max_sources(self) -> int | None: ...


def operation_limit(budget: LimitBudget) -> int:
    value = getattr(budget, "max_provider_operations", None)
    return budget.max_search_calls if value is None else value


def run_source_limit(budget: LimitBudget, quick_mode: bool = False) -> int:
    value = getattr(budget, "max_sources", None)
    return source_limit(budget.max_search_calls, quick_mode) if value is None else value


def is_run_quick(run: object | None = None, *, mode: str | None = None, question: str = "") -> bool:
    if run is not None:
        mode = getattr(run, "mode", None)
        question = getattr(run, "original_question", "")
    return mode is None and is_quick_explainer(question)


def source_limit(max_search_calls: int, quick_mode: bool = False) -> int:
    return min(max_search_calls, 2) if quick_mode else max_search_calls


def active_time_limit(max_search_calls: int) -> int:
    """Visible mode defaults: quick 2m, Focused 3m, Balanced 5m, Deep 10m.

    These are upper bounds, not latency promises. Explicit user limits win.
    """
    if max_search_calls <= 2:
        return 120_000
    if max_search_calls <= 6:
        return 180_000
    if max_search_calls <= 12:
        return 300_000
    return 600_000


def source_allocations(limit: int, questions: int, existing: int = 0) -> list[int]:
    """Preallocate slots so concurrent workers cannot overshoot the run ceiling."""
    if questions <= 0:
        return []
    remaining = max(0, limit - existing)
    per_question, extra = divmod(remaining, questions)
    return [min(6, per_question + (index < extra)) for index in range(questions)]
