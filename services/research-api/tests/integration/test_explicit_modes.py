"""Local-only admission, replay and frozen mode-policy snapshots."""

import asyncio
import importlib
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import api, mode_planning, mode_policy, runtime_api
from research_api.config import Settings
from research_api.db.models import (
    Budget,
    DispatchRegistry,
    Report,
    ResearchPlan,
    ResearchRun,
    RunEvent,
    RuntimeJob,
    Source,
    SubQuestion,
    Tenant,
    UsageLedger,
    User,
)
from research_api.db.session import tenant_session
from research_api.jobs import PROTECTED_MODE_GRAPH_VERSION, PROTECTED_MODE_SERPER_GRAPH_VERSION
from research_api.mode_planning import CoveragePlan, attach_coverage_plan, planning_admission
from research_api.repositories.budgets import BudgetExceededError, BudgetReservationRepository
from research_api.repositories.runs import RunBudgetDefaults, RunRepository
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest
from research_api.schemas.generated.followup_request import FollowupRequest

pytestmark = pytest.mark.integration


@pytest.fixture
async def identity(monkeypatch):
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Explicit modes local fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id=tenant,
                user_id=user,
            )
        ),
    )
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: Settings(
            APP_ENV="test",
            SERPER_DISCOVERY_ENABLED=False,
        ),
    )
    return tenant, user


async def submit(mode=None, overrides=None, key=None):
    payload = CreateResearchRunRequest.model_validate(
        {
            "question": "What is gravity?",
            "mode": mode,
            "budgetOverrides": overrides,
            "idempotencyKey": key or str(uuid.uuid4()),
        }
    )
    return await api.create_research_run(payload, SimpleNamespace())


@pytest.mark.parametrize(
    "mode,operations,sources,wall",
    [
        ("focused", 6, 6, 240_000),
        ("balanced", 12, 12, 300_000),
        ("deep", 20, 20, 600_000),
    ],
)
async def test_explicit_admission_projection_and_job(identity, mode, operations, sources, wall):
    tenant, _ = identity
    response = await submit(mode)
    run_id = uuid.UUID(response["runId"])
    assert response["mode"] == mode
    assert response["modePolicyVersion"] == mode_policy.MODE_POLICY_VERSION
    assert response["budget"]["maxProviderOperations"] == operations
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        budget = await session.scalar(select(Budget).where(Budget.run_id == run_id))
        job = await session.get(RuntimeJob, run_id)
        assert (run.mode, run.mode_policy_version) == (mode, mode_policy.MODE_POLICY_VERSION)
        assert (
            budget.max_search_calls,
            budget.max_provider_operations,
            budget.max_sources,
            budget.max_wall_clock_ms,
        ) == (operations, operations, sources, wall)
        assert job.graph_version == PROTECTED_MODE_GRAPH_VERSION
    projection = await api.get_research_run(run_id)
    assert projection["quickMode"] is False
    assert projection["modeResolution"] == "explicit"
    assert projection["sourceLimit"] == sources
    assert projection["usage"]["providerOperations"] == projection["usage"]["searchCalls"] == 0
    listing = await api.list_research_runs()
    assert listing["runs"][0]["mode"] == mode
    assert listing["runs"][0]["quickMode"] is False


async def test_legacy_null_and_response_compatibility(identity):
    tenant, _ = identity
    response = await submit()
    assert set(response) == {"runId", "status"}
    run_id = uuid.UUID(response["runId"])
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        assert run.mode is run.mode_policy_version is None
    projection = await api.get_research_run(run_id)
    assert projection["modeResolution"] == "legacy-inferred"
    assert projection["modePolicyVersion"] is None
    assert projection["quickMode"] is True


async def test_explicit_partial_budget_and_durable_source_usage(identity):
    tenant, _ = identity
    response = await submit("deep", {"maxProviderOperations": 2, "maxSources": 1})
    run_id = uuid.UUID(response["runId"])
    async with tenant_session(str(tenant)) as session:
        session.add(
            Source(
                tenant_id=tenant,
                run_id=run_id,
                canonical_url="https://fixture.invalid/source",
                title="Local source",
                provider="fixture",
                source_class="primary",
                content_hash="f" * 64,
                artifact_ref="fixture",
                retrieved_at=datetime.now(UTC),
            )
        )
    projection = await api.get_research_run(run_id)
    assert projection["mode"] == "deep"
    assert projection["budget"]["maxProviderOperations"] == 2
    assert projection["sourceLimit"] == projection["usage"]["sources"] == 1
    assert projection["quickMode"] is False


async def test_explicit_over_ceiling_fails_before_admission(identity):
    with pytest.raises(HTTPException) as error:
        await submit("focused", {"maxSearchCalls": 20})
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "mode_budget_invalid"
    assert error.value.detail["message"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_question", "Changed original question"),
        ("normalized_question", "Changed normalized question"),
        ("report_requirements", ["Changed requirements"]),
    ],
)
@pytest.mark.parametrize("mode", [None, "deep"])
async def test_explicit_brief_frozen_and_legacy_brief_mutable(identity, field, value, mode):
    tenant, _ = identity
    run_id = uuid.UUID((await submit(mode))["runId"])

    async def change():
        async with tenant_session(str(tenant)) as session:
            await session.execute(
                update(ResearchRun).where(ResearchRun.id == run_id).values({field: value})
            )

    if mode is not None:
        with pytest.raises(IntegrityError, match="brief snapshot is immutable"):
            await change()
    else:
        await change()


async def test_idempotency_includes_mode_and_limits(identity):
    key = str(uuid.uuid4())
    first, second = await asyncio.gather(submit("focused", key=key), submit("focused", key=key))
    assert first == second
    for mode, overrides in [("deep", None), ("focused", {"maxSources": 1})]:
        with pytest.raises(HTTPException) as error:
            await submit(mode, overrides, key)
        assert error.value.status_code == 409


async def test_replay_uses_original_policy_after_deployment_change(identity, monkeypatch):
    key = str(uuid.uuid4())
    first = await submit("focused", key=key)
    monkeypatch.setitem(
        mode_policy.MODE_POLICIES,
        "research-mode-policy-v2-test",
        {
            "focused": (4, 120_000),
            "balanced": (8, 240_000),
            "deep": (16, 500_000),
        },
    )
    monkeypatch.setattr(mode_policy, "MODE_POLICY_VERSION", "research-mode-policy-v2-test")
    assert await submit("focused", key=key) == first
    fresh = await submit("focused")
    assert fresh["modePolicyVersion"] == "research-mode-policy-v2-test"
    assert fresh["budget"]["maxProviderOperations"] == 4


@pytest.mark.parametrize("mode", [None, "focused"])
async def test_run_snapshot_immutable_but_status_routing_mutable(identity, mode):
    tenant, _ = identity
    run_id = uuid.UUID((await submit(mode))["runId"])
    async with tenant_session(str(tenant)) as session:
        await session.execute(
            update(ResearchRun)
            .where(ResearchRun.id == run_id)
            .values(
                status="planning",
                model_routing={"fixture": "normal update"},
            )
        )
    with pytest.raises(IntegrityError, match="snapshot is immutable"):
        async with tenant_session(str(tenant)) as session:
            await session.execute(
                update(ResearchRun)
                .where(ResearchRun.id == run_id)
                .values(
                    mode="deep",
                    mode_policy_version="research-mode-policy-v1",
                )
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_sources", 1),
        ("max_wall_clock_ms", 1000),
        ("max_input_tokens", 500),
        ("max_output_tokens", 500),
        ("max_estimated_cost_usd", Decimal("1")),
        ("max_reflection_rounds", 0),
    ],
)
async def test_explicit_budget_snapshot_is_immutable(identity, field, value):
    tenant, _ = identity
    run_id = uuid.UUID((await submit("deep"))["runId"])
    with pytest.raises(IntegrityError, match="budget snapshot is immutable"):
        async with tenant_session(str(tenant)) as session:
            await session.execute(
                update(Budget).where(Budget.run_id == run_id).values({field: value})
            )


async def test_legacy_budget_remains_mutable(identity):
    tenant, _ = identity
    run_id = uuid.UUID((await submit())["runId"])
    async with tenant_session(str(tenant)) as session:
        await session.execute(
            update(Budget).where(Budget.run_id == run_id).values(max_search_calls=2)
        )


async def test_operations_share_existing_reservation_ledger(identity):
    tenant, _ = identity
    run_id = uuid.UUID(
        (await submit("deep", {"maxProviderOperations": 2, "maxSources": 6}))["runId"]
    )
    async with tenant_session(str(tenant)) as session:
        repository = BudgetReservationRepository(session, tenant)
        for index in range(2):
            await repository.reserve(
                run_id=run_id,
                provider="fixture",
                operation="search",
                request_fingerprint=f"op-{index}",
                estimated_cost_usd=Decimal("0"),
            )
        with pytest.raises(BudgetExceededError):
            await repository.reserve(
                run_id=run_id,
                provider="fixture",
                operation="extract",
                request_fingerprint="op-exhausted",
                estimated_cost_usd=Decimal("0"),
            )
    projection = await api.get_research_run(run_id)
    assert projection["usage"]["reservedProviderOperations"] == 2


async def test_retry_inherits_frozen_snapshot(identity):
    tenant, _ = identity
    run_id = uuid.UUID(
        (await submit("deep", {"maxProviderOperations": 2, "maxSources": 1}))["runId"]
    )
    async with tenant_session(str(tenant)) as session:
        await session.execute(
            update(ResearchRun).where(ResearchRun.id == run_id).values(status="failed")
        )
    with pytest.raises(HTTPException) as error:
        await api.retry_research_run(run_id, SimpleNamespace(), max_wall_clock_ms=700_000)
    assert error.value.status_code == 422
    response = await api.retry_research_run(run_id, SimpleNamespace())
    projection = await api.get_research_run(uuid.UUID(response["runId"]))
    assert projection["mode"] == "deep"
    assert projection["modePolicyVersion"] == mode_policy.MODE_POLICY_VERSION
    assert projection["budget"]["maxProviderOperations"] == 2
    assert projection["sourceLimit"] == 1


async def test_followup_inherits_or_explicitly_changes_mode(identity):
    tenant, _ = identity
    run_id = uuid.UUID(
        (await submit("deep", {"maxProviderOperations": 2, "maxSources": 1}))["runId"]
    )
    async with tenant_session(str(tenant)) as session:
        report = Report(
            tenant_id=tenant,
            run_id=run_id,
            version=1,
            markdown="Local fixture",
            published=True,
        )
        session.add(report)
        await session.flush()
        run = await session.get(ResearchRun, run_id)
        run.status, run.report_id = "completed", report.id
    inherited = await api.followup_research_run(
        run_id,
        FollowupRequest(
            question="Explain another aspect",
            idempotencyKey=str(uuid.uuid4()),
        ),
        SimpleNamespace(),
    )
    projection = await api.get_research_run(uuid.UUID(inherited["runId"]))
    assert projection["mode"] == "deep" and projection["sourceLimit"] == 1
    key = str(uuid.uuid4())
    body = FollowupRequest(question="Explain another aspect", mode="focused", idempotencyKey=key)
    changed = await api.followup_research_run(run_id, body, SimpleNamespace())
    assert (await api.followup_research_run(run_id, body, SimpleNamespace()))["runId"] == changed[
        "runId"
    ]
    projection = await api.get_research_run(uuid.UUID(changed["runId"]))
    assert projection["mode"] == "focused" and projection["sourceLimit"] == 6
    with pytest.raises(HTTPException) as error:
        await api.followup_research_run(
            run_id, body.model_copy(update={"mode": "deep"}), SimpleNamespace()
        )
    assert error.value.status_code == 409


async def test_serper_route_is_pinned_at_enqueue(identity, monkeypatch):
    tenant, _ = identity
    monkeypatch.setattr(
        api, "get_settings", lambda: Settings(APP_ENV="test", SERPER_DISCOVERY_ENABLED=True)
    )
    run_id = uuid.UUID((await submit("focused"))["runId"])
    async with tenant_session(str(tenant)) as session:
        assert (
            await session.get(RuntimeJob, run_id)
        ).graph_version == PROTECTED_MODE_SERPER_GRAPH_VERSION


async def test_repository_resolves_absent_explicit_budget(identity):
    tenant, user = identity
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="What is gravity?",
            mode="deep",
        )
        budget = await session.scalar(select(Budget).where(Budget.run_id == run.id))
        assert run.mode_policy_version == mode_policy.MODE_POLICY_VERSION
        assert budget.max_sources == budget.max_provider_operations == budget.max_search_calls == 20
        assert budget.max_wall_clock_ms == 600_000


@pytest.mark.parametrize(
    "invalid",
    [
        RunBudgetDefaults(),
        replace(mode_policy.resolve_mode_budget("focused"), max_sources=7),
        replace(
            mode_policy.resolve_mode_budget("focused"),
            max_search_calls=7,
            max_provider_operations=7,
        ),
        replace(mode_policy.resolve_mode_budget("focused"), max_search_calls=5),
        replace(mode_policy.resolve_mode_budget("focused"), max_wall_clock_ms=180_001),
    ],
)
async def test_repository_rejects_incomplete_or_over_policy_snapshot(identity, invalid):
    tenant, user = identity
    with pytest.raises(ValueError):
        async with tenant_session(str(tenant)) as session:
            await RunRepository(session, tenant).create(
                user_id=user,
                question="Compare evidence",
                mode="focused",
                budget=invalid,
            )


async def test_migration_reapplication_is_idempotent(identity):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module("research_api.db.migrations.versions.0013_research_modes")
    engine = create_async_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        async with engine.connect() as connection:
            # Roll back schema locks/DDL; leave the shared schema untouched after the test.
            transaction = await connection.begin()

            def apply(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.upgrade()
                    migration.upgrade()

            await connection.run_sync(apply)
            await transaction.rollback()
    finally:
        await engine.dispose()


async def editable_explicit_plan(
    identity,
    monkeypatch,
    mode="deep",
    *,
    operations=4,
    sources=2,
    reflections=0,
    source_policy=False,
):
    tenant, user = identity
    initial = [
        {
            "question": "Explain the original evidence",
            "rationale": "Original rationale",
            "success_criteria": ["Find exact evidence"],
            "source_classes": ["primary"],
        }
    ]
    monkeypatch.setattr(
        runtime_api,
        "_caller",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id=tenant,
                user_id=user,
            )
        ),
    )
    async with tenant_session(str(tenant)) as session:
        selected = replace(
            mode_policy.resolve_mode_budget(mode),
            max_search_calls=operations,
            max_provider_operations=operations,
            max_sources=sources,
            max_reflection_rounds=reflections,
        )
        admission = planning_admission(selected, mode=mode)
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="Compare research systems",
            mode=mode,
            report_requirements=["Discuss recovery", "Discuss costs"],
            budget=selected,
            approval_required=True,
        )
        from research_api.jobs import enqueue

        await enqueue(session, run, Settings(APP_ENV="test"))
        coverage = attach_coverage_plan(
            run_id=run.id,
            question=run.original_question,
            requirements=run.report_requirements,
            questions=initial,
            mode=mode,
            policy_version=run.mode_policy_version,
            operations=operations,
            sources=sources,
            repair_operations=admission.repair_operations_reserved,
            repair_sources=admission.repair_sources_reserved,
        )
        original_payload = {"sub_questions": initial, "coverage": coverage.model_dump(mode="json")}
        if source_policy:
            original_payload["source_policy"] = {
                "kind": "official_documentation",
                "allowed_domains": ["docs.langchain.com"],
            }
        plan = ResearchPlan(tenant_id=tenant, run_id=run.id, plan_version=1, plan=original_payload)
        session.add(plan)
        await session.flush()
        session.add(
            SubQuestion(
                tenant_id=tenant,
                run_id=run.id,
                plan_id=plan.id,
                question=initial[0]["question"],
                payload=initial[0]
                | {
                    "planIndex": 0,
                    "dimensionIds": [str(key) for key in coverage.question_dimensions[0]],
                },
                status="pending",
                attempts=0,
            )
        )
        run.status, run.active_plan_id, run.plan_version = "awaiting_approval", plan.id, 1
        job = await session.get(RuntimeJob, run.id)
        job.state = "waiting"
        return tenant, run.id, plan.id, original_payload


@pytest.mark.parametrize("mode", ["focused", "deep"])
async def test_edit_explicit_plan_regenerates_coverage_and_question_associations(
    identity, monkeypatch, mode
):
    tenant, run_id, plan_id, original_payload = await editable_explicit_plan(
        identity, monkeypatch, mode, source_policy=True
    )
    edited_questions = ["How does restart recovery work?", "What are the operation costs?"]
    payload = runtime_api.EditResearchPlanRequest.model_validate(
        {
            "planId": str(plan_id),
            "expectedPlanVersion": 1,
            "questions": edited_questions,
        }
    )
    response = await runtime_api.edit_plan(run_id, payload)
    async with tenant_session(str(tenant)) as session:
        old = await session.get(ResearchPlan, plan_id)
        replacement = await session.get(ResearchPlan, response.plan_id)
        run = await session.get(ResearchRun, run_id)
        assert old.plan == original_payload
        assert replacement.parent_plan_version == 1 and replacement.plan_version == 2
        assert replacement.plan["source_policy"] == original_payload["source_policy"]
        assert run.active_plan_id == replacement.id
        assert run.report_requirements == ["Discuss recovery", "Discuss costs"]
        coverage = CoveragePlan.model_validate(replacement.plan["coverage"])
        original = CoveragePlan.model_validate(original_payload["coverage"])
        assert coverage.mode == mode and coverage.policy_version == run.mode_policy_version
        assert coverage.requirement_dimensions == original.requirement_dimensions
        old_task_ids = set(original.question_dimensions[0]) - {
            key for keys in original.requirement_dimensions.values() for key in keys
        }
        new_ids = {dimension.id for dimension in coverage.dimensions}
        assert not old_task_ids & new_ids
        assert {item.label for item in coverage.dimensions} >= set(edited_questions)
        assert coverage.operations_per_question == (2, 2)
        assert coverage.sources_per_question == (1, 1)
        assert coverage.repair_operations_reserved == 0
        questions = list(
            await session.scalars(
                select(SubQuestion).where(
                    SubQuestion.run_id == run_id,
                    SubQuestion.plan_id == response.plan_id,
                )
            )
        )
        questions.sort(key=lambda item: item.payload["planIndex"])
        assert [item.question for item in questions] == edited_questions
        assert [item.payload["dimensionIds"] for item in questions] == [
            [str(key) for key in ids] for ids in coverage.question_dimensions
        ]
        assert [item.payload["allowed_domains"] for item in questions] == [
            ["docs.langchain.com"]
        ] * len(questions)
        assert (
            len(
                list(
                    await session.scalars(
                        select(SubQuestion).where(
                            SubQuestion.run_id == run_id,
                            SubQuestion.plan_id == plan_id,
                        )
                    )
                )
            )
            == 1
        )
    with pytest.raises(HTTPException) as stale:
        await runtime_api.edit_plan(run_id, payload)
    assert stale.value.status_code == 409


@pytest.mark.parametrize(
    "questions",
    [
        ["Duplicated edited question", "Duplicated edited question"],
        ["First edited question", "Second edited question", "Third edited question"],
    ],
)
async def test_invalid_explicit_coverage_edit_preserves_active_plan(
    identity, monkeypatch, questions
):
    tenant, run_id, plan_id, original_payload = await editable_explicit_plan(identity, monkeypatch)
    with pytest.raises(HTTPException) as error:
        await runtime_api.edit_plan(
            run_id,
            runtime_api.EditResearchPlanRequest.model_validate(
                {
                    "planId": str(plan_id),
                    "expectedPlanVersion": 1,
                    "questions": questions,
                }
            ),
        )
    assert error.value.status_code == 422
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        assert run.active_plan_id == plan_id and run.plan_version == 1
        assert (await session.get(ResearchPlan, plan_id)).plan == original_payload
        plans = list(
            await session.scalars(select(ResearchPlan).where(ResearchPlan.run_id == run_id))
        )
        assert len(plans) == 1


async def test_edit_preserves_repair_reserve_and_projection_admission(identity, monkeypatch):
    monkeypatch.setattr(mode_planning, "EXPLICIT_REPAIR_ENABLED", True)
    tenant, run_id, plan_id, _ = await editable_explicit_plan(
        identity,
        monkeypatch,
        "focused",
        operations=6,
        sources=6,
        reflections=1,
    )
    projection = await api.get_research_run(run_id)
    assert projection["approval"]["maxQuestions"] == 2
    response = await runtime_api.edit_plan(
        run_id,
        runtime_api.EditResearchPlanRequest.model_validate(
            {
                "planId": str(plan_id),
                "expectedPlanVersion": 1,
                "questions": ["Explain the original evidence"],
            }
        ),
    )
    async with tenant_session(str(tenant)) as session:
        replacement = await session.get(ResearchPlan, response.plan_id)
        coverage = CoveragePlan.model_validate(replacement.plan["coverage"])
        assert coverage.repair_operations_reserved == 2
        assert coverage.repair_sources_reserved == 1
        assert coverage.sources_per_question == (5,)
        budget = await session.scalar(select(Budget).where(Budget.run_id == run_id))
        coverage.validate_budget(
            budget, mode="focused", policy_version=mode_policy.MODE_POLICY_VERSION
        )


@pytest.mark.parametrize(
    "mode,ceiling,maximum",
    [
        ("focused", 6, 3),
        ("balanced", 12, 4),
        ("deep", 20, 6),
    ],
)
async def test_disabled_repair_keeps_full_initial_capacity_in_edits_and_projection(
    identity, monkeypatch, mode, ceiling, maximum
):
    assert mode_planning.EXPLICIT_REPAIR_ENABLED is False
    tenant, run_id, plan_id, _ = await editable_explicit_plan(
        identity,
        monkeypatch,
        mode,
        operations=ceiling,
        sources=ceiling,
        reflections=1,
    )
    assert (await api.get_research_run(run_id))["approval"]["maxQuestions"] == maximum
    response = await runtime_api.edit_plan(
        run_id,
        runtime_api.EditResearchPlanRequest.model_validate(
            {
                "planId": str(plan_id),
                "expectedPlanVersion": 1,
                "questions": [f"Research initial dimension {index}" for index in range(maximum)],
            }
        ),
    )
    async with tenant_session(str(tenant)) as session:
        plan = await session.get(ResearchPlan, response.plan_id)
        coverage = CoveragePlan.model_validate(plan.plan["coverage"])
        assert coverage.repair_operations_reserved == coverage.repair_sources_reserved == 0
        assert len(coverage.sources_per_question) == maximum
        assert sum(coverage.sources_per_question) == ceiling


async def test_source_limited_edit_rejects_zero_slot_task_and_reports_same_maximum(
    identity, monkeypatch
):
    tenant, run_id, plan_id, original_payload = await editable_explicit_plan(
        identity,
        monkeypatch,
        operations=4,
        sources=1,
    )
    assert (await api.get_research_run(run_id))["approval"]["maxQuestions"] == 1
    with pytest.raises(HTTPException) as error:
        await runtime_api.edit_plan(
            run_id,
            runtime_api.EditResearchPlanRequest.model_validate(
                {
                    "planId": str(plan_id),
                    "expectedPlanVersion": 1,
                    "questions": ["Explain original evidence", "Discuss recovery costs"],
                }
            ),
        )
    assert error.value.status_code == 422
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        assert run.active_plan_id == plan_id
        assert (await session.get(ResearchPlan, plan_id)).plan == original_payload


async def test_explicit_budget_cannot_be_deleted_and_replaced(identity):
    tenant, _ = identity
    run_id = uuid.UUID((await submit("focused"))["runId"])
    with pytest.raises(IntegrityError, match="budget snapshot is immutable"):
        async with tenant_session(str(tenant)) as session:
            await session.execute(delete(Budget).where(Budget.run_id == run_id))
    async with tenant_session(str(tenant)) as session:
        budget = await session.scalar(select(Budget).where(Budget.run_id == run_id))
        assert budget.max_sources == 6 and budget.max_provider_operations == 6


async def test_table_owner_can_erase_explicit_fixture_in_foreign_key_order(identity):
    tenant, _ = identity
    run_id = uuid.UUID((await submit("deep"))["runId"])
    # The runtime role cannot use the retention exception, even within its tenant.
    with pytest.raises(IntegrityError, match="budget snapshot is immutable"):
        async with tenant_session(str(tenant)) as session:
            await session.execute(delete(Budget).where(Budget.run_id == run_id))
    engine = create_async_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            assert await session.scalar(
                text(
                    "SELECT current_user = pg_catalog.pg_get_userbyid(relowner) "
                    "FROM pg_catalog.pg_class WHERE oid = 'public.budgets'::regclass"
                )
            )
            for model in (
                RunEvent,
                RuntimeJob,
                UsageLedger,
                Budget,
                ResearchRun,
                DispatchRegistry,
                User,
            ):
                await session.execute(delete(model).where(model.tenant_id == tenant))
            await session.execute(delete(Tenant).where(Tenant.id == tenant))
            assert await session.scalar(select(Budget).where(Budget.run_id == run_id)) is None
            assert await session.get(ResearchRun, run_id) is None
    finally:
        await engine.dispose()


async def test_table_owner_erasure_exception_does_not_allow_snapshot_updates(identity):
    run_id = uuid.UUID((await submit("deep"))["runId"])
    engine = create_async_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with pytest.raises(IntegrityError, match="budget snapshot is immutable"):
            async with async_sessionmaker(engine)() as session, session.begin():
                await session.execute(
                    update(Budget).where(Budget.run_id == run_id).values(max_sources=1)
                )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("mode", [None, "deep"])
@pytest.mark.parametrize("field", ["run_id", "tenant_id", "id"])
async def test_budget_ownership_cannot_be_reassigned(identity, mode, field):
    tenant, _ = identity
    run_id = uuid.UUID((await submit(mode))["runId"])
    with pytest.raises(IntegrityError, match="budget ownership is immutable"):
        async with tenant_session(str(tenant)) as session:
            await session.execute(
                update(Budget).where(Budget.run_id == run_id).values({field: uuid.uuid4()})
            )


async def test_legacy_budget_delete_remains_allowed(identity):
    tenant, _ = identity
    run_id = uuid.UUID((await submit())["runId"])
    async with tenant_session(str(tenant)) as session:
        await session.execute(delete(Budget).where(Budget.run_id == run_id))
        assert await session.scalar(select(Budget).where(Budget.run_id == run_id)) is None
