import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import research_api.main as main
from research_api.config import Settings
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
        async def scalar(self, statement: object, params: dict[str, object] | None = None) -> bool:
            query = str(statement)
            State.queries.append(query)
            if "to_regclass('public.alembic_version')" in query:
                return True
            if "version_num >= :revision" in query:
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
    assert any("version_num >= :revision" in query for query in State.queries)
    assert "schema required" in error.value.detail


@pytest.mark.parametrize(("enforcement", "revision"), [(False, "0022"), (True, "0026")])
def test_readiness_succeeds_when_current_schema_is_present(
    monkeypatch: pytest.MonkeyPatch, enforcement: bool, revision: str
) -> None:
    queries: list[tuple[str, dict[str, object] | None]] = []

    class Connection:
        async def scalar(self, statement: object, params: dict[str, object] | None = None) -> bool:
            queries.append((str(statement), params))
            return True

    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()

    async def validate_role(_engine: object) -> None:
        return None

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "validate_runtime_role", validate_role)
    if enforcement:
        monkeypatch.setattr(
            main,
            "get_settings",
            lambda: Settings(BILLING_ENFORCEMENT_ENABLED=True),
        )

    assert asyncio.run(main.readiness())["status"] == "ok"
    assert any(
        "version_num >= :revision" in query and params == {"revision": revision}
        for query, params in queries
    )
    assert any(
        "billing_accounts" in query and "billing_periods" in query for query, _params in queries
    )


def test_stripe_readiness_requires_period_transition_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[tuple[str, dict[str, object] | None]] = []

    class Connection:
        async def scalar(self, statement: object, params: dict[str, object] | None = None) -> bool:
            queries.append((str(statement), params))
            return True

    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()

    async def validate_role(_engine: object) -> None:
        return None

    settings = Settings(
        APP_ENV="test",
        BILLING_STRIPE_ENABLED=True,
        BILLING_ENFORCEMENT_ENABLED=True,
        STRIPE_SECRET_KEY="sk_test_disposable",  # noqa: S106 - inert test fixture
        STRIPE_WEBHOOK_SECRET="whsec_disposable",  # noqa: S106 - inert test fixture
        STRIPE_API_VERSION="2026-10-19",
        STRIPE_PRICE_SCHOLAR_MONTHLY="price_scholar_disposable",
        STRIPE_PRICE_INVESTIGATOR_MONTHLY="price_investigator_disposable",
        STRIPE_PORTAL_CONFIGURATION_ID="bpc_disposable",
        BILLING_APP_BASE_URL="http://localhost:3000",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "validate_runtime_role", validate_role)

    assert asyncio.run(main.readiness())["status"] == "ok"
    assert any(
        "version_num >= :revision" in query and params == {"revision": "0028"}
        for query, params in queries
    )


def test_readiness_rejects_a_database_without_alembic_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        async def scalar(self, statement: object, params: dict[str, object] | None = None) -> bool:
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
    assert "0022" in error.value.detail


def test_readiness_rejects_a_database_behind_the_required_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        async def scalar(self, statement: object, params: dict[str, object] | None = None) -> bool:
            query = str(statement)
            if "to_regclass('public.alembic_version')" in query:
                return True
            if "version_num >= :revision" in query:
                return False
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
    assert "migrations through 0022" in error.value.detail
