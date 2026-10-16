"""Persist the role-to-provider/model choice on each research run."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute(
        "ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS model_routing jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0011 is intentionally irreversible: dropping model_routing would erase "
        "provider/model choices required for replay consistency. Keep the column on app rollback."
    )
