"""add durable research-run idempotency key

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0001 creates tables from current SQLAlchemy metadata in a fresh install,
    # so the column may already be present. Existing 0001 installs need it.
    op.execute("ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(200)")
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'uq_research_runs_tenant_user_idempotency') THEN "
        "ALTER TABLE research_runs ADD CONSTRAINT uq_research_runs_tenant_user_idempotency "
        "UNIQUE (tenant_id, user_id, idempotency_key); END IF; END $$;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS "
        "uq_research_runs_tenant_user_idempotency"
    )
    op.execute("ALTER TABLE research_runs DROP COLUMN IF EXISTS idempotency_key")
