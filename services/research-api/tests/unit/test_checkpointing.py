"""Scope/fence regressions against the installed official saver interface."""

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, empty_checkpoint

import research_api.checkpointing as module
from research_api.checkpointing import (
    MAX_CHECKPOINT_BYTES,
    BoundedJsonPlusSerializer,
    CheckpointPayloadError,
    CheckpointScopeError,
    TenantPostgresSaver,
)
from research_api.runtime_context import JobFence, LeaseLostError, current_job


@pytest.fixture(autouse=True)
def clear_fence() -> Any:
    token = current_job.set(None)
    try:
        yield
    finally:
        current_job.reset(token)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    events: list[str] = []
    cursor = MagicMock()
    cursor.execute = AsyncMock(side_effect=lambda *args: events.append("authorize"))
    cursor.fetchone = AsyncMock(return_value={"status": "running"})
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.execute = AsyncMock(side_effect=lambda *args: events.append("settings"))

    @asynccontextmanager
    async def transaction() -> AsyncIterator[None]:
        events.append("begin")
        try:
            yield
        except BaseException:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    @asynccontextmanager
    async def connection() -> AsyncIterator[Any]:
        events.append("acquire")
        try:
            yield conn
        finally:
            events.append("release")

    conn.transaction.side_effect = transaction
    pool = MagicMock()
    pool.connection.side_effect = connection
    saver = TenantPostgresSaver(pool, uuid4(), uuid4())
    item = CheckpointTuple(saver.config(checkpoint_id="01"), empty_checkpoint(), {}, None, [])
    delegate = MagicMock()
    delegate.aget_tuple = AsyncMock(return_value=item)
    delegate.aput = AsyncMock(return_value=item.config)
    delegate.aput_writes = AsyncMock()
    delegate.adelete_thread = AsyncMock()
    delegate.aget_delta_channel_history = AsyncMock(return_value={})
    factory = MagicMock(return_value=delegate)
    monkeypatch.setattr(module, "AsyncPostgresSaver", factory)
    return SimpleNamespace(
        events=events,
        cursor=cursor,
        conn=conn,
        pool=pool,
        saver=saver,
        item=item,
        delegate=delegate,
        factory=factory,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("thread_id", "other:run"),
        ("checkpoint_ns", "other"),
        ("tenant_id", str(uuid4())),
        ("run_id", str(uuid4())),
    ],
)
async def test_cross_scope_denied_before_checkout(harness: Any, field: str, value: str) -> None:
    config = harness.saver.config()
    config["configurable"][field] = value
    with pytest.raises(CheckpointScopeError):
        await harness.saver.aget_tuple(config)
    assert harness.events == []


async def test_delegate_uses_same_connection_and_transaction(harness: Any) -> None:
    result = await harness.saver.aget(harness.saver.config())
    assert result == harness.item.checkpoint
    assert harness.events == ["acquire", "begin", "settings", "authorize", "commit", "release"]
    harness.factory.assert_called_once_with(harness.conn, serde=harness.saver.serde)
    sql, params = harness.conn.execute.call_args.args
    assert "research_checkpoints,public" in sql
    assert "true" in sql
    assert params == (str(harness.saver._tenant_id),)
    assert "public.research_runs" in harness.cursor.execute.call_args.args[0]


async def test_missing_run_denied_and_transaction_released(harness: Any) -> None:
    harness.cursor.fetchone.return_value = None
    with pytest.raises(CheckpointScopeError):
        await harness.saver.aget_tuple(harness.saver.config())
    harness.factory.assert_not_called()
    assert harness.events[-2:] == ["rollback", "release"]


@pytest.mark.parametrize("operation", ["read", "put", "writes", "delta", "delete"])
async def test_stale_fence_blocks_every_operation(harness: Any, operation: str) -> None:
    current_job.set(JobFence(harness.saver._tenant_id, harness.saver._run_id, uuid4(), 7))
    harness.cursor.fetchone.return_value = None
    config = harness.saver.config(checkpoint_id="01")
    with pytest.raises(LeaseLostError):
        match operation:
            case "read":
                await harness.saver.aget_tuple(config)
            case "put":
                await harness.saver.aput(config, empty_checkpoint(), {}, {})
            case "writes":
                await harness.saver.aput_writes(config, [("a", 1)], "task")
            case "delta":
                await harness.saver.aget_delta_channel_history(config=config, channels=["a"])
            case "delete":
                await harness.saver.adelete_thread(harness.saver.thread_id)
    sql, params = harness.cursor.execute.call_args.args
    assert "FOR SHARE" in sql and "clock_timestamp()" in sql and "state = 'running'" in sql
    assert params[-1] == 7
    harness.factory.assert_not_called()


async def test_valid_fence_precedes_run_authorization_and_writes(harness: Any) -> None:
    fence = JobFence(harness.saver._tenant_id, harness.saver._run_id, uuid4(), 3)
    current_job.set(fence)
    harness.cursor.fetchone.side_effect = [{"ok": 1}, {"status": "running"}]
    await harness.saver.aput_writes(harness.saver.config(checkpoint_id="01"), [("a", 1)], "t")
    calls = harness.cursor.execute.call_args_list
    assert "runtime_jobs" in calls[0].args[0]
    assert calls[0].args[1] == (fence.tenant_id, fence.run_id, fence.owner_id, fence.generation)
    assert "research_runs" in calls[1].args[0]
    harness.delegate.aput_writes.assert_awaited_once()


async def test_foreign_fence_denied_before_checkout(harness: Any) -> None:
    current_job.set(JobFence(uuid4(), harness.saver._run_id, uuid4(), 1))
    with pytest.raises(CheckpointScopeError):
        await harness.saver.aget_tuple(harness.saver.config())
    assert harness.events == []


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed", "cancelled"])
async def test_retention_only_accepts_terminal_runs(harness: Any, status: str) -> None:
    harness.cursor.fetchone.return_value = {"status": status}
    if status in module.TERMINAL_RUN_STATES:
        await harness.saver.adelete_thread(harness.saver.thread_id)
        harness.delegate.adelete_thread.assert_awaited_once_with(harness.saver.thread_id)
    else:
        with pytest.raises(CheckpointScopeError):
            await harness.saver.adelete_thread(harness.saver.thread_id)
        harness.delegate.adelete_thread.assert_not_awaited()


async def test_listing_is_scoped_and_releases_before_yield(harness: Any) -> None:
    async def listing(*args: Any, **kwargs: Any) -> AsyncIterator[CheckpointTuple]:
        yield harness.item

    harness.delegate.alist.side_effect = listing
    iterator = harness.saver.alist(None)
    assert await anext(iterator) == harness.item
    assert harness.events[-2:] == ["commit", "release"]
    harness.delegate.alist.assert_called_once_with(
        harness.saver.config(), filter=None, before=None, limit=module.MAX_LIST_PAGE
    )
    await iterator.aclose()


async def test_listing_validates_before_scope(harness: Any) -> None:
    before = {"configurable": {"thread_id": "foreign:run", "checkpoint_id": "x"}}
    with pytest.raises(CheckpointScopeError):
        await anext(harness.saver.alist(None, before=before))
    assert harness.events == []


@pytest.mark.parametrize("error", [RuntimeError("db failure"), asyncio.CancelledError()])
async def test_delegate_failure_rolls_back_and_releases(harness: Any, error: BaseException) -> None:
    harness.delegate.aget_tuple.side_effect = error
    with pytest.raises(type(error)):
        await harness.saver.aget_tuple(harness.saver.config())
    assert harness.events[-2:] == ["rollback", "release"]


@pytest.mark.parametrize("operation", ["checkpoint", "writes", "metadata", "inline_json"])
async def test_oversized_payload_denied_before_checkout(harness: Any, operation: str) -> None:
    checkpoint = empty_checkpoint()
    metadata: Any = {}
    config = harness.saver.config(checkpoint_id="01")
    with pytest.raises(CheckpointPayloadError):
        if operation == "writes":
            await harness.saver.aput_writes(config, [("a", "x" * MAX_CHECKPOINT_BYTES)], "t")
        else:
            if operation == "metadata":
                metadata = {"large": "x" * MAX_CHECKPOINT_BYTES}
            elif operation == "inline_json":
                checkpoint["channel_values"] = {"a": "\x01" * (MAX_CHECKPOINT_BYTES // 5)}
            else:
                checkpoint["channel_values"] = {"a": "x" * MAX_CHECKPOINT_BYTES}
            await harness.saver.aput(config, checkpoint, metadata, {})
    assert harness.events == []


def test_serde_is_strict_and_bounds_reads() -> None:
    serde = BoundedJsonPlusSerializer()
    assert serde.pickle_fallback is False
    assert serde._allowed_msgpack_modules is None
    assert serde._allowed_json_modules is None
    value = {"a": [1, True, None, "text"], "uuid": uuid4()}
    assert serde.loads_typed(serde.dumps_typed(value)) == value
    with pytest.raises(NotImplementedError):
        serde.loads_typed(("pickle", b"untrusted"))
    with pytest.raises(CheckpointPayloadError):
        serde.loads_typed(("msgpack", b"x" * (MAX_CHECKPOINT_BYTES + 1)))
    with pytest.raises(TypeError):
        serde.dumps_typed(object())


async def test_bulk_maintenance_is_denied(harness: Any) -> None:
    for operation in (
        harness.saver.acopy_thread("a", "b"),
        harness.saver.adelete_for_runs(["a"]),
        harness.saver.aprune(["a"]),
    ):
        with pytest.raises(CheckpointScopeError):
            await operation
    assert harness.events == []


def test_all_public_async_base_methods_are_explicitly_overridden() -> None:
    methods = {
        name
        for name, value in vars(BaseCheckpointSaver).items()
        if name.startswith("a")
        and (inspect.iscoroutinefunction(value) or inspect.isasyncgenfunction(value))
    }
    assert methods <= vars(TenantPostgresSaver).keys()


def test_versions_use_official_postgres_format(harness: Any) -> None:
    first = harness.saver.get_next_version(None, None)
    second = harness.saver.get_next_version(first, None)
    assert len(first.split(".")[0]) == 32
    assert int(second.split(".")[0]) == int(first.split(".")[0]) + 1
