"""Tenant-scoped pre-dispatch extraction admission. Drain old workers before rollout."""

from typing import cast

from alembic import op
from sqlalchemy import Table

from research_api.db.models import ExtractionSlot

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname='uq_reservations_tenant_run_id'
                AND conrelid='provider_call_reservations'::regclass) THEN
                ALTER TABLE provider_call_reservations
                    ADD CONSTRAINT uq_reservations_tenant_run_id UNIQUE (tenant_id, run_id, id);
            END IF;
        END $$;
    """)
    # Initial migration uses current Base.metadata; checkfirst supports fresh installs too.
    cast(Table, ExtractionSlot.__table__).create(op.get_bind(), checkfirst=True)
    op.execute("""
        ALTER TABLE extraction_slots ENABLE ROW LEVEL SECURITY;
        ALTER TABLE extraction_slots FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_scope ON extraction_slots
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        REVOKE ALL ON extraction_slots FROM PUBLIC;
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='research_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON extraction_slots TO research_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
                REVOKE ALL ON extraction_slots FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
                REVOKE ALL ON extraction_slots FROM authenticated;
            END IF;
        END $$;
    """)
    # Existing sources are imported lazily in a tenant-scoped admission transaction.
    # No global data backfill and no elevation around FORCE RLS are needed.


def downgrade() -> None:
    op.drop_table("extraction_slots")
    op.drop_constraint(
        "uq_reservations_tenant_run_id", "provider_call_reservations", type_="unique"
    )
