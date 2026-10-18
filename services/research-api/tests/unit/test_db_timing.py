import json
import logging
from contextlib import asynccontextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.db import session as db


@pytest.mark.parametrize(
    "sql, expected",
    [
        (" SELECT secret_column FROM private_table", "SELECT"),
        ("WITH secret AS (SELECT 1) SELECT * FROM secret", "WITH"),
        ("/* private comment */ SELECT 1", "OTHER"),
        ("", "OTHER"),
    ],
)
def test_command_category_never_contains_sql(sql, expected):
    assert db.command_category(sql) == expected


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT * FROM runtime_jobs WHERE owner_id=:secret FOR UPDATE", "runtime_job_exclusive"),
        ("SELECT run_id FROM runtime_jobs FOR SHARE", "runtime_job_shared"),
        ("SELECT * FROM budgets FOR UPDATE", "budget_exclusive"),
        ("SELECT * FROM research_runs FOR UPDATE", "run_exclusive"),
        ("SELECT * FROM reports WHERE tenant_id=:tenant", "report"),
        ("WITH rows AS (SELECT * FROM citations) SELECT * FROM rows", "citation"),
        ('SELECT * FROM "sub_question_attempts"', "sub_question_attempt"),
        ("SELECT * FROM private_table WHERE token=:secret", "other"),
    ],
)
def test_slow_query_family_is_static_and_redacted(sql, expected):
    assert db.slow_query_family(sql) == expected


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("UPDATE runtime_jobs SET state='secret'", "runtime_job"),
        ("INSERT INTO provider_calls VALUES ('secret')", "provider_call"),
        ("DELETE FROM citations WHERE id='secret'", "citation"),
    ],
)
def test_query_family_covers_write_statements_without_exposing_values(sql, expected):
    assert db.query_family(sql) == expected


def test_detailed_statement_timing_is_opt_in_and_redacted(monkeypatch, caplog):
    detailed_settings = db.settings.model_copy(
        update={"DATABASE_QUERY_TIMING_ENABLED": True}
    )
    monkeypatch.setattr(db, "settings", detailed_settings)
    with caplog.at_level(logging.DEBUG, logger="research_api.dependencies"):
        db.statement_finish(
            None,
            None,
            "UPDATE runtime_jobs SET owner_id='secret'",
            {"owner": "secret"},
            SimpleNamespace(research_started=monotonic()),
            False,
        )
    record = json.loads(caplog.records[-1].message)
    assert record["operation"] == "db.statement.timing"
    assert record["commandCategory"] == "UPDATE"
    assert record["queryFamily"] == "runtime_job"
    assert "secret" not in caplog.text


def test_slow_statement_logs_category_without_sql_or_parameters(caplog):
    with caplog.at_level(logging.WARNING, logger="research_api.dependencies"):
        db.statement_finish(
            None,
            None,
            "SELECT secret",
            {"secret": "token"},
            SimpleNamespace(research_started=monotonic() - 61),
            False,
        )
    record = json.loads(caplog.records[-1].message)
    assert record["commandCategory"] == "SELECT"
    assert record["queryFamily"] == "other"
    assert "secret" not in caplog.text and "token" not in caplog.text


async def test_connection_timing_preserves_tenant_setup_order(monkeypatch, caplog):
    session = AsyncMock()
    session.info = {}
    order = []

    async def connection():
        order.append("connection")

    async def execute(statement, parameters):
        order.append("tenant")
        assert "set_config" in str(statement)
        assert parameters == {"tenant_id": "fixture-tenant"}

    session.connection.side_effect = connection
    session.execute.side_effect = execute

    @asynccontextmanager
    async def transaction():
        yield
        order.append("commit")

    @asynccontextmanager
    async def factory():
        yield session

    session.begin = transaction
    monkeypatch.setattr(db, "session_factory", factory)
    with caplog.at_level(logging.DEBUG, logger="research_api.dependencies"):
        async with db.tenant_session("fixture-tenant"):
            order.append("body")
    assert order == ["connection", "tenant", "body", "commit"]
    row = json.loads(caplog.records[-1].message)
    assert row["acquireMs"] >= 0
    assert row["setupMs"] >= row["acquireMs"]


def test_slow_connection_acquire_visible_at_default_level(caplog):
    from research_api.telemetry import operation_event

    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        operation_event("db.connection.acquire", started=monotonic())
        operation_event("db.connection.acquire", started=monotonic() - 2)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
