"""Stable LangGraph checkpoint state contract.

Keep the fields and reducers compatible with persisted graph checkpoints. Node
implementations may be reorganized without changing this public state shape.
"""

from typing import Annotated, Literal, NotRequired, TypedDict


def merge_source_ids(left: list[str], right: list[str]) -> list[str]:
    """Merge graph fan-out source IDs in first-seen order without duplicates."""
    return list(dict.fromkeys([*left, *right]))


class RunState(TypedDict):
    run_id: str
    tenant_id: str
    user_id: str
    question: str
    sub_question_ids: list[str]
    source_ids: Annotated[list[str], merge_source_ids]
    quick_mode: bool
    mode: NotRequired[str | None]
    mode_policy_version: NotRequired[str | None]
    graph_version: NotRequired[str]
    discovery_provider: NotRequired[Literal["tavily", "serper"]]
    openalex_discovery_enabled: NotRequired[bool]
    error: NotRequired[str]
    reflection_round: NotRequired[int]
    expand: NotRequired[bool]
    assessment_id: NotRequired[str]
    repair_admitted: NotRequired[bool]
