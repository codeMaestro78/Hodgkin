"""Grant narrowly scoped billing-ledger writes after schema guards exist.

Revision ID: 0023
Revises: 0022

Unique idempotency indexes are part of the 0022-created table metadata. No public
admission path is enabled by this migration. Writes remain owner-scoped by RLS.
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("REVOKE ALL ON public.billing_accounts FROM PUBLIC")
    op.execute("REVOKE ALL ON public.billing_periods FROM PUBLIC")
    op.execute("REVOKE ALL ON public.billing_unit_entries FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT ON TABLE public.billing_accounts, '
                    'public.billing_periods, public.billing_unit_entries TO %I',
                    'research_app'
                );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Retain billing ledger idempotency guarantees and audit history; roll back code only"
    )
