"""Durable dispatch, tenant-isolated checkpoints and approval records."""

from typing import cast

from alembic import op
from sqlalchemy import Table

from research_api.db.models import (
    DispatchRegistry,
    PlanApproval,
    ResearchBatch,
    ResearchSchedule,
    RuntimeJob,
)

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS "
        "approval_required BOOLEAN NOT NULL DEFAULT false"
    )
    for model in (DispatchRegistry, ResearchBatch, RuntimeJob, PlanApproval, ResearchSchedule):
        cast(Table, model.__table__).create(op.get_bind(), checkfirst=True)
        table = model.__tablename__
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_scope ON {table} USING "
            "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"""DO $$ BEGIN  -- fixed model allowlist
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='research_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO research_app; END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
                REVOKE ALL ON {table} FROM anon; END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
                REVOKE ALL ON {table} FROM authenticated; END IF;
        END $$;""")  # noqa: S608
    # Reviewed coordination exception: discovery has only tenant IDs/wake-up times.
    # No globally readable prompts, approvals, jobs, checkpoints or evidence.
    op.execute(
        "CREATE POLICY dispatch_discovery ON dispatch_registry FOR SELECT USING "
        "(current_setting('app.dispatcher', true) = 'on')"
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS research_checkpoints")
    op.execute("SET LOCAL search_path TO research_checkpoints, public")
    # Snapshot of the official saver 3.1.3 DDL. No runtime setup under app credentials.
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoint_migrations (v INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT,
            type TEXT, checkpoint JSONB NOT NULL, metadata JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id));
        CREATE TABLE IF NOT EXISTS checkpoint_blobs (
            thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL, version TEXT NOT NULL, type TEXT NOT NULL, blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, channel, version));
        CREATE TABLE IF NOT EXISTS checkpoint_writes (
            thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL,
            channel TEXT NOT NULL, type TEXT, blob BYTEA NOT NULL,
            task_path TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx));
        INSERT INTO checkpoint_migrations SELECT generate_series(0,9) ON CONFLICT DO NOTHING;
    """)
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id uuid "
            "GENERATED ALWAYS AS (split_part(thread_id, ':', 1)::uuid) STORED"
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS {table}_thread_id_idx ON {table}(thread_id)")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_scope ON {table} USING "
            "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute("REVOKE ALL ON SCHEMA research_checkpoints FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA research_checkpoints FROM PUBLIC")
    op.execute(
        "ALTER TABLE research_checkpoints.checkpoints ADD CONSTRAINT checkpoint_size "
        "CHECK (octet_length(checkpoint::text) <= 1048576 AND "
        "octet_length(metadata::text) <= 1048576)"
    )
    for table in ("checkpoint_blobs", "checkpoint_writes"):
        op.execute(
            f"ALTER TABLE research_checkpoints.{table} ADD CONSTRAINT {table}_size "
            "CHECK (octet_length(blob) <= 1048576)"
        )
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='research_app') THEN
            GRANT USAGE ON SCHEMA research_checkpoints TO research_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA research_checkpoints
                TO research_app;
            REVOKE ALL ON research_checkpoints.checkpoint_migrations FROM research_app; END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
            REVOKE ALL ON SCHEMA research_checkpoints FROM anon;
            REVOKE ALL ON ALL TABLES IN SCHEMA research_checkpoints FROM anon; END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
            REVOKE ALL ON SCHEMA research_checkpoints FROM authenticated;
            REVOKE ALL ON ALL TABLES IN SCHEMA research_checkpoints FROM authenticated; END IF;
    END $$;""")


def downgrade() -> None:
    # Drain workers and export any needed recovery state before this rollback.
    op.execute("DROP SCHEMA research_checkpoints CASCADE")
    for table in (
        "plan_approvals",
        "runtime_jobs",
        "research_schedules",
        "research_batches",
        "dispatch_registry",
    ):
        op.drop_table(table)
    op.drop_column("research_runs", "approval_required")
