"""Add owner mapping and an ordered, minimal Stripe subscription projection.

Revision ID: 0027
Revises: 0026
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.models import (
        StripeCheckoutAttempt,
        StripeCustomerLink,
        StripeSubscription,
    )

    op.execute("SET LOCAL search_path TO public")
    bind = op.get_bind()
    for model in (StripeCustomerLink, StripeSubscription, StripeCheckoutAttempt):
        cast(Table, model.__table__).create(bind, checkfirst=True)

    op.execute("""
        ALTER TABLE public.stripe_webhook_events
            ALTER COLUMN processing_status TYPE varchar(32);
        ALTER TABLE public.stripe_webhook_events
            DROP CONSTRAINT IF EXISTS ck_stripe_webhook_event_status;
        ALTER TABLE public.stripe_webhook_events
            ADD CONSTRAINT ck_stripe_webhook_event_status CHECK (
                processing_status IN (
                    'received', 'ignored', 'processed', 'stale', 'reconciliation_required'
                )
            );
    """)
    for table in (
        "stripe_customer_links",
        "stripe_subscriptions",
        "stripe_checkout_attempts",
        "stripe_webhook_events",
    ):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS billing_service_only ON public.{table}")
        if table == "stripe_webhook_events":
            policy = "current_user = 'research_app'"
        else:
            policy = """current_user = 'research_app' AND (
                (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                 AND user_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid))
                OR current_setting('app.billing_system', true) = 'on'
            )"""
        op.execute(
            f"CREATE POLICY billing_service_only ON public.{table} "
            f"TO PUBLIC USING ({policy}) WITH CHECK ({policy})"  # noqa: S608
        )
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")
    op.execute("""
        DO $$
        DECLARE table_name text;
        BEGIN
            FOREACH table_name IN ARRAY ARRAY[
                'stripe_customer_links', 'stripe_subscriptions',
                'stripe_checkout_attempts', 'stripe_webhook_events'
            ] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE public.%I FROM anon', table_name
                    );
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE public.%I FROM authenticated', table_name
                    );
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                    EXECUTE format(
                        'GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO research_app',
                        table_name
                    );
                END IF;
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Preserve subscription and webhook idempotency history; roll back application code only"
    )
