"""Permit the additive V5 technical-result report projection.

Revision ID: 0029
Revises: 0028
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        ALTER TABLE public.reports DROP CONSTRAINT IF EXISTS ck_report_document_v1;
        ALTER TABLE public.reports ADD CONSTRAINT ck_report_document_v1 CHECK (
            document IS NULL OR (
                jsonb_typeof(document) = 'object'
                AND COALESCE(document->>'version' IN ('1', '2', '3', '4', '5'), false)
                AND octet_length(document::text) <= 524288
            )
        );
    """)


def downgrade() -> None:
    raise RuntimeError("Preserve published V5 technical results; roll back application code only")
