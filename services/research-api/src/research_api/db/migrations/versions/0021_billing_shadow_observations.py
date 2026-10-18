"""Persist non-enforcing, tenant-scoped mode-unit observations.

Revision ID: 0021
Revises: 0020

The approved v1 catalog/policy snapshot is persisted for newly observed runs.
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.models import BillingShadowObservation

    op.execute("SET LOCAL search_path TO public")
    cast(Table, BillingShadowObservation.__table__).create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE public.billing_shadow_observations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_shadow_observations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON public.billing_shadow_observations "
        "USING (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) "
        "WITH CHECK (tenant_id = "
        "(SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
    )
    op.execute("REVOKE ALL ON public.billing_shadow_observations FROM PUBLIC")
    op.execute("""
        DO $$
        DECLARE role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'research_app'] LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE pg_roles.rolname = role_name
                ) THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE public.billing_shadow_observations FROM %I',
                        role_name
                    );
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT ON TABLE public.billing_shadow_observations TO %I',
                    'research_app'
                );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Retain append-only billing shadow observations; disable the feature in application config"
    )
