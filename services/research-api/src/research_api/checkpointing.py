"""Internal, run-bound LangGraph persistence (no setup or global maintenance API).

Integration contract: migrate AsyncPostgresSaver.MIGRATIONS into the private
research_checkpoints schema before use. Migrations 6--8 contain CONCURRENTLY;
run those outside the migration transaction or replace with ordinary indexes.
On checkpoints/checkpoint_blobs/checkpoint_writes add a stored generated UUID
tenant_id = split_part(thread_id, ':', 1)::uuid, ENABLE + FORCE RLS with USING
and WITH CHECK against current_setting('app.tenant_id', true)::uuid. Revoke
schema/table access from PUBLIC and browser roles; grant the service role only
USAGE and required DML. checkpoint_migrations is owner-only (no tenant column).
Add database CHECK bounds on octet_length(blob), and on the JSONB checkpoint
and metadata text, to bound stored rows before the driver decodes inline JSON.
The service role must be NOSUPERUSER NOBYPASSRLS. Never call saver.setup() at
runtime. Keep public schema CREATE privileges restricted too.

Main supplies runtime_context.current_job, default None, containing JobFence
(tenant_id, run_id, owner_id, generation). runtime_jobs must expose those
columns plus state and lease_expires_at. Fence checks take FOR SHARE in the
same transaction as delegate IO, preventing takeover until commit. Run rows
are also locked so terminal cleanup cannot race a status transition.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    DeltaChannelHistory,
    get_serializable_checkpoint_metadata,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from research_api.config import Settings
from research_api.runtime_context import LeaseLostError, current_job

MAX_CHECKPOINT_BYTES = 1024 * 1024
MAX_LIST_PAGE = 100
TERMINAL_RUN_STATES = frozenset({"completed", "failed", "cancelled"})


@asynccontextmanager
async def CheckpointPool(settings: Settings) -> AsyncIterator[AsyncConnectionPool[Any]]:
    """Application-lifespan pool; pass the yielded pool to all run-bound savers."""
    url = make_url(settings.DATABASE_URL)
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("Checkpoint pool requires a PostgreSQL psycopg URL")
    if settings.DATABASE_POOL_SIZE < 1:
        raise ValueError("Checkpoint pool size must be positive")
    conninfo = url.set(drivername="postgresql").render_as_string(hide_password=False)
    async with AsyncConnectionPool(
        conninfo,
        min_size=1,
        max_size=settings.DATABASE_POOL_SIZE,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    ) as pool:
        await pool.wait()
        yield pool


class CheckpointScopeError(PermissionError):
    """Scope, run authorization, or current worker fence is invalid."""


class CheckpointPayloadError(ValueError):
    """A serialized checkpoint or write exceeds the configured bound."""


class BoundedJsonPlusSerializer(JsonPlusSerializer):
    """Strict official serde, with byte bounds before decoding and after encoding."""

    def __init__(self) -> None:
        super().__init__(
            pickle_fallback=False, allowed_msgpack_modules=None, allowed_json_modules=None
        )

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        value = super().dumps_typed(obj)
        self._check(value[1])
        return value

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        self._check(data[1])
        return super().loads_typed(data)

    @staticmethod
    def _check(data: bytes) -> None:
        if len(data) > MAX_CHECKPOINT_BYTES:
            raise CheckpointPayloadError("Checkpoint payload exceeds 1 MiB")


class TenantPostgresSaver(BaseCheckpointSaver[str]):
    """Bind once per run; share the application pool, never a live connection.

    Use config() for graph.ainvoke/astream and history lookups. Only the async
    saver interface is supported. Namespace is fixed for the lifetime of a run;
    callers cannot switch namespaces or use arbitrary subgraph namespaces.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        tenant_id: UUID | str,
        run_id: UUID | str,
        *,
        namespace: str = "",
    ) -> None:
        super().__init__(serde=BoundedJsonPlusSerializer())
        self._versioner = BasePostgresSaver(serde=self.serde)
        self._pool = pool
        self._tenant_id = UUID(str(tenant_id))
        self._run_id = UUID(str(run_id))
        if not isinstance(namespace, str) or len(namespace.encode()) > 200:
            raise ValueError("Checkpoint namespace must be a string of at most 200 bytes")
        self._namespace = namespace

    @property
    def thread_id(self) -> str:
        return f"{self._tenant_id}:{self._run_id}"

    def config(self, *, checkpoint_id: str | None = None) -> RunnableConfig:
        configurable: dict[str, Any] = {
            "thread_id": self.thread_id,
            "checkpoint_ns": self._namespace,
        }
        if checkpoint_id is not None:
            configurable["checkpoint_id"] = checkpoint_id
        return {"configurable": configurable}

    def _scoped(self, config: RunnableConfig) -> RunnableConfig:
        scoped = dict(config.get("configurable", {}))
        if scoped.get("thread_id") != self.thread_id:
            raise CheckpointScopeError("Checkpoint thread does not match bound run")
        if scoped.get("checkpoint_ns", self._namespace) != self._namespace:
            raise CheckpointScopeError("Checkpoint namespace does not match bound run")
        for key, expected in (("tenant_id", self._tenant_id), ("run_id", self._run_id)):
            if key in scoped and str(scoped[key]) != str(expected):
                raise CheckpointScopeError("Checkpoint config does not match bound scope")
        scoped["checkpoint_ns"] = self._namespace
        return {**config, "configurable": scoped}

    @asynccontextmanager
    async def _delegate(self, *, deleting: bool = False) -> AsyncIterator[AsyncPostgresSaver]:
        fence = current_job.get()
        if fence is not None and (
            str(fence.tenant_id) != str(self._tenant_id) or str(fence.run_id) != str(self._run_id)
        ):
            raise CheckpointScopeError("Worker fence does not match bound run")
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', %s, true), "
                "set_config('search_path', 'research_checkpoints,public', true)",
                (str(self._tenant_id),),
            )
            async with conn.cursor(row_factory=dict_row) as cur:
                if fence is not None:
                    await cur.execute(
                        "SELECT 1 FROM public.runtime_jobs "
                        "WHERE tenant_id = %s AND run_id = %s AND owner_id = %s "
                        "AND generation = %s AND state = 'running' "
                        "AND lease_expires_at > clock_timestamp() FOR SHARE",
                        (self._tenant_id, self._run_id, fence.owner_id, fence.generation),
                    )
                    if await cur.fetchone() is None:
                        raise LeaseLostError("Worker lease is stale or expired")
                await cur.execute(
                    "SELECT status FROM public.research_runs "
                    "WHERE tenant_id = %s AND id = %s FOR SHARE",
                    (self._tenant_id, self._run_id),
                )
                run = await cur.fetchone()
                if run is None:
                    raise CheckpointScopeError("Bound research run is not authorized")
                if deleting and run["status"] not in TERMINAL_RUN_STATES:
                    raise CheckpointScopeError("Only terminal run checkpoints can be deleted")
            yield AsyncPostgresSaver(conn, serde=self.serde)

    def _bounded(self, value: Any) -> None:
        self.serde.dumps_typed(value)

    async def aget(self, config: RunnableConfig) -> Checkpoint | None:
        item = await self.aget_tuple(config)
        return item.checkpoint if item else None

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        scoped = self._scoped(config)
        async with self._delegate() as saver:
            result = await saver.aget_tuple(scoped)
            if result is not None:
                self._bounded((result.checkpoint, result.metadata, result.pending_writes))
            return result

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        scoped = self._scoped(config if config is not None else self.config())
        cursor = self._scoped(before) if before is not None else None
        if limit is not None and (isinstance(limit, bool) or limit < 0):
            raise ValueError("Checkpoint list limit must be nonnegative")
        remaining = limit
        while remaining is None or remaining > 0:
            page_size = min(remaining, MAX_LIST_PAGE) if remaining is not None else MAX_LIST_PAGE
            async with self._delegate() as saver:
                page = [
                    item
                    async for item in saver.alist(
                        scoped, filter=filter, before=cursor, limit=page_size
                    )
                ]
                for item in page:
                    self._bounded((item.checkpoint, item.metadata, item.pending_writes))
            for item in page:
                yield item
            if len(page) < page_size:
                break
            cursor = self._scoped(page[-1].config)
            if remaining is not None:
                remaining -= len(page)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        scoped = self._scoped(config)
        actual_metadata = get_serializable_checkpoint_metadata(scoped, metadata)
        self._bounded((checkpoint, actual_metadata))
        # Official saver writes metadata/inline primitives directly as JSONB,
        # bypassing serde: bound that representation separately as well.
        BoundedJsonPlusSerializer._check(json.dumps(actual_metadata).encode())
        BoundedJsonPlusSerializer._check(
            json.dumps(checkpoint, default=lambda value: None).encode()
        )
        async with self._delegate() as saver:
            return await saver.aput(scoped, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        scoped = self._scoped(config)
        self._bounded((writes, task_id, task_path))
        async with self._delegate() as saver:
            await saver.aput_writes(scoped, writes, task_id, task_path)

    async def aget_delta_channel_history(
        self, *, config: RunnableConfig, channels: Sequence[str]
    ) -> Mapping[str, DeltaChannelHistory]:
        scoped = self._scoped(config)
        async with self._delegate() as saver:
            result = await saver.aget_delta_channel_history(config=scoped, channels=channels)
            self._bounded(result)
            return result

    async def adelete_thread(self, thread_id: str) -> None:
        self._scoped({"configurable": {"thread_id": thread_id}})
        async with self._delegate(deleting=True) as saver:
            await saver.adelete_thread(thread_id)

    async def acopy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        raise CheckpointScopeError("Checkpoint copying is not supported")

    async def adelete_for_runs(self, run_ids: Sequence[str]) -> None:
        raise CheckpointScopeError("Use terminal, run-bound adelete_thread for retention")

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        raise CheckpointScopeError("Use terminal, run-bound adelete_thread for retention")

    def get_next_version(self, current: str | None, channel: None) -> str:
        return self._versioner.get_next_version(current, channel)
