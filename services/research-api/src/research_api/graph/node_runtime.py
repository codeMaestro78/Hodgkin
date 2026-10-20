"""Cross-cutting lifecycle wrapper for durable LangGraph nodes."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from langgraph.errors import GraphInterrupt

from research_api.graph.state import RunState
from research_api.telemetry import operation_event

NodeHandler = Callable[[RunState], Awaitable[Any]]
CancelCheck = Callable[..., Awaitable[bool]]
NodeStarter = Callable[..., Awaitable[uuid.UUID]]
NodeFinisher = Callable[..., Awaitable[None]]


def tracked_node(
    name: str,
    function: NodeHandler,
    *,
    cancel_if_requested: CancelCheck,
    start_node: NodeStarter,
    finish_node: NodeFinisher,
) -> NodeHandler:
    """Wrap one node with persisted task lifecycle, cancellation, and timing.

    The wrapper owns orchestration bookkeeping only. Node behavior and the
    database transaction boundaries remain with the node implementation.
    """

    async def invoke(state: RunState) -> Any:
        started = monotonic()
        tenant_id = uuid.UUID(state["tenant_id"])
        run_id = uuid.UUID(state["run_id"])
        if await cancel_if_requested(tenant_id=tenant_id, run_id=run_id):
            return {"expand": False}
        task_id = await start_node(tenant_id, run_id, name)
        try:
            result = await function(state)
        except GraphInterrupt:
            await finish_node(tenant_id, run_id, task_id, "paused")
            raise
        except BaseException as exc:
            operation_event(f"node.{name}", started=started, outcome="failed", error=exc)
            await finish_node(
                tenant_id,
                run_id,
                task_id,
                "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
            )
            raise
        operation_event(f"node.{name}", started=started)
        await finish_node(
            tenant_id,
            run_id,
            task_id,
            "cancelled"
            if await cancel_if_requested(tenant_id=tenant_id, run_id=run_id)
            else "completed",
        )
        return result

    return invoke
