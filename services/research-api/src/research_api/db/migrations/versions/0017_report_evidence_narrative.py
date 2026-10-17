"""Allow the immutable report V4 evidence-verified narrative projection.

Revision ID: 0017
Revises: 0016
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        ALTER TABLE public.reports DROP CONSTRAINT IF EXISTS ck_report_document_v1;
        ALTER TABLE public.reports ADD CONSTRAINT ck_report_document_v1 CHECK (
            document IS NULL OR (
                jsonb_typeof(document) = 'object'
                AND COALESCE(document->>'version' IN ('1', '2', '3', '4'), false)
                AND octet_length(document::text) <= 524288
            )
        );
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0017 preserves published report V4 data; retain additive schema on application rollback"
    )
