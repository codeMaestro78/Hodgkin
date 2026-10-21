"""Add persistent pinning and workspace deletion for research history.

Revision ID: 0032
Revises: 0031
"""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute(
        "ALTER TABLE public.research_runs ADD COLUMN IF NOT EXISTS pinned_at timestamptz"
    )
    op.execute(
        "ALTER TABLE public.research_runs ADD COLUMN IF NOT EXISTS deleted_at timestamptz"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_research_runs_owner_pinned_created "
        "ON public.research_runs "
        "(tenant_id, user_id, pinned_at DESC NULLS LAST, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve user history controls; roll back application code only")
