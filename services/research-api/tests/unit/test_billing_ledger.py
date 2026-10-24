import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from research_api.billing.catalog import BILLING_CATALOG
from research_api.billing.ledger import (
    BillingConfigurationUnavailable,
    adjust_units,
    ensure_period_grant,
)
from research_api.config import Settings
from research_api.db.models import Budget, ResearchRun
from research_api.mode_policy import MODE_POLICY_VERSION, resolve_mode_budget
from research_api.repositories.runs import RunBudgetDefaults, RunRepository


async def test_unknown_catalog_cannot_create_a_period_grant():
    session = AsyncMock()

    with pytest.raises(BillingConfigurationUnavailable):
        await ensure_period_grant(
            session,
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            plan_key="scholar",
            catalog_version=BILLING_CATALOG.version,
            starts_at=datetime(2026, 10, 1, tzinfo=UTC),
            ends_at=datetime(2026, 11, 1, tzinfo=UTC),
            approved_catalogs={},
        )

    session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("delta", "actor_id", "reason"),
    [
        (0, uuid.uuid4(), "correction"),
        (1, uuid.UUID(int=0), "correction"),
        (1, uuid.uuid4(), " "),
        (1, uuid.uuid4(), "x" * 501),
        (1, uuid.uuid4(), None),
    ],
)
async def test_adjustment_rejects_invalid_or_unauditable_requests(delta, actor_id, reason):
    with pytest.raises(ValueError):
        await adjust_units(
            AsyncMock(),
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            period_id=uuid.uuid4(),
            delta=delta,
            idempotency_key="adjustment:test",
            actor_id=actor_id,
            reason=reason,
        )


async def test_adjustment_requires_actor_and_reason_arguments():
    with pytest.raises(TypeError):
        await adjust_units(
            AsyncMock(),
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            period_id=uuid.uuid4(),
            delta=1,
            idempotency_key="adjustment:test",
        )


def test_adjustment_schema_requires_audit_fields():
    from research_api.db.models import BillingUnitEntry

    constraint = next(
        item
        for item in BillingUnitEntry.__table__.constraints
        if item.name == "ck_billing_adjustment_audit"
    )
    assert "actor_id IS NOT NULL" in str(constraint.sqltext)
    assert "reason IS NOT NULL" in str(constraint.sqltext)


@pytest.mark.parametrize(
    ("mode", "policy_version", "budget"),
    [
        ("focused", MODE_POLICY_VERSION, resolve_mode_budget("focused")),
        (None, None, RunBudgetDefaults()),
    ],
)
async def test_idempotent_replay_does_not_retroactively_reserve_units(
    monkeypatch, mode, policy_version, budget
):
    import research_api.repositories.runs as runs_module

    tenant_id, user_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    question = "Existing focused research"
    run = ResearchRun(
        id=run_id,
        tenant_id=tenant_id,
        user_id=user_id,
        original_question=question,
        report_requirements=[],
        parent_report_id=None,
        approval_required=False,
        mode=mode,
        mode_policy_version=policy_version,
    )
    stored_budget = Budget(tenant_id=tenant_id, run_id=run_id, **asdict(budget))

    class Session:
        def __init__(self):
            self.scalar_calls = 0

        async def scalar(self, _statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else stored_budget

    repository = RunRepository(Session(), tenant_id)
    repository.get_by_idempotency_key = AsyncMock(return_value=run)
    repository._reserve_billing_if_enabled = AsyncMock()
    monkeypatch.setattr(
        runs_module,
        "get_settings",
        lambda: Settings(BILLING_ENFORCEMENT_ENABLED=True),
    )

    replayed, created = await repository.create_once(
        user_id=user_id,
        question=question,
        idempotency_key="existing-run-replay",
        budget=budget,
        mode=mode,
        mode_policy_version=policy_version,
    )

    assert replayed is run
    assert created is False
    repository._reserve_billing_if_enabled.assert_not_awaited()


async def test_internal_unmetered_user_skips_only_unit_reservation(monkeypatch):
    user_id = uuid.uuid4()
    repository = RunRepository(AsyncMock(), uuid.uuid4())
    run = SimpleNamespace(id=uuid.uuid4(), mode="deep")
    settings = Settings(
        _env_file=None,
        BILLING_ENFORCEMENT_ENABLED=True,
        BILLING_INTERNAL_UNMETERED_USER_IDS={user_id},
    )
    monkeypatch.setattr("research_api.repositories.runs.get_settings", lambda: settings)
    monkeypatch.setattr("research_api.telemetry.operation_event", Mock())

    await repository._reserve_billing_if_enabled(run, user_id, "request-key-123", settings)

    repository._session.execute.assert_not_awaited()
