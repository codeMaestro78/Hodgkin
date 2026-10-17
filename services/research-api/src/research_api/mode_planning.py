"""Bounded, stable coverage dimensions attached to versioned explicit-mode plans."""

from dataclasses import dataclass
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from research_api.coverage import Criterion, Dimension
from research_api.mode_policy import resolve_mode_budget
from research_api.mode_reports import policy_for_mode
from research_api.research_limits import (
    LimitBudget,
    operation_limit,
    run_source_limit,
    source_allocations,
)

# No environment/config switch: enable only after bounded delta-assessment gates pass.
EXPLICIT_REPAIR_ENABLED = False
BOUNDED_REPAIR_MODES = frozenset({"balanced", "deep"})


@dataclass(frozen=True, slots=True)
class PlanningAdmission:
    max_initial_questions: int
    repair_operations_reserved: int
    repair_sources_reserved: int
    initial_source_limit: int


def planning_admission(
    budget: LimitBudget, *, mode: str | None, quick_mode: bool = False, repair: bool = False
) -> PlanningAdmission:
    """One initial-task/repair split shared by planning, editing and projections.

    ``repair`` is the job's pinned bounded-repair capability (graph v10). Focused
    never reserves; the global flag remains for all-mode experiments only.
    """
    operations = operation_limit(budget)
    sources = run_source_limit(budget, quick_mode if mode is None else False)
    if mode is None:
        maximum = (
            1 if quick_mode else min(policy_for_mode(operations).question_count, operations // 2)
        )
        return PlanningAdmission(maximum, 0, 0, sources)
    if mode not in {"focused", "balanced", "deep"}:
        raise ValueError("unknown explicit mode")
    if type(operations) is not int or operations < 2 or type(sources) is not int or sources < 1:
        raise ValueError("planning requires at least two operations and one source")
    repairs = (
        min(
            {"focused": 1, "balanced": 2, "deep": 4}[mode],
            (operations - 2) // 2,
            sources - 1,
        )
        if (EXPLICIT_REPAIR_ENABLED or (repair and mode in BOUNDED_REPAIR_MODES))
        and getattr(budget, "max_reflection_rounds", 0) > 0
        else 0
    )
    initial_sources = sources - repairs
    return PlanningAdmission(
        min(
            policy_for_mode(operations, mode=mode).question_count,
            (operations - repairs * 2) // 2,
            initial_sources,
        ),
        repairs * 2,
        repairs,
        initial_sources,
    )


class CoveragePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: StrictInt = Field(ge=1, le=1)
    mode: Literal["focused", "balanced", "deep"]
    policy_version: str = Field(min_length=1, max_length=100)
    dimensions: list[Dimension] = Field(min_length=1, max_length=32)
    # IDs are associations, never certification of semantic satisfaction.
    requirement_dimensions: dict[str, list[UUID]]
    question_dimensions: list[list[UUID]]
    max_provider_operations: StrictInt = Field(ge=2, le=50)
    max_sources: StrictInt = Field(ge=1, le=20)
    operations_per_question: tuple[StrictInt, ...]
    sources_per_question: tuple[StrictInt, ...]
    repair_operations_reserved: StrictInt = Field(ge=0)
    repair_sources_reserved: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def relationships(self) -> "CoveragePlan":
        ceiling = resolve_mode_budget(self.mode, policy_version=self.policy_version)
        if self.max_provider_operations > operation_limit(
            ceiling
        ) or self.max_sources > run_source_limit(ceiling):
            raise ValueError("allocation snapshot exceeds mode policy ceilings")
        ids = {d.id for d in self.dimensions}
        if len(ids) != len(self.dimensions):
            raise ValueError("duplicate coverage dimension")
        criterion_ids = [c.id for d in self.dimensions for c in d.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("duplicate coverage criterion")
        if "question" not in self.requirement_dimensions or len(self.requirement_dimensions) > 21:
            raise ValueError("main question and bounded requirements are required")
        for key, linked in self.requirement_dimensions.items():
            if key != "question" and key not in {f"requirement-{n}" for n in range(1, 21)}:
                raise ValueError("unknown requirement identity")
            if not linked or len(linked) != len(set(linked)) or not set(linked) <= ids:
                raise ValueError("invalid requirement dimension links")
        size = len(self.question_dimensions)
        if not 1 <= size <= {"focused": 3, "balanced": 4, "deep": 6}[self.mode]:
            raise ValueError("invalid mode question count")
        if len(self.operations_per_question) != size or len(self.sources_per_question) != size:
            raise ValueError("allocation count mismatch")
        if any(type(n) is not int or not 1 <= n <= 6 for n in self.sources_per_question):
            raise ValueError("invalid source allocation")
        if any(type(n) is not int or n != 2 for n in self.operations_per_question):
            raise ValueError("invalid operation allocation")
        if (
            self.repair_operations_reserved != 2 * self.repair_sources_reserved
            or self.repair_sources_reserved > {"focused": 1, "balanced": 2, "deep": 4}[self.mode]
        ):
            raise ValueError("invalid repair allocation")
        if (
            sum(self.operations_per_question) + self.repair_operations_reserved
            > self.max_provider_operations
        ):
            raise ValueError("allocations exceed operation budget")
        if sum(self.sources_per_question) + self.repair_sources_reserved > self.max_sources:
            raise ValueError("allocations exceed source budget")
        for linked in self.question_dimensions:
            if not linked or len(linked) != len(set(linked)) or not set(linked) <= ids:
                raise ValueError("invalid question dimension links")
        return self

    def validate_budget(self, budget: LimitBudget, *, mode: str, policy_version: str) -> Self:
        """Stored JSON ceilings must match the authoritative run snapshot on load."""
        if (self.mode, self.policy_version, self.max_provider_operations, self.max_sources) != (
            mode,
            policy_version,
            operation_limit(budget),
            run_source_limit(budget),
        ):
            raise ValueError("coverage allocation snapshot does not match run budget")
        return self


def attach_coverage_plan(
    *,
    run_id: UUID,
    question: str,
    requirements: list[str],
    questions: list[dict[str, Any]],
    mode: str,
    policy_version: str,
    operations: int,
    sources: int,
    repair_operations: int = 0,
    repair_sources: int | None = None,
) -> CoveragePlan:
    """Route explicit requirements without claiming collection or coverage success.

    The main question and every user requirement get their own mandatory criterion.
    Task dimensions retain the planner's success criteria. All identities are
    derived from immutable input, so approval/restart cannot invent new IDs.
    """
    if mode not in {"focused", "balanced", "deep"}:
        raise ValueError("unknown mode")
    if not 1 <= len(questions) <= {"focused": 3, "balanced": 4, "deep": 6}[mode]:
        raise ValueError("mode question bound exceeded")
    if any(type(value) is not int for value in (operations, sources, repair_operations)):
        raise ValueError("allocation ceilings must be integers")
    if repair_sources is None:
        repair_sources = repair_operations // 2
    if type(repair_sources) is not int or repair_sources < 0 or repair_operations < 0:
        raise ValueError("invalid repair allocation")
    if len(requirements) > 20 or operations < 2 * len(questions) + repair_operations:
        raise ValueError("plan does not fit operation budget")
    if sources - repair_sources < len(questions):
        raise ValueError("every initial question needs source capacity")
    dimensions = []
    requirement_dimensions = {}
    for index, text in enumerate([question, *requirements]):
        key = "question" if index == 0 else f"requirement-{index}"
        dim_id = uuid5(run_id, f"dimension:{key}")
        dimensions.append(
            Dimension(
                id=dim_id,
                label=text[:1000],
                priority=index,
                criteria=tuple(
                    Criterion(id=uuid5(dim_id, f"criterion:{offset}"), label=part)
                    for offset, start in enumerate(range(0, len(text), 1000))
                    if (part := text[start : start + 1000]).strip()
                ),
            )
        )
        requirement_dimensions[key] = [dim_id]
    mappings = []
    for index, item in enumerate(questions):
        classes = item.get("source_classes", ["unknown"])
        if (
            not classes
            or len(classes) > 5
            or len(set(classes)) != len(classes)
            or not set(classes) <= {"primary", "secondary", "academic", "official", "unknown"}
        ):
            raise ValueError("unknown or duplicate requested source class")
        dim_id = uuid5(run_id, "task-dimension:" + item["question"])
        if any(dim.id == dim_id for dim in dimensions):
            raise ValueError("duplicate plan question")
        criteria = item.get("success_criteria") or []
        if not 1 <= len(criteria) <= 5:
            raise ValueError("each task needs bounded success criteria")
        dimensions.append(
            Dimension(
                id=dim_id,
                label=item["question"][:1000],
                priority=min(100, 21 + index),
                criteria=tuple(
                    Criterion(id=uuid5(dim_id, f"criterion:{offset}"), label=text[:1000])
                    for offset, text in enumerate(criteria)
                ),
            )
        )
        # A routing assignment only; independent assessment decides coverage.
        assigned = [requirement_dimensions["question"][0], dim_id]
        assigned.extend(
            requirement_dimensions[f"requirement-{offset + 1}"][0]
            for offset in range(len(requirements))
            if offset % len(questions) == index
        )
        mappings.append(assigned)
    return CoveragePlan(
        version=1,
        mode=mode,
        policy_version=policy_version,
        dimensions=dimensions,
        requirement_dimensions=requirement_dimensions,
        question_dimensions=mappings,
        max_provider_operations=operations,
        max_sources=sources,
        operations_per_question=tuple([2] * len(questions)),
        sources_per_question=tuple(source_allocations(sources - repair_sources, len(questions))),
        repair_operations_reserved=repair_operations,
        repair_sources_reserved=repair_sources,
    )
