"""Persist execution facts and task events, never model reasoning or tool arguments."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from research_api.billing.lifecycle import settle_terminal_run
from research_api.db.models import NodeExecution
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.lifecycle import TERMINAL_RUN_STATUSES, ensure_active, lock_run


async def start_node(tenant_id: uuid.UUID, run_id: uuid.UUID, node: str) -> uuid.UUID:
    async with tenant_session(str(tenant_id)) as session:
        run = await lock_run(session, tenant_id, run_id)
        ensure_active(run)
        attempt = (
            await session.scalar(
                select(func.max(NodeExecution.attempt)).where(
                    NodeExecution.tenant_id == tenant_id,
                    NodeExecution.run_id == run_id,
                    NodeExecution.node_id == node,
                )
            )
            or 0
        ) + 1
        row = NodeExecution(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            run_id=run_id,
            node_id=node,
            attempt=attempt,
            output_hash="0" * 64,
            status="running",
            started_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        await EventOutbox(session, tenant_id).append(
            run_id=run_id,
            event_type="task.state",
            payload={
                "taskId": str(row.id),
                "nodeId": node,
                "status": "running",
                "attempt": attempt,
                "label": f"{node.replace('_', ' ')} started",
            },
        )
        return row.id


async def finish_node(
    tenant_id: uuid.UUID, run_id: uuid.UUID, node_id: uuid.UUID, status: str
) -> None:
    if status not in {"completed", "failed", "cancelled", "paused"}:
        raise ValueError("invalid terminal task status")
    async with tenant_session(str(tenant_id)) as session:
        run = await lock_run(session, tenant_id, run_id)
        row = await session.scalar(
            select(NodeExecution)
            .where(
                NodeExecution.tenant_id == tenant_id,
                NodeExecution.run_id == run_id,
                NodeExecution.id == node_id,
            )
            .with_for_update()
        )
        if row is None or row.status != "running":
            return
        row.status = status
        row.completed_at = None if status == "paused" else datetime.now(UTC)
        await EventOutbox(session, tenant_id).append(
            run_id=run_id,
            event_type="task.state",
            payload={
                "taskId": str(row.id),
                "nodeId": row.node_id,
                "status": status,
                "attempt": row.attempt,
                "label": f"{row.node_id.replace('_', ' ')} {status}",
            },
        )
        if row.node_id == "synthesizer" and status == "completed":
            if (
                run.report_id
                and run.status not in TERMINAL_RUN_STATUSES
                and run.cancellation_requested_at is None
            ):
                run.status = "completed"
                await settle_terminal_run(session, run)
                await EventOutbox(session, tenant_id).append(
                    run_id=run_id,
                    event_type="run.completed",
                    payload={"reportId": str(run.report_id), "label": "Research run completed"},
                )


async def close_open_nodes(
    session: Any, tenant_id: uuid.UUID, run_id: uuid.UUID, status: str
) -> None:
    """Close tasks an interrupted graph left running, in the caller's run-locked transaction."""
    rows = list(
        await session.scalars(
            select(NodeExecution)
            .where(
                NodeExecution.tenant_id == tenant_id,
                NodeExecution.run_id == run_id,
                NodeExecution.status == "running",
            )
            .with_for_update()
        )
    )
    outbox = EventOutbox(session, tenant_id)
    for row in rows:
        row.status = status
        row.completed_at = datetime.now(UTC)
        await outbox.append(
            run_id=run_id,
            event_type="task.state",
            payload={
                "taskId": str(row.id),
                "nodeId": row.node_id,
                "status": status,
                "attempt": row.attempt,
                "label": f"{row.node_id.replace('_', ' ')} {status}",
            },
        )


def task_projection(
    row: Any,
    *,
    name: str | None = None,
    source_ids: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "nodeId": getattr(row, "node_id", "research_task"),
        "name": name or row.node_id.replace("_", " "),
        "status": row.status,
        "attempt": row.attempt,
        "startedAt": row.started_at.isoformat() if row.started_at else None,
        "completedAt": row.completed_at.isoformat() if row.completed_at else None,
        "errorCode": getattr(row, "error_code", None),
        "sourceIds": source_ids or [],
        "dependsOn": dependencies or [],
    }


def prior_dependencies(node: Any, nodes: list[Any]) -> list[str]:
    kind = {
        "planner": "intake",
        "research_worker": "planner_delta" if node.attempt > 1 else "planner",
        "reflector": "research_worker",
        "planner_delta": "reflector",
        "verifier": "reflector",
        "synthesizer": "verifier",
    }.get(node.node_id)
    prior = [
        item
        for item in nodes
        if item.node_id == kind and item.started_at <= node.started_at and item.id != node.id
    ]
    return [str(max(prior, key=lambda item: item.started_at).id)] if prior else []
