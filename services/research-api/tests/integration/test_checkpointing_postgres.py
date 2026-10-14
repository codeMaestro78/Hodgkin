"""Official saver round trips + real RLS/fencing in a disposable loopback database.

The fixture models main's schema contract; it does not migrate the app database
or claim to validate main's forthcoming migration. No provider calls are made.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import AsyncConnection, errors, sql
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from research_api.checkpointing import CheckpointPool, CheckpointScopeError, TenantPostgresSaver
from research_api.config import Settings
from research_api.runtime_context import JobFence, LeaseLostError, current_job

pytestmark = pytest.mark.integration


def conninfo(url: str, database: str | None = None) -> str:
    parsed = make_url(url).set(drivername="postgresql")
    if database is not None:
        parsed = parsed.set(database=database)
    return parsed.render_as_string(hide_password=False)


@pytest.fixture
async def database() -> AsyncIterator[Any]:
    name = "research_checkpoint_test_" + uuid4().hex
    admin = await AsyncConnection.connect(
        conninfo(os.environ["TEST_DATABASE_ADMIN_URL"]), autocommit=True
    )
    await admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    owner = await AsyncConnection.connect(
        conninfo(os.environ["TEST_DATABASE_ADMIN_URL"], name), autocommit=True
    )
    token = current_job.set(None)
    try:
        await owner.execute("CREATE SCHEMA research_checkpoints")
        await owner.execute("SET search_path = research_checkpoints,public")
        for migration in AsyncPostgresSaver.MIGRATIONS:
            await owner.execute(migration.replace("CONCURRENTLY", ""))
        await owner.execute("""
            CREATE TABLE public.research_runs (
                id uuid PRIMARY KEY, tenant_id uuid NOT NULL, status text NOT NULL
            );
            CREATE TABLE public.runtime_jobs (
                tenant_id uuid NOT NULL, run_id uuid NOT NULL,
                owner_id uuid NOT NULL, generation bigint NOT NULL,
                state text NOT NULL, lease_expires_at timestamptz NOT NULL,
                PRIMARY KEY (tenant_id, run_id)
            );
            REVOKE ALL ON SCHEMA research_checkpoints FROM PUBLIC;
            GRANT USAGE ON SCHEMA research_checkpoints TO research_app;
        """)
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            await owner.execute(
                sql.SQL("""
                ALTER TABLE research_checkpoints.{table}
                ADD COLUMN tenant_id uuid GENERATED ALWAYS AS
                    (split_part(thread_id, ':', 1)::uuid) STORED;
            """).format(table=sql.Identifier(table))
            )
        for schema, table in (
            ("research_checkpoints", "checkpoints"),
            ("research_checkpoints", "checkpoint_blobs"),
            ("research_checkpoints", "checkpoint_writes"),
            ("public", "research_runs"),
            ("public", "runtime_jobs"),
        ):
            await owner.execute(
                sql.SQL("""
                ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY;
                CREATE POLICY tenant_access ON {schema}.{table} FOR ALL TO research_app
                USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
                GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.{table} TO research_app;
            """).format(schema=sql.Identifier(schema), table=sql.Identifier(table))
            )
        first, second = uuid4(), uuid4()
        run, other_run, job_owner = uuid4(), uuid4(), uuid4()
        await owner.execute(
            "INSERT INTO public.research_runs VALUES (%s, %s, 'running'), (%s, %s, 'running')",
            (run, first, other_run, second),
        )
        await owner.execute(
            "INSERT INTO public.runtime_jobs VALUES "
            "(%s, %s, %s, 1, 'running', clock_timestamp() + interval '1 hour')",
            (first, run, job_owner),
        )
        settings = Settings(
            DATABASE_URL=make_url(os.environ["DATABASE_URL"])
            .set(database=name)
            .render_as_string(hide_password=False),
            DATABASE_POOL_SIZE=1,
        )
        async with CheckpointPool(settings) as pool:
            yield SimpleNamespace(
                pool=pool,
                owner=owner,
                tenant=first,
                other_tenant=second,
                run=run,
                other_run=other_run,
                job_owner=job_owner,
                saver=TenantPostgresSaver(pool, first, run),
            )
    finally:
        current_job.reset(token)
        await owner.close()
        # Only this fixture's generated disposable DB is targeted.
        await admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        await admin.close()


def checkpoint() -> Any:
    result = empty_checkpoint()
    result["channel_values"] = {"text": "hello", "state": {"ids": ["one", "two"]}}
    result["channel_versions"] = {"text": "1", "state": "1"}
    return result


async def test_round_trip_pending_writes_history_and_terminal_cleanup(database: Any) -> None:
    saver = database.saver
    saved = checkpoint()
    config = await saver.aput(saver.config(), saved, {"step": 1}, saved["channel_versions"])
    await saver.aput_writes(config, [("result", {"ok": True})], "task")
    loaded = await saver.aget_tuple(config)
    assert loaded.checkpoint["channel_values"] == saved["channel_values"]
    assert loaded.pending_writes == [("task", "result", {"ok": True})]
    assert [item.config async for item in saver.alist(None)] == [config]
    with pytest.raises(CheckpointScopeError):
        await saver.adelete_thread(saver.thread_id)
    await database.owner.execute(
        "UPDATE public.research_runs SET status = 'completed' WHERE id = %s", (database.run,)
    )
    await saver.adelete_thread(saver.thread_id)
    assert await saver.aget_tuple(config) is None
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        result = await database.owner.execute(
            sql.SQL("SELECT count(*) FROM research_checkpoints.{}").format(sql.Identifier(table))
        )
        assert (await result.fetchone())[0] == 0


async def test_pool_reuse_does_not_leak_tenant_settings_and_rls_blocks_forgery(
    database: Any,
) -> None:
    first = checkpoint()
    await database.saver.aput(database.saver.config(), first, {}, first["channel_versions"])
    other = TenantPostgresSaver(database.pool, database.other_tenant, database.other_run)
    second = checkpoint()
    await other.aput(other.config(), second, {}, second["channel_versions"])
    assert (await other.aget(other.config()))["id"] == second["id"]
    assert (await database.saver.aget(database.saver.config()))["id"] == first["id"]
    async with database.pool.connection() as connection:
        cursor = await connection.execute("SELECT current_setting('app.tenant_id', true)")
        assert (await cursor.fetchone())[0] in (None, "")
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (str(database.other_tenant),)
            )
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("SELECT thread_id FROM research_checkpoints.checkpoints")
                assert await cursor.fetchall() == [{"thread_id": other.thread_id}]
            with pytest.raises(errors.InsufficientPrivilege):
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO research_checkpoints.checkpoints "
                        "(thread_id, checkpoint_ns, checkpoint_id, checkpoint) "
                        "VALUES (%s, '', 'forged', '{}'::jsonb)",
                        (database.saver.thread_id,),
                    )
            cursor = await connection.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            assert await cursor.fetchone() == (False, False)
    # Legitimate tenant, but foreign run still fails the run existence check.
    forged = TenantPostgresSaver(database.pool, database.other_tenant, database.run)
    with pytest.raises(CheckpointScopeError):
        await forged.aget(forged.config())


async def test_delegate_failure_rolls_back_earlier_blob_insert(database: Any) -> None:
    await database.owner.execute("""
        ALTER TABLE research_checkpoints.checkpoints
        ADD CONSTRAINT injected_failure CHECK (checkpoint_id <> 'reject')
    """)
    saved = checkpoint()
    saved["id"] = "reject"
    with pytest.raises(errors.CheckViolation):
        await database.saver.aput(database.saver.config(), saved, {}, saved["channel_versions"])
    cursor = await database.owner.execute(
        "SELECT count(*) FROM research_checkpoints.checkpoint_blobs"
    )
    assert (await cursor.fetchone())[0] == 0


@pytest.mark.parametrize("change", ["owner", "generation", "expired", "state"])
async def test_stale_worker_cannot_read_or_write(database: Any, change: str) -> None:
    current_job.set(JobFence(database.tenant, database.run, database.job_owner, 1))
    if change == "owner":
        assignment = sql.SQL("owner_id = {} ").format(sql.Literal(uuid4()))
    elif change == "generation":
        assignment = sql.SQL("generation = 2")
    elif change == "expired":
        assignment = sql.SQL("lease_expires_at = clock_timestamp() - interval '1 second'")
    else:
        assignment = sql.SQL("state = 'queued'")
    await database.owner.execute(sql.SQL("UPDATE public.runtime_jobs SET {}").format(assignment))
    saved = checkpoint()
    with pytest.raises(LeaseLostError):
        await database.saver.aput(database.saver.config(), saved, {}, saved["channel_versions"])
    with pytest.raises(LeaseLostError):
        await database.saver.aget(database.saver.config())


async def test_fence_share_lock_blocks_takeover_until_checkpoint_commit(
    database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    original = AsyncPostgresSaver.aput

    async def held(self: Any, *args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncPostgresSaver, "aput", held)
    current_job.set(JobFence(database.tenant, database.run, database.job_owner, 1))
    saved = checkpoint()
    task = asyncio.create_task(
        database.saver.aput(database.saver.config(), saved, {}, saved["channel_versions"])
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        async with database.owner.transaction():
            await database.owner.execute("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(errors.LockNotAvailable):
                async with database.owner.transaction():
                    await database.owner.execute("UPDATE public.runtime_jobs SET generation = 2")
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=5)
    await database.owner.execute("UPDATE public.runtime_jobs SET generation = 2")
    with pytest.raises(LeaseLostError):
        await database.saver.aget(database.saver.config())


class CounterState(TypedDict):
    count: int


async def test_langgraph_resumes_from_official_checkpoint(database: Any) -> None:
    async def increment(state: CounterState) -> CounterState:
        return {"count": state["count"] + 1}

    builder = StateGraph(CounterState)
    builder.add_node("first", increment)
    builder.add_node("second", increment)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    graph = builder.compile(checkpointer=database.saver, interrupt_after=["first"])
    config = database.saver.config()
    assert (await graph.ainvoke({"count": 0}, config))["count"] == 1
    # A new compiled graph uses the same run-bound saver and persisted state.
    resumed = builder.compile(checkpointer=database.saver)
    assert (await resumed.ainvoke(None, config))["count"] == 2
    snapshot = await resumed.aget_state(config)
    assert snapshot.values == {"count": 2}
    assert snapshot.next == ()
    history = [item async for item in resumed.aget_state_history(config)]
    assert len(history) >= 3
