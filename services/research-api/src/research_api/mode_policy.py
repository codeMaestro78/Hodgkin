"""Server-owned, versioned admission policy. Null mode is always legacy."""

from dataclasses import replace
from decimal import Decimal
from typing import Literal

from research_api.repositories.runs import RunBudgetDefaults

ResearchMode = Literal["focused", "balanced", "deep"]
MODE_POLICY_VERSION = "research-mode-policy-v1"
# Keep historical versions available for idempotent replay after a policy rollout.
MODE_POLICIES = {
    "research-mode-policy-v1": {
        "focused": (6, 180_000),
        "balanced": (12, 300_000),
        "deep": (20, 600_000),
    }
}


def resolve_mode_budget(
    mode: str, overrides: object | None = None, *, policy_version: str | None = None
) -> RunBudgetDefaults:
    version = policy_version or MODE_POLICY_VERSION
    if version not in MODE_POLICIES or mode not in MODE_POLICIES[version]:
        raise ValueError("unsupported research mode or policy version")
    operations, wall_ms = MODE_POLICIES[version][mode]
    defaults = RunBudgetDefaults(
        max_search_calls=operations,
        max_provider_operations=operations,
        max_sources=operations,
        max_wall_clock_ms=wall_ms,
        max_browser_sessions=0,
        max_reflection_rounds=1,
        max_input_tokens=100_000,
        max_output_tokens=20_000,
        max_estimated_cost_usd=Decimal("5.00"),
    )
    fields: set[str] = getattr(overrides, "model_fields_set", set())
    values = {
        field: getattr(overrides, field)
        for field in fields
        if getattr(overrides, field) is not None
    }
    old_ops = values.pop("max_search_calls", None)
    new_ops = values.get("max_provider_operations")
    if old_ops is not None and new_ops is not None and old_ops != new_ops:
        raise ValueError("maxSearchCalls and maxProviderOperations must agree")
    if old_ops is not None:
        values["max_provider_operations"] = old_ops
    for field, value in values.items():
        if field not in RunBudgetDefaults.__dataclass_fields__:
            raise ValueError(f"unsupported budget override: {field}")
        ceiling = getattr(defaults, field)
        if field == "max_estimated_cost_usd":
            value = Decimal(str(value))
            values[field] = value
        minimum = (
            2
            if field == "max_provider_operations"
            else (
                1
                if field
                in {"max_sources", "max_wall_clock_ms", "max_input_tokens", "max_output_tokens"}
                else 0
            )
        )
        if not minimum <= value <= ceiling:
            raise ValueError(f"{field} must be between {minimum} and {ceiling} for {mode}")
    values["max_search_calls"] = values.get("max_provider_operations", operations)
    return replace(defaults, **values)


def validate_mode_budget(mode: str, budget: RunBudgetDefaults, *, policy_version: str) -> None:
    """Internal callers must supply a complete snapshot within its archived policy."""
    if budget.max_provider_operations is None or budget.max_sources is None:
        raise ValueError("explicit mode requires independent operation and source limits")
    if budget.max_search_calls != budget.max_provider_operations:
        raise ValueError("compatibility operation limit must match max_provider_operations")
    ceiling = resolve_mode_budget(mode, policy_version=policy_version)
    for field in RunBudgetDefaults.__dataclass_fields__:
        value = getattr(budget, field)
        minimum = (
            2
            if field in {"max_search_calls", "max_provider_operations"}
            else (
                0
                if field
                in {"max_browser_sessions", "max_reflection_rounds", "max_estimated_cost_usd"}
                else 1
            )
        )
        if field == "max_estimated_cost_usd" and not value.is_finite():
            raise ValueError("budget cost must be finite")
        if not minimum <= value <= getattr(ceiling, field):
            raise ValueError(f"{field} exceeds the stored mode policy bounds")
