"""Add owner-scoped billing period snapshots and read-only unit ledger.

Revision ID: 0022
Revises: 0021

The application role receives SELECT only. There is deliberately no period
writer, reservation path, or quota enforcement in this migration.
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.models import BillingAccount, BillingPeriod, BillingUnitEntry

    op.execute("SET LOCAL search_path TO public")
    bind = op.get_bind()
    for model in (BillingAccount, BillingPeriod, BillingUnitEntry):
        cast(Table, model.__table__).create(bind, checkfirst=True)

    op.execute("ALTER TABLE public.billing_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_accounts FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_periods ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_periods FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_unit_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_unit_entries FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY personal_owner_scope ON public.billing_accounts
        USING (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND user_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
        )
        WITH CHECK (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND user_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
        )
    """)
    op.execute("""
        CREATE POLICY personal_owner_scope ON public.billing_periods
        USING (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND EXISTS (
                SELECT 1 FROM public.billing_accounts a
                WHERE a.tenant_id = billing_periods.tenant_id
                  AND a.id = billing_periods.billing_account_id
                  AND a.user_id =
                    (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
            )
        )
        WITH CHECK (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND EXISTS (
                SELECT 1 FROM public.billing_accounts a
                WHERE a.tenant_id = billing_periods.tenant_id
                  AND a.id = billing_periods.billing_account_id
                  AND a.user_id =
                    (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
            )
        )
    """)
    op.execute("""
        CREATE POLICY personal_owner_scope ON public.billing_unit_entries
        USING (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND EXISTS (
                SELECT 1 FROM public.billing_accounts a
                WHERE a.tenant_id = billing_unit_entries.tenant_id
                  AND a.id = billing_unit_entries.billing_account_id
                  AND a.user_id =
                    (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
            )
        )
        WITH CHECK (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND EXISTS (
                SELECT 1 FROM public.billing_accounts a
                WHERE a.tenant_id = billing_unit_entries.tenant_id
                  AND a.id = billing_unit_entries.billing_account_id
                  AND a.user_id =
                    (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
            )
        )
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_billing_period_snapshot()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'billing period history is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.tenant_id, NEW.id, NEW.billing_account_id, NEW.plan_key,
                   NEW.catalog_version, NEW.allowance_units, NEW.starts_at, NEW.ends_at)
               IS DISTINCT FROM
               ROW(OLD.tenant_id, OLD.id, OLD.billing_account_id, OLD.plan_key,
                   OLD.catalog_version, OLD.allowance_units, OLD.starts_at, OLD.ends_at)
            THEN
                RAISE EXCEPTION 'billing period grant snapshot is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER billing_period_snapshot_immutable
        BEFORE UPDATE OR DELETE ON public.billing_periods
        FOR EACH ROW EXECUTE FUNCTION public.freeze_billing_period_snapshot();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_billing_unit_entry()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            RAISE EXCEPTION 'billing unit ledger is append-only'
                USING ERRCODE = '23514';
        END $$;
        CREATE TRIGGER billing_unit_entry_append_only
        BEFORE UPDATE OR DELETE ON public.billing_unit_entries
        FOR EACH ROW EXECUTE FUNCTION public.freeze_billing_unit_entry();
    """)

    op.execute("REVOKE ALL ON public.billing_accounts FROM PUBLIC")
    op.execute("REVOKE ALL ON public.billing_periods FROM PUBLIC")
    op.execute("REVOKE ALL ON public.billing_unit_entries FROM PUBLIC")
    op.execute("""
        DO $$
        DECLARE role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'research_app'] LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE pg_roles.rolname = role_name
                ) THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE public.billing_accounts, '
                        'public.billing_periods, public.billing_unit_entries FROM %I',
                        role_name
                    );
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                EXECUTE format(
                    'GRANT SELECT ON TABLE public.billing_accounts, '
                    'public.billing_periods, public.billing_unit_entries TO %I',
                    'research_app'
                );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Retain billing period and unit-ledger history; roll back application code only"
    )
