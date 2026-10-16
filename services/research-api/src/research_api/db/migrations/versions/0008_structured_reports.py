"""Add versioned report documents without rewriting historical Markdown.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing report ownership, tenant RLS and runtime-role privileges are unchanged.
    # Migration 0001 creates current Base.metadata on fresh installs, so the
    # additive column may already exist there (but not on upgraded databases).
    op.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS document jsonb")
    op.execute("""
        ALTER TABLE reports ADD CONSTRAINT ck_report_document_v1 CHECK (
            document IS NULL OR (
                jsonb_typeof(document) = 'object'
                AND document->>'version' IS NOT DISTINCT FROM '1'
                AND octet_length(document::text) <= 524288
            )
        )
    """)


def downgrade() -> None:
    # Explicit operator action only: Markdown and relational evidence remain intact.
    op.drop_constraint("ck_report_document_v1", "reports", type_="check")
    op.drop_column("reports", "document")
