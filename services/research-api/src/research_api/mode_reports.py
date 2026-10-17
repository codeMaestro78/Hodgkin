"""Explicit-mode report selection, preserving the legacy policy implementation."""

from dataclasses import replace

from research_api.reports import ReportPolicy, report_policy

MODE_CEILINGS = {"focused": 6, "balanced": 12, "deep": 20}


def policy_for_mode(
    calls: int, *, mode: str | None = None, max_sources: int | None = None
) -> ReportPolicy:
    """Budget tightening changes available evidence, never the selected report mode."""
    if mode is None:
        return report_policy(calls)
    if mode not in MODE_CEILINGS:
        raise ValueError("unknown explicit research mode")
    policy = report_policy(MODE_CEILINGS[mode])
    return replace(
        policy,
        source_count=min(policy.source_count, max_sources if max_sources is not None else calls),
    )
