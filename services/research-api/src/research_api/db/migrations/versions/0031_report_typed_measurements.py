"""Permit the additive V6 typed-measurement report projection.

Revision ID: 0031
Revises: 0030
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        ALTER TABLE public.reports DROP CONSTRAINT IF EXISTS ck_report_document_v1;
        ALTER TABLE public.reports ADD CONSTRAINT ck_report_document_v1 CHECK (
            document IS NULL OR (
                jsonb_typeof(document) = 'object'
                AND COALESCE(document->>'version' IN ('1', '2', '3', '4', '5', '6'), false)
                AND octet_length(document::text) <= 524288
            )
        );
    """)


def downgrade() -> None:
    raise RuntimeError("Preserve published V6 measurement reports; roll back application code only")
