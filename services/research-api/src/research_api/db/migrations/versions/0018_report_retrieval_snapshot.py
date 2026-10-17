"""Persist retrieval accounting with each immutable report version.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("ALTER TABLE public.reports ADD COLUMN IF NOT EXISTS retrieval_accounting jsonb")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_report_retrieval_accounting_snapshot'
                  AND conrelid = 'public.reports'::regclass
            ) THEN
                ALTER TABLE public.reports
                ADD CONSTRAINT ck_report_retrieval_accounting_snapshot CHECK (
                    retrieval_accounting IS NULL OR (
                        jsonb_typeof(retrieval_accounting) = 'object'
                        AND retrieval_accounting->>'schemaVersion' = '1.1'
                        AND octet_length(retrieval_accounting::text) <= 65536
                    )
                );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0018 snapshots publication-time report accounting; retain it on application rollback"
    )
