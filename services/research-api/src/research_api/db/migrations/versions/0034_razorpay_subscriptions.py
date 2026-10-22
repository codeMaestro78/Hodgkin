"""Add owner-scoped Razorpay subscription and charge projections.

Revision ID: 0034
Revises: 0033
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.models import (
        RazorpaySubscription,
        RazorpaySubscriptionCheckoutAttempt,
        RazorpaySubscriptionPayment,
    )

    op.execute("SET LOCAL search_path TO public")
    bind = op.get_bind()
    for model in (
        RazorpaySubscription,
        RazorpaySubscriptionCheckoutAttempt,
        RazorpaySubscriptionPayment,
    ):
        cast(Table, model.__table__).create(bind, checkfirst=True)

    for table in (
        "razorpay_subscriptions",
        "razorpay_subscription_checkout_attempts",
        "razorpay_subscription_payments",
    ):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS billing_service_only ON public.{table}")
        if table == "razorpay_subscription_payments":
            predicate = (
                "current_user = 'research_app' AND "
                "current_setting('app.billing_system', true) = 'on'"
            )
        else:
            predicate = """current_user = 'research_app' AND (
                (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                 AND user_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid))
                OR current_setting('app.billing_system', true) = 'on'
            )"""
        op.execute(
            f"CREATE POLICY billing_service_only ON public.{table} "
            f"TO PUBLIC USING ({predicate}) WITH CHECK ({predicate})"  # noqa: S608
        )
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")

    op.execute("""
        DO $$
        DECLARE table_name text;
        BEGIN
            FOREACH table_name IN ARRAY ARRAY[
                'razorpay_subscriptions',
                'razorpay_subscription_checkout_attempts',
                'razorpay_subscription_payments'
            ] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon', table_name);
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM authenticated', table_name);
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
        "Preserve recurring billing and charge idempotency history; roll back application code only"
    )
