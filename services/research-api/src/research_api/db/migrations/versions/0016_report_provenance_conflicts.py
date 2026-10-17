"""Allow the immutable report V3 provenance/conflict projection.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        ALTER TABLE public.reports DROP CONSTRAINT IF EXISTS ck_report_document_v1;
        ALTER TABLE public.reports ADD CONSTRAINT ck_report_document_v1 CHECK (
            document IS NULL OR (
                jsonb_typeof(document) = 'object'
                AND COALESCE(document->>'version' IN ('1', '2', '3'), false)
                AND octet_length(document::text) <= 524288
            )
        );
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0016 preserves published report V3 data; retain additive schema on application rollback"
    )
