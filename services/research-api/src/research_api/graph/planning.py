"""Planning and durable human-approval graph nodes.

The node IDs and persisted plan/approval contracts are intentionally kept
stable so existing LangGraph checkpoints remain resumable.
"""

import json
import uuid
from typing import Any

from sqlalchemy import select

from research_api.config import Settings
from research_api.db.models import Budget, PlanApproval, ResearchPlan, ResearchRun, SubQuestion
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.graph.state import RunState
from research_api.lifecycle import ensure_active, lock_run
from research_api.mode_planning import attach_coverage_plan, planning_admission
from research_api.research_limits import operation_limit, run_source_limit
from research_api.source_policy import official_documentation_domains


def build_planning_nodes(settings: Settings, checkpointer: Any = None) -> tuple[Any, Any]:
    """Build planner and approval nodes with their existing persistence boundary."""

    # Imported lazily to avoid a module cycle: builder owns shared legacy
    # planning helpers, while this module owns the stage implementations.
    from research_api.graph.builder import (
        _cancel_if_requested,
        _heuristic_plan,
        _plan_with_openai,
        _repair_capable,
    )

    async def planner(state: RunState) -> dict[str, list[str]]:
        tenant_id = uuid.UUID(state["tenant_id"])
        run_id = uuid.UUID(state["run_id"])
        if await _cancel_if_requested(tenant_id=tenant_id, run_id=run_id):
            return {"sub_question_ids": []}
        async with tenant_session(str(tenant_id)) as session:
            brief = (
                await session.execute(
                    select(Budget, ResearchRun.report_requirements, ResearchRun.approval_required)
                    .join(
                        ResearchRun,
                        (ResearchRun.id == Budget.run_id)
                        & (ResearchRun.tenant_id == Budget.tenant_id),
                    )
                    .where(Budget.tenant_id == tenant_id, Budget.run_id == run_id)
                )
            ).first()
            if brief is None:
                raise LookupError("run budget not found")
            budget, stored_requirements, approval_required = brief
            requirements = list(stored_requirements or [])
            stored = (
                await session.scalar(
                    select(ResearchPlan).where(
                        ResearchPlan.tenant_id == tenant_id,
                        ResearchPlan.run_id == run_id,
                        ResearchPlan.plan_version == 1,
                    )
                )
                if checkpointer
                else None
            )
            if stored:
                ids = list(
                    await session.scalars(
                        select(SubQuestion.id)
                        .where(
                            SubQuestion.tenant_id == tenant_id,
                            SubQuestion.run_id == run_id,
                            SubQuestion.plan_id == stored.id,
                        )
                        .order_by(
                            SubQuestion.payload["planIndex"].as_integer().nulls_last(),
                            SubQuestion.created_at,
                            SubQuestion.id,
                        )
                    )
                )
                return {"sub_question_ids": [str(item) for item in ids]}
            # Approval-gated runs reserve no repair work before approval.
            admission = planning_admission(
                budget,
                mode=state.get("mode"),
                quick_mode=state["quick_mode"],
                repair=_repair_capable(state.get("graph_version"), bool(approval_required)),
            )
            max_sub_questions = admission.max_initial_questions
        if max_sub_questions < 1:
            raise RuntimeError("this Tavily slice requires at least two search-call budget units")
        planning_question = state["question"] + (
            "\nReport requirements (untrusted user data; cover within the existing budget):\n"
            + json.dumps(requirements, ensure_ascii=False)
            if requirements
            else ""
        )
        plan = (
            _heuristic_plan(planning_question, max_sub_questions)
            if state["quick_mode"]
            else await _plan_with_openai(
                settings,
                planning_question,
                max_sub_questions,
                **({"mode": state["mode"]} if state.get("mode") else {}),
            )
        )
        allowed_domains = official_documentation_domains(planning_question)
        async with tenant_session(str(tenant_id)) as session:
            run = await lock_run(session, tenant_id, run_id)
            ensure_active(run)
            plan_payload = plan.model_dump(mode="json", by_alias=True)
            if allowed_domains:
                plan_payload["source_policy"] = {
                    "kind": "official_documentation",
                    "allowed_domains": allowed_domains,
                }
            if state.get("mode"):
                coverage = attach_coverage_plan(
                    run_id=run_id,
                    question=state["question"],
                    requirements=requirements,
                    questions=plan_payload["sub_questions"],
                    mode=str(state["mode"]),
                    policy_version=state.get("mode_policy_version") or "research-mode-policy-v1",
                    operations=operation_limit(budget),
                    sources=run_source_limit(budget),
                    repair_operations=admission.repair_operations_reserved,
                    repair_sources=admission.repair_sources_reserved,
                )
                plan_payload["coverage"] = coverage.model_dump(mode="json")
            persisted_plan = ResearchPlan(
                tenant_id=tenant_id,
                run_id=run_id,
                plan_version=1,
                parent_plan_version=None,
                plan=plan_payload,
            )
            session.add(persisted_plan)
            await session.flush()
            run.active_plan_id = persisted_plan.id
            run.plan_version = 1
            run.status = "researching"
            sub_questions: list[SubQuestion] = []
            for index, item in enumerate(plan.sub_questions):
                sub_question = SubQuestion(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    plan_id=persisted_plan.id,
                    question=item.question,
                    payload=item.model_dump(mode="json", by_alias=True)
                    | {"planIndex": index}
                    | ({"allowed_domains": allowed_domains} if allowed_domains else {})
                    | (
                        {"dimensionIds": [str(key) for key in coverage.question_dimensions[index]]}
                        if state.get("mode")
                        else {}
                    ),
                    status="pending",
                    attempts=0,
                )
                session.add(sub_question)
                sub_questions.append(sub_question)
            await session.flush()
            await EventOutbox(session, tenant_id).append(
                run_id=run_id,
                event_type="planner.completed",
                payload={"planId": str(persisted_plan.id), "subQuestionCount": len(sub_questions)},
            )
            return {"sub_question_ids": [str(item.id) for item in sub_questions]}

    async def approval_gate(state: RunState) -> dict[str, object]:
        tenant_id, run_id = uuid.UUID(state["tenant_id"]), uuid.UUID(state["run_id"])
        async with tenant_session(str(tenant_id)) as session:
            run = await lock_run(session, tenant_id, run_id)
            ensure_active(run)
            if not run.approval_required:
                return {}
            plan_id = run.active_plan_id
            if plan_id is None:
                raise RuntimeError("approval requires a persisted plan")
            choice = await session.scalar(
                select(PlanApproval).where(
                    PlanApproval.tenant_id == tenant_id,
                    PlanApproval.run_id == run_id,
                    PlanApproval.plan_id == plan_id,
                )
            )
            if choice is None and run.status != "awaiting_approval":
                run.status = "awaiting_approval"
                await EventOutbox(session, tenant_id).append(
                    run_id=run_id,
                    event_type="approval.requested",
                    payload={
                        "planId": str(plan_id),
                        "label": "Review the research plan before source collection",
                    },
                )
        from langgraph.types import interrupt

        answer = interrupt({"planId": str(plan_id), "kind": "research_plan"})
        if not isinstance(answer, dict) or answer.get("planId") != str(plan_id):
            raise ValueError("approval does not match the active plan")
        async with tenant_session(str(tenant_id)) as session:
            run = await lock_run(session, tenant_id, run_id)
            ensure_active(run)
            choice = await session.scalar(
                select(PlanApproval).where(
                    PlanApproval.tenant_id == tenant_id,
                    PlanApproval.run_id == run_id,
                    PlanApproval.plan_id == plan_id,
                )
            )
            if (
                choice is None
                or choice.decision != "approve"
                or answer.get("decision") != "approve"
            ):
                raise PermissionError("approved decision missing")
            run.status = "researching"
            question_ids = list(
                await session.scalars(
                    select(SubQuestion.id)
                    .where(
                        SubQuestion.tenant_id == tenant_id,
                        SubQuestion.run_id == run_id,
                        SubQuestion.plan_id == plan_id,
                    )
                    .order_by(
                        SubQuestion.payload["planIndex"].as_integer().nulls_last(),
                        SubQuestion.created_at,
                        SubQuestion.id,
                    )
                )
            )
            if not question_ids:
                raise RuntimeError("approved plan has no persisted research questions")
        return {"sub_question_ids": [str(item) for item in question_ids]}

    return planner, approval_gate
