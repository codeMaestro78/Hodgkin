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


def test_readiness_requires_model_routing_column(monkeypatch: pytest.MonkeyPatch) -> None:
    class State:
        query = ""

    class Connection:
        async def scalar(self, statement: object) -> bool:
            State.query = str(statement)
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
    assert "model_routing" in State.query
    assert "research_runs" in State.query
    assert "0012" in error.value.detail


def test_readiness_succeeds_when_current_schema_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        async def scalar(self, _statement: object) -> bool:
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
