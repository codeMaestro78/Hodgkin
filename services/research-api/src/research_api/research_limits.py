"""Source ceilings derived from the persisted provider-call budget.

The UI presets use the same numeric ceiling for sources and provider operations.
Search and extraction each consume one operation, not one source.
"""


def source_limit(max_search_calls: int, quick_mode: bool = False) -> int:
    return min(max_search_calls, 2) if quick_mode else max_search_calls


def source_allocations(limit: int, questions: int, existing: int = 0) -> list[int]:
    """Preallocate slots so concurrent workers cannot overshoot the run ceiling."""
    if questions <= 0:
        return []
    remaining = max(0, limit - existing)
    per_question, extra = divmod(remaining, questions)
    return [min(6, per_question + (index < extra)) for index in range(questions)]
