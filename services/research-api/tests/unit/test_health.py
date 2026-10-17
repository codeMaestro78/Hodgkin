import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import research_api.main as main
from research_api.main import app


def test_health_alias_matches_liveness() -> None:
    client = TestClient(app)

    assert client.get("/health").json() == {
        "status": "ok",
        "service": "research-api",
    }
    assert client.get("/health/live").json() == {
        "status": "ok",
        "service": "research-api",
    }


def test_readiness_requires_current_schema_and_model_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class State:
        queries: list[str] = []

    class Connection:
        async def scalar(self, statement: object) -> bool:
            query = str(statement)
            State.queries.append(query)
            if "to_regclass('public.alembic_version')" in query:
                return True
            if "version_num >= '0019'" in query:
                return True
            return False

    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()

    async def validate_role(_engine: object) -> None:
        return None

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "validate_runtime_role", validate_role)

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.readiness())

    assert error.value.status_code == 503
    assert any("model_routing" in query and "research_runs" in query for query in State.queries)
    assert any("version_num >= '0019'" in query for query in State.queries)
    assert "schema required" in error.value.detail


def test_readiness_succeeds_when_current_schema_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []

    class Connection:
        async def scalar(self, statement: object) -> bool:
            queries.append(str(statement))
            return True

    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()

    async def validate_role(_engine: object) -> None:
        return None

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "validate_runtime_role", validate_role)

    assert asyncio.run(main.readiness())["status"] == "ok"
    assert any("version_num >= '0019'" in query for query in queries)


def test_readiness_rejects_a_database_without_alembic_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        async def scalar(self, statement: object) -> bool:
            return "to_regclass('public.alembic_version')" in str(statement)

    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()

    async def validate_role(_engine: object) -> None:
        return None

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "validate_runtime_role", validate_role)

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.readiness())

    assert error.value.status_code == 503
    assert "0019" in error.value.detail


def test_readiness_rejects_a_database_behind_the_required_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        async def scalar(self, statement: object) -> bool:
            return "to_regclass('public.alembic_version')" in str(statement)

    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()

    async def validate_role(_engine: object) -> None:
        return None

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "validate_runtime_role", validate_role)

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.readiness())

    assert error.value.status_code == 503
    assert "migrations through 0019" in error.value.detail
