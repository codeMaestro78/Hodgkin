import importlib.util
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from research_api import api


def _load_migration():
    path = (
        Path(__file__).parents[2]
        / "src/research_api/db/migrations/versions/0032_research_history_controls.py"
    )
    spec = importlib.util.spec_from_file_location("research_history_controls_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_history_controls_migration_adds_soft_delete_and_partial_owner_order_index(monkeypatch):
    migration = _load_migration()
    statements: list[str] = []

    class Operations:
        def execute(self, statement):
            statements.append(str(statement))

    monkeypatch.setattr(migration, "op", Operations())
    migration.upgrade()
    sql = "\n".join(statements)

    assert migration.revision == "0032"
    assert migration.down_revision == "0031"
    assert "ADD COLUMN IF NOT EXISTS pinned_at timestamptz" in sql
    assert "ADD COLUMN IF NOT EXISTS deleted_at timestamptz" in sql
    assert "WHERE deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_pin_is_owner_scoped_locked_and_persisted(monkeypatch):
    tenant, user, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run = SimpleNamespace(id=run_id, pinned_at=None, deleted_at=None)
    queries = []

    class Session:
        async def scalar(self, query):
            queries.append(str(query.compile(dialect=postgresql.dialect())))
            return run

    @asynccontextmanager
    async def session_scope(_tenant):
        yield Session()

    async def caller(*args, **kwargs):
        return SimpleNamespace(tenant_id=tenant, user_id=user)

    monkeypatch.setattr(api, "_caller", caller)
    monkeypatch.setattr(api, "get_settings", lambda: object())
    monkeypatch.setattr(api, "tenant_session", session_scope)

    pinned = await api.set_research_run_pin(run_id, api.PinResearchRunRequest(pinned=True))
    assert pinned == {"runId": str(run_id), "pinned": True}
    assert run.pinned_at is not None
    sql = queries[0]
    assert "research_runs.tenant_id" in sql
    assert "research_runs.user_id" in sql
    assert "research_runs.deleted_at IS NULL" in sql
    assert "FOR UPDATE" in sql

    unpinned = await api.set_research_run_pin(run_id, api.PinResearchRunRequest(pinned=False))
    assert unpinned["pinned"] is False
    assert run.pinned_at is None


@pytest.mark.asyncio
async def test_delete_rejects_active_runs_without_mutation(monkeypatch):
    run = SimpleNamespace(status="researching", deleted_at=None, pinned_at=None)

    class Session:
        async def scalar(self, _query):
            return run

        async def execute(self, _query):
            raise AssertionError("active runs must not revoke or mutate artifacts")

    @asynccontextmanager
    async def session_scope(_tenant):
        yield Session()

    async def caller(*args, **kwargs):
        return SimpleNamespace(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())

    async def set_context(*args):
        return None

    monkeypatch.setattr(api, "_caller", caller)
    monkeypatch.setattr(api, "get_settings", lambda: object())
    monkeypatch.setattr(api, "tenant_session", session_scope)
    monkeypatch.setattr(api, "set_user_context", set_context)

    with pytest.raises(api.HTTPException) as error:
        await api.delete_research_run(uuid.uuid4())
    assert error.value.status_code == 409
    assert run.deleted_at is None


@pytest.mark.asyncio
async def test_delete_tombstones_terminal_run_and_revokes_shares(monkeypatch):
    tenant, user, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run = SimpleNamespace(
        id=run_id, status="completed", deleted_at=None, pinned_at=datetime.now(UTC)
    )
    executed = []

    class Session:
        async def scalar(self, _query):
            return run

        async def execute(self, query):
            executed.append(str(query.compile(dialect=postgresql.dialect())))

    @asynccontextmanager
    async def session_scope(_tenant):
        yield Session()

    async def caller(*args, **kwargs):
        return SimpleNamespace(tenant_id=tenant, user_id=user)

    async def set_context(*args):
        return None

    monkeypatch.setattr(api, "_caller", caller)
    monkeypatch.setattr(api, "get_settings", lambda: object())
    monkeypatch.setattr(api, "tenant_session", session_scope)
    monkeypatch.setattr(api, "set_user_context", set_context)

    assert await api.delete_research_run(run_id) is None
    assert run.deleted_at is not None
    assert run.pinned_at is None
    assert len(executed) == 1
    assert "report_shares" in executed[0]
    assert "revoked_at" in executed[0]
