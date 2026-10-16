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
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import api, mode_policy
from research_api.config import Settings
from research_api.db.models import Budget, Report, ResearchRun, RuntimeJob, Source, Tenant, User
from research_api.db.session import tenant_session
from research_api.jobs import MODE_GRAPH_VERSION, MODE_SERPER_GRAPH_VERSION
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
        ("focused", 6, 6, 180_000),
        ("balanced", 12, 12, 300_000),
        ("deep", 20, 20, 600_000),
    ],
)
async def test_explicit_admission_projection_and_job(identity, mode, operations, sources, wall):
    tenant, _ = identity
    response = await submit(mode)
    run_id = uuid.UUID(response["runId"])
    assert response["mode"] == mode
    assert response["modePolicyVersion"] == "research-mode-policy-v1"
    assert response["budget"]["maxProviderOperations"] == operations
    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        budget = await session.scalar(select(Budget).where(Budget.run_id == run_id))
        job = await session.get(RuntimeJob, run_id)
        assert (run.mode, run.mode_policy_version) == (mode, "research-mode-policy-v1")
        assert (
            budget.max_search_calls,
            budget.max_provider_operations,
            budget.max_sources,
            budget.max_wall_clock_ms,
        ) == (operations, operations, sources, wall)
        assert job.graph_version == MODE_GRAPH_VERSION
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
    assert projection["modePolicyVersion"] == "research-mode-policy-v1"
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
        assert (await session.get(RuntimeJob, run_id)).graph_version == MODE_SERPER_GRAPH_VERSION


async def test_repository_resolves_absent_explicit_budget(identity):
    tenant, user = identity
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="What is gravity?",
            mode="deep",
        )
        budget = await session.scalar(select(Budget).where(Budget.run_id == run.id))
        assert run.mode_policy_version == "research-mode-policy-v1"
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
