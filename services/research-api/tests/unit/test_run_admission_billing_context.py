import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api import api, runtime_api
from research_api.config import Settings
from research_api.mode_policy import MODE_POLICY_VERSION
from research_api.schemas.generated.batch_request import BatchRequest
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest
from research_api.schemas.generated.followup_request import FollowupRequest


@pytest.mark.asyncio
async def test_create_run_binds_authenticated_user_before_repository_admission(monkeypatch):
    tenant_id, user_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    session = SimpleNamespace(owner_user_id=None)

    async def execute(statement, parameters):
        if "app.user_id" in str(statement):
            session.owner_user_id = uuid.UUID(parameters["user_id"])

    session.execute = AsyncMock(side_effect=execute)

    @asynccontextmanager
    async def fake_tenant_session(_tenant_id):
        yield session

    class Repository:
        def __init__(self, bound_session, _tenant_id):
            self.session = bound_session

        async def create_once(self, **_kwargs):
            assert self.session.owner_user_id == user_id
            return (
                SimpleNamespace(
                    id=run_id,
                    mode="focused",
                    mode_policy_version=MODE_POLICY_VERSION,
                    original_question="What is a database?",
                ),
                True,
            )

    class Outbox:
        def __init__(self, *_args):
            pass

        async def append(self, **_kwargs):
            pass

    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(return_value=SimpleNamespace(tenant_id=tenant_id, user_id=user_id)),
    )
    monkeypatch.setattr(api, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(api, "RunRepository", Repository)
    monkeypatch.setattr(api, "EventOutbox", Outbox)
    monkeypatch.setattr(api, "enqueue", AsyncMock())
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: Settings(BILLING_ENFORCEMENT_ENABLED=True),
    )

    response = await api.create_research_run(
        CreateResearchRunRequest(
            question="What is a database?",
            mode="focused",
            idempotencyKey="user-context-regression",
        ),
        SimpleNamespace(),
    )

    assert response["runId"] == str(run_id)
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_retry_binds_authenticated_user_before_billing_admission(monkeypatch):
    tenant_id, user_id, prior_id, fresh_id = (uuid.uuid4() for _ in range(4))
    session = SimpleNamespace(owner_user_id=None, scalar=AsyncMock())

    async def execute(statement, parameters):
        if "app.user_id" in str(statement):
            session.owner_user_id = uuid.UUID(parameters["user_id"])

    session.execute = AsyncMock(side_effect=execute)
    session.scalar.side_effect = [
        SimpleNamespace(
            id=prior_id,
            status="failed",
            mode="focused",
            mode_policy_version=MODE_POLICY_VERSION,
            original_question="What is a database?",
            report_requirements=[],
            approval_required=False,
        ),
        SimpleNamespace(
            max_wall_clock_ms=180_000,
            max_search_calls=6,
            max_browser_sessions=6,
            max_reflection_rounds=1,
            max_input_tokens=10_000,
            max_output_tokens=10_000,
            max_estimated_cost_usd=0,
            max_provider_operations=6,
            max_sources=6,
        ),
    ]

    @asynccontextmanager
    async def fake_tenant_session(_tenant_id):
        yield session

    class Repository:
        def __init__(self, bound_session, _tenant_id):
            self.session = bound_session

        async def create(self, **_kwargs):
            assert self.session.owner_user_id == user_id
            return SimpleNamespace(id=fresh_id)

    class Outbox:
        def __init__(self, *_args):
            pass

        async def append(self, **_kwargs):
            pass

    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(return_value=SimpleNamespace(tenant_id=tenant_id, user_id=user_id)),
    )
    monkeypatch.setattr(api, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(api, "RunRepository", Repository)
    monkeypatch.setattr(api, "EventOutbox", Outbox)
    monkeypatch.setattr(api, "enqueue", AsyncMock())
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: Settings(BILLING_ENFORCEMENT_ENABLED=True),
    )

    response = await api.retry_research_run(prior_id, SimpleNamespace())

    assert response == {"runId": str(fresh_id), "status": "queued"}
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_followup_binds_authenticated_user_before_billing_admission(monkeypatch):
    tenant_id, user_id, prior_id, report_id, fresh_id = (uuid.uuid4() for _ in range(5))
    session = SimpleNamespace(owner_user_id=None, scalar=AsyncMock())

    async def execute(statement, parameters):
        if "app.user_id" in str(statement):
            session.owner_user_id = uuid.UUID(parameters["user_id"])

    session.execute = AsyncMock(side_effect=execute)
    session.scalar.side_effect = [
        SimpleNamespace(
            id=prior_id,
            status="completed",
            report_id=report_id,
            mode="focused",
            mode_policy_version=MODE_POLICY_VERSION,
            original_question="What is a database?",
            report_requirements=[],
            approval_required=False,
        ),
        SimpleNamespace(
            max_wall_clock_ms=180_000,
            max_search_calls=6,
            max_browser_sessions=6,
            max_reflection_rounds=1,
            max_input_tokens=10_000,
            max_output_tokens=10_000,
            max_estimated_cost_usd=0,
            max_provider_operations=6,
            max_sources=6,
        ),
    ]

    @asynccontextmanager
    async def fake_tenant_session(_tenant_id):
        yield session

    class Repository:
        def __init__(self, bound_session, _tenant_id):
            self.session = bound_session

        async def get_by_idempotency_key(self, **_kwargs):
            return None

        async def create_once(self, **_kwargs):
            assert self.session.owner_user_id == user_id
            return SimpleNamespace(id=fresh_id), True

    class Outbox:
        def __init__(self, *_args):
            pass

        async def append(self, **_kwargs):
            pass

    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(return_value=SimpleNamespace(tenant_id=tenant_id, user_id=user_id)),
    )
    monkeypatch.setattr(api, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(api, "lock_registry", AsyncMock())
    monkeypatch.setattr(api, "RunRepository", Repository)
    monkeypatch.setattr(api, "EventOutbox", Outbox)
    monkeypatch.setattr(api, "enqueue", AsyncMock())
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: Settings(BILLING_ENFORCEMENT_ENABLED=True),
    )

    response = await api.followup_research_run(
        prior_id,
        FollowupRequest(question="Explain the trade-offs", idempotencyKey="followup-user-context"),
        SimpleNamespace(),
    )

    assert response == {"runId": str(fresh_id), "status": "queued"}
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_batch_binds_authenticated_user_before_billing_admission(monkeypatch):
    tenant_id, user_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    registry = SimpleNamespace(next_due_at=None)
    session = SimpleNamespace(
        owner_user_id=None,
        scalar=AsyncMock(return_value=None),
        add=lambda _item: None,
        flush=AsyncMock(),
    )

    async def execute(statement, parameters):
        if "app.user_id" in str(statement):
            session.owner_user_id = uuid.UUID(parameters["user_id"])

    session.execute = AsyncMock(side_effect=execute)

    @asynccontextmanager
    async def fake_tenant_session(_tenant_id):
        yield session

    class Repository:
        def __init__(self, bound_session, _tenant_id):
            self.session = bound_session

        async def create_once(self, **_kwargs):
            assert self.session.owner_user_id == user_id
            return SimpleNamespace(id=run_id), True

    class Outbox:
        def __init__(self, *_args):
            pass

        async def append(self, **_kwargs):
            pass

    monkeypatch.setattr(
        runtime_api,
        "_caller",
        AsyncMock(return_value=SimpleNamespace(tenant_id=tenant_id, user_id=user_id)),
    )
    monkeypatch.setattr(runtime_api, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(runtime_api, "lock_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(runtime_api, "RunRepository", Repository)
    monkeypatch.setattr(runtime_api, "EventOutbox", Outbox)
    monkeypatch.setattr(runtime_api, "enqueue", AsyncMock())
    monkeypatch.setattr(
        runtime_api,
        "get_settings",
        lambda: Settings(BILLING_ENFORCEMENT_ENABLED=True),
    )

    response = await runtime_api.create_batch(
        BatchRequest(
            questions=["What is a database?"],
            idempotencyKey="batch-user-context-key",
            mode="focused",
        )
    )

    assert response["runIds"] == [str(run_id)]
    assert session.execute.await_count == 1
