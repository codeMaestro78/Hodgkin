import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from research_api.config import Settings
from research_api.db.models import ResearchRun
from research_api.mode_policy import MODE_POLICY_VERSION, resolve_mode_budget
from research_api.repositories import runs as run_repository


@asynccontextmanager
async def _nested_transaction():
    yield


def test_shadow_accounting_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BILLING_SHADOW_ACCOUNTING_ENABLED", raising=False)
    assert Settings(_env_file=None).BILLING_SHADOW_ACCOUNTING_ENABLED is False


def test_shadow_constraint_accepts_the_current_catalog_snapshot():
    from research_api.db.models import BillingShadowObservation

    constraint = next(
        item
        for item in BillingShadowObservation.__table__.constraints
        if item.name == "ck_billing_shadow_decision_shape"
    )
    assert "research-units-v1-2026-10-19" in str(constraint.sqltext)
    assert "research-units-v3-2026-10-22" in str(constraint.sqltext)


@pytest.mark.parametrize(
    ("mode", "status", "units", "policy_version"),
    [
        ("focused", "provisional", 1, "approved-mode-weights-1-2-4-v1"),
        ("balanced", "provisional", 2, "approved-mode-weights-1-2-4-v1"),
        ("deep", "provisional", 4, "approved-mode-weights-1-2-4-v1"),
        (None, "unpriced_legacy_mode", None, None),
    ],
)
def test_shadow_observation_is_a_non_authoritative_mode_snapshot(
    mode, status, units, policy_version
):
    from research_api.billing.shadow import build_shadow_observation

    tenant, user, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    row = build_shadow_observation(tenant_id=tenant, user_id=user, run_id=run_id, mode=mode)

    assert row.tenant_id == tenant and row.user_id == user and row.run_id == run_id
    assert row.mode == mode
    assert row.decision_status == status
    assert row.proposed_units == units
    assert row.policy_version == policy_version
    assert row.catalog_version == ("research-units-v3-2026-10-22" if mode is not None else None)


@pytest.mark.parametrize("enabled", [False, True])
async def test_run_creation_records_shadow_once_only_when_enabled(monkeypatch, enabled):
    tenant, user, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    created_run = ResearchRun(
        id=run_id,
        tenant_id=tenant,
        user_id=user,
        status="queued",
        original_question="A bounded question",
        normalized_question="A bounded question",
        thread_id=f"run:{run_id}",
        mode="balanced",
        mode_policy_version=MODE_POLICY_VERSION,
    )
    session = AsyncMock()
    session.add_all = Mock()
    session.add = Mock()
    session.begin_nested = Mock(side_effect=_nested_transaction)
    session.scalar.return_value = created_run
    session.flush.return_value = None
    monkeypatch.setattr(
        run_repository,
        "get_settings",
        lambda: SimpleNamespace(
            model_routing_snapshot=lambda: {},
            BILLING_SHADOW_ACCOUNTING_ENABLED=enabled,
            BILLING_ENFORCEMENT_ENABLED=False,
        ),
    )

    run, created = await run_repository.RunRepository(session, tenant).create_once(
        user_id=user,
        question="A bounded question",
        mode="balanced",
        mode_policy_version=MODE_POLICY_VERSION,
    )

    assert run is created_run and created
    additions = session.add_all.call_args.args[0]
    from research_api.db.models import BillingShadowObservation

    observations = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], BillingShadowObservation)
    ]
    assert len(observations) == int(enabled)
    if enabled:
        assert observations[0].run_id == additions[0].run_id
        assert observations[0].proposed_units == 2
        assert observations[0].catalog_version == "research-units-v3-2026-10-22"
        assert session.flush.await_args_list[1].args == ([observations[0]],)
        assert session.flush.await_count == 2
    else:
        session.flush.assert_awaited_once_with()


async def test_idempotent_replay_does_not_create_another_shadow_observation(monkeypatch):
    tenant, user, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    existing_run = ResearchRun(
        id=run_id,
        tenant_id=tenant,
        user_id=user,
        status="queued",
        original_question="A bounded question",
        normalized_question="A bounded question",
        report_requirements=[],
        thread_id=f"run:{run_id}",
        mode="focused",
        mode_policy_version=MODE_POLICY_VERSION,
        approval_required=False,
    )
    from research_api.db.models import Budget

    defaults = resolve_mode_budget("focused")
    stored_budget = Budget(
        tenant_id=tenant,
        run_id=run_id,
        max_wall_clock_ms=defaults.max_wall_clock_ms,
        max_search_calls=defaults.max_search_calls,
        max_provider_operations=defaults.max_provider_operations,
        max_sources=defaults.max_sources,
        max_browser_sessions=defaults.max_browser_sessions,
        max_reflection_rounds=defaults.max_reflection_rounds,
        max_input_tokens=defaults.max_input_tokens,
        max_output_tokens=defaults.max_output_tokens,
        max_estimated_cost_usd=defaults.max_estimated_cost_usd,
    )
    session = AsyncMock()
    session.add_all = Mock()
    session.scalar.side_effect = [existing_run, None, existing_run, stored_budget]
    monkeypatch.setattr(
        run_repository,
        "get_settings",
        lambda: SimpleNamespace(
            model_routing_snapshot=lambda: {},
            BILLING_SHADOW_ACCOUNTING_ENABLED=True,
            BILLING_ENFORCEMENT_ENABLED=False,
        ),
    )

    run, created = await run_repository.RunRepository(session, tenant).create_once(
        user_id=user,
        question="A bounded question",
        idempotency_key="same-request",
        mode="focused",
        mode_policy_version=MODE_POLICY_VERSION,
    )

    assert run is existing_run and not created
    session.add_all.assert_not_called()


async def test_shadow_write_failure_is_best_effort_and_does_not_reject_run(monkeypatch):
    from research_api.billing.shadow import (
        build_shadow_observation,
        persist_shadow_observation,
    )

    observation = build_shadow_observation(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        mode="focused",
    )
    session = AsyncMock()
    session.add = Mock()
    session.begin_nested = Mock(side_effect=_nested_transaction)
    session.flush.side_effect = SQLAlchemyError("table unavailable")
    monkeypatch.setattr("research_api.billing.shadow.operation_event", Mock())

    assert await persist_shadow_observation(session, observation) is False
    session.add.assert_called_once_with(observation)


def test_shadow_builder_rejects_unknown_explicit_mode():
    from research_api.billing.shadow import build_shadow_observation

    with pytest.raises(ValueError, match="unsupported explicit mode"):
        build_shadow_observation(
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            mode="unrecognized",
        )
