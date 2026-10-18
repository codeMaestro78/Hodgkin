import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from sqlalchemy import inspect

from research_api import snapshots


def fake_session(failure=None):
    trace = []
    tenant, run = uuid4(), uuid4()
    timestamp = datetime.now(UTC)
    rows = [
        [
            {
                "id": uuid4(),
                "tenant_id": tenant,
                "run_id": run,
                "retrieved_at": timestamp,
                "quality_score": Decimal("0.7500"),
            }
        ]
    ] + [[]] * 7
    cursors = []

    class Cursor:
        def __init__(self, index):
            self.index = index
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True
            trace.append(("close", self.index))

        async def execute(self, query, params):
            trace.append(("execute", self.index, query, params))
            if failure == ("execute", self.index):
                raise ValueError("secret SQL and parameters")
            if failure == ("cancel", self.index):
                raise asyncio.CancelledError("secret SQL and parameters")

        async def fetchall(self):
            trace.append(("fetch", self.index))
            if failure == ("fetch", self.index):
                raise ValueError("secret SQL and parameters")
            return rows[self.index]

    @asynccontextmanager
    async def pipeline():
        trace.append(("enter",))
        yield
        trace.append(("sync",))
        if failure == ("sync", 0):
            raise ValueError("secret SQL and parameters")

    def cursor(*, row_factory):
        assert row_factory is dict_row
        result = Cursor(len(cursors))
        cursors.append(result)
        return result

    driver = MagicMock(spec=AsyncConnection)
    driver.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
    driver.cursor.side_effect = cursor
    driver.pipeline.side_effect = pipeline
    connection = SimpleNamespace(
        get_raw_connection=AsyncMock(return_value=SimpleNamespace(driver_connection=driver))
    )
    session = SimpleNamespace(connection=AsyncMock(return_value=connection))
    return session, driver, cursors, trace, tenant, run, rows


async def test_pipeline_queues_all_selects_before_fetching_and_keeps_native_values(caplog):
    session, driver, cursors, trace, tenant, run, rows = fake_session()
    with caplog.at_level(logging.DEBUG, logger="research_api.dependencies"):
        result = await snapshots.load_collections(session, tenant, run)
    executions = [item for item in trace if item[0] == "execute"]
    assert len(executions) == 8
    assert all(item[3] == (tenant, run) for item in executions)
    for execution, limit in zip(executions, (200, 16, 60, 32, 40, 20, 100, 40), strict=True):
        assert execution[2].startswith("SELECT ")
        assert "WHERE tenant_id = %s AND run_id = %s" in execution[2]
        assert execution[2].endswith(f"LIMIT {limit}")
    assert trace.index(("sync",)) < trace.index(("fetch", 0))
    assert all(cursor.closed for cursor in cursors)
    assert result.sources[0].id == rows[0][0]["id"]
    assert result.sources[0].retrieved_at is rows[0][0]["retrieved_at"]
    assert result.sources[0].quality_score is rows[0][0]["quality_score"]
    assert inspect(result.sources[0]).transient
    driver.commit.assert_not_called()
    driver.rollback.assert_not_called()
    driver.close.assert_not_called()
    event = next(
        json.loads(record.message)
        for record in caplog.records
        if '"operation": "db.snapshot.collections"' in record.message
    )
    assert event["queryCount"] == 8
    assert event["rowCount"] == 1
    assert event["pipelineMs"] >= 0
    assert event["fetchMs"] >= 0
    assert event["hydrationMs"] >= 0
    assert "SELECT" not in event


@pytest.mark.parametrize(
    "failure",
    [
        ("execute", 3),
        ("sync", 0),
        ("fetch", 4),
        ("cancel", 2),
        ("hydrate", 0),
    ],
)
async def test_failure_closes_every_cursor_and_logs_only_safe_facts(failure, caplog):
    session, driver, cursors, trace, tenant, run, rows = fake_session(failure)
    if failure[0] == "hydrate":
        rows[0][0]["unknown_column"] = "secret SQL and parameters"
    expected = (
        asyncio.CancelledError
        if failure[0] == "cancel"
        else (TypeError if failure[0] == "hydrate" else ValueError)
    )
    with pytest.raises(expected):
        await snapshots.load_collections(session, tenant, run)
    assert len(cursors) == 8
    assert all(cursor.closed for cursor in cursors)
    assert "db.snapshot.collections" in caplog.text
    assert "secret" not in caplog.text
    assert str(tenant) not in caplog.text
    assert str(run) not in caplog.text
    assert "SELECT" not in caplog.text
    driver.rollback.assert_not_called()


async def test_unsupported_driver_fails_without_fallback(caplog):
    connection = SimpleNamespace(
        get_raw_connection=AsyncMock(return_value=SimpleNamespace(driver_connection=object()))
    )
    session = SimpleNamespace(connection=AsyncMock(return_value=connection))
    with pytest.raises(TypeError, match="psycopg"):
        await snapshots.load_collections(session, uuid4(), uuid4())
    assert "db.snapshot.collections" in caplog.text


async def test_no_database_transaction_is_rejected_before_any_queries():
    session, driver, cursors, trace, tenant, run, rows = fake_session()
    driver.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(RuntimeError, match="existing database transaction"):
        await snapshots.load_collections(session, tenant, run)
    assert not cursors


async def test_cursor_creation_failure_closes_previously_created_cursors():
    session, driver, cursors, trace, tenant, run, rows = fake_session()
    create_cursor = driver.cursor.side_effect

    def fail_fourth_cursor(**kwargs):
        if len(cursors) == 3:
            raise ValueError("secret SQL and parameters")
        return create_cursor(**kwargs)

    driver.cursor.side_effect = fail_fourth_cursor
    with pytest.raises(ValueError):
        await snapshots.load_collections(session, tenant, run)
    assert len(cursors) == 3
    assert all(cursor.closed for cursor in cursors)
    driver.pipeline.assert_not_called()
