from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from langgraph.errors import GraphInterrupt


def _state() -> dict[str, str]:
    return {
        "tenant_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
    }


async def test_tracked_node_records_normal_completion_with_existing_identity(monkeypatch):
    from research_api.graph.node_runtime import tracked_node

    task_id = uuid.uuid4()
    started = AsyncMock(return_value=task_id)
    finished = AsyncMock()
    cancel = AsyncMock(return_value=False)
    handler = AsyncMock(return_value={"source_ids": ["source-1"]})
    node = tracked_node(
        "research_worker",
        handler,
        cancel_if_requested=cancel,
        start_node=started,
        finish_node=finished,
    )

    state = _state()
    result = await node(state)
    assert result == {"source_ids": ["source-1"]}
    cancel.assert_any_await(
        tenant_id=uuid.UUID(state["tenant_id"]), run_id=uuid.UUID(state["run_id"])
    )
    started.assert_awaited_once_with(
        uuid.UUID(state["tenant_id"]), uuid.UUID(state["run_id"]), "research_worker"
    )
    finished.assert_awaited_once_with(
        uuid.UUID(state["tenant_id"]), uuid.UUID(state["run_id"]), task_id, "completed"
    )


async def test_tracked_node_preserves_approval_interrupt_and_does_not_mark_failed(monkeypatch):
    from research_api.graph.node_runtime import tracked_node

    task_id = uuid.uuid4()
    started = AsyncMock(return_value=task_id)
    finished = AsyncMock()
    cancel = AsyncMock(return_value=False)

    async def interrupting_handler(_state):
        raise GraphInterrupt([])

    node = tracked_node(
        "approval_gate",
        interrupting_handler,
        cancel_if_requested=cancel,
        start_node=started,
        finish_node=finished,
    )
    with pytest.raises(GraphInterrupt):
        await node(_state())
    assert finished.await_args.args[-1] == "paused"


async def test_tracked_node_skips_handler_when_cancellation_was_persisted():
    from research_api.graph.node_runtime import tracked_node

    handler = AsyncMock()
    started = AsyncMock()
    finished = AsyncMock()
    node = tracked_node(
        "planner",
        handler,
        cancel_if_requested=AsyncMock(return_value=True),
        start_node=started,
        finish_node=finished,
    )
    assert await node(_state()) == {"expand": False}
    handler.assert_not_awaited()
    started.assert_not_awaited()
    finished.assert_not_awaited()


async def test_tracked_node_marks_failure_and_reraises_original_exception():
    from research_api.graph.node_runtime import tracked_node

    task_id = uuid.uuid4()
    started = AsyncMock(return_value=task_id)
    finished = AsyncMock()
    error = RuntimeError("worker failed")
    node = tracked_node(
        "verifier",
        AsyncMock(side_effect=error),
        cancel_if_requested=AsyncMock(return_value=False),
        start_node=started,
        finish_node=finished,
    )
    with pytest.raises(RuntimeError) as caught:
        await node(_state())
    assert caught.value is error
    assert finished.await_args.args[-1] == "failed"
