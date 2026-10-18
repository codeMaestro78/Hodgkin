"""Allow additive retrieval-accounting snapshot version 1.2.

Revision ID: 0020
Revises: 0019
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        ALTER TABLE public.reports
        DROP CONSTRAINT IF EXISTS
            ck_report_retrieval_accounting_snapshot;
        ALTER TABLE public.reports ADD CONSTRAINT ck_report_retrieval_accounting_snapshot CHECK (
            retrieval_accounting IS NULL OR (
                jsonb_typeof(retrieval_accounting) = 'object'
                AND retrieval_accounting->>'schemaVersion' IN ('1.1', '1.2')
                AND octet_length(retrieval_accounting::text) <= 65536
            )
        );
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0019 permits persisted retrieval-accounting v1.2 snapshots; retain additive schema"
    )
