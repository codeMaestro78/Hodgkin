"""Persist actor and reason on immutable billing-ledger adjustments.

Revision ID: 0024
Revises: 0023

Adjustment writes remain internal and require authorization at the calling
service boundary. This migration adds audit fields without granting UPDATE or
DELETE access to the ledger.
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    # 0022 creates tables from current ORM metadata; tolerate columns/constraint
    # already present there while also upgrading databases created at revision 0023.
    op.execute("ALTER TABLE public.billing_unit_entries ADD COLUMN IF NOT EXISTS actor_id uuid")
    op.execute(
        "ALTER TABLE public.billing_unit_entries ADD COLUMN IF NOT EXISTS reason varchar(500)"
    )
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'public.billing_unit_entries'::regclass
                  AND conname = 'ck_billing_adjustment_audit'
            ) THEN
                ALTER TABLE public.billing_unit_entries
                    ADD CONSTRAINT ck_billing_adjustment_audit CHECK (
                        (entry_type = 'adjustment' AND actor_id IS NOT NULL AND
                         reason IS NOT NULL AND
                         length(btrim(reason)) BETWEEN 1 AND 500) OR
                        (entry_type <> 'adjustment' AND actor_id IS NULL AND reason IS NULL)
                    );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Retain immutable adjustment actor and reason history; roll back application code only"
    )
