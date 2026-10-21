"""Add provider-neutral Razorpay order fields while retaining legacy payment history.

Revision ID: 0033
Revises: 0032
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.models import RazorpayWebhookEvent

    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        ALTER TABLE public.billing_credit_purchases
            ADD COLUMN IF NOT EXISTS payment_provider varchar(16),
            ADD COLUMN IF NOT EXISTS provider_order_state varchar(16)
                NOT NULL DEFAULT 'not_started',
            ADD COLUMN IF NOT EXISTS provider_order_id varchar(255),
            ADD COLUMN IF NOT EXISTS provider_payment_id varchar(255)
    """)
    op.execute("""
        UPDATE public.billing_credit_purchases
        SET payment_provider = CASE
            WHEN stripe_price_id IS NULL THEN 'razorpay'
            ELSE 'stripe'
        END
        WHERE payment_provider IS NULL;
        ALTER TABLE public.billing_credit_purchases
            ALTER COLUMN payment_provider SET DEFAULT 'razorpay',
            ALTER COLUMN payment_provider SET NOT NULL,
            ALTER COLUMN provider_order_state SET DEFAULT 'not_started',
            ALTER COLUMN provider_order_state SET NOT NULL;
    """)
    cast(Table, RazorpayWebhookEvent.__table__).create(op.get_bind(), checkfirst=True)
    op.execute("REVOKE ALL ON public.razorpay_webhook_events FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON public.razorpay_webhook_events FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON public.razorpay_webhook_events FROM authenticated;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                GRANT SELECT, INSERT, UPDATE ON public.razorpay_webhook_events TO research_app;
            END IF;
        END $$;
    """)
    op.execute(
        "ALTER TABLE public.billing_credit_purchases ALTER COLUMN stripe_price_id DROP NOT NULL"
    )
    op.execute("""
        DO $$
        DECLARE constraint_name text;
        BEGIN
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'public.billing_credit_purchases'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) ILIKE '%stripe_price_id%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE public.billing_credit_purchases DROP CONSTRAINT %I',
                    constraint_name
                );
            END LOOP;
        END $$;
        ALTER TABLE public.billing_credit_purchases
            ADD CONSTRAINT ck_billing_credit_purchase_provider CHECK (
                (payment_provider = 'stripe' AND stripe_price_id IS NOT NULL) OR
                (payment_provider = 'razorpay' AND stripe_price_id IS NULL AND
                 stripe_checkout_session_id IS NULL AND stripe_payment_intent_id IS NULL)
            );
        ALTER TABLE public.billing_credit_purchases
            ADD CONSTRAINT ck_billing_credit_paid_provider_payment CHECK (
                state <> 'paid' OR stripe_payment_intent_id IS NOT NULL OR
                provider_payment_id IS NOT NULL
            );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_credit_provider_order
            ON public.billing_credit_purchases (provider_order_id)
            WHERE provider_order_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_credit_provider_payment
            ON public.billing_credit_purchases (provider_payment_id)
            WHERE provider_payment_id IS NOT NULL;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_razorpay_credit_purchase_fields()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.payment_provider = 'razorpay' AND
                   (NEW.state <> 'pending' OR NEW.stripe_price_id IS NOT NULL OR
                    NEW.stripe_checkout_session_id IS NOT NULL OR
                    NEW.stripe_payment_intent_id IS NOT NULL OR
                    NEW.provider_payment_id IS NOT NULL) THEN
                    RAISE EXCEPTION 'Razorpay purchase must begin pending without payment'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.payment_provider IS DISTINCT FROM OLD.payment_provider THEN
                RAISE EXCEPTION 'billing purchase provider is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF (OLD.provider_order_id IS NOT NULL AND
                NEW.provider_order_id IS DISTINCT FROM OLD.provider_order_id) OR
               (OLD.provider_payment_id IS NOT NULL AND
                NEW.provider_payment_id IS DISTINCT FROM OLD.provider_payment_id) THEN
                RAISE EXCEPTION 'Razorpay provider identifiers are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF (NEW.provider_order_id IS DISTINCT FROM OLD.provider_order_id OR
                NEW.provider_payment_id IS DISTINCT FROM OLD.provider_payment_id OR
                NEW.provider_order_state IS DISTINCT FROM OLD.provider_order_state) AND
               current_setting('app.billing_system', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'billing system context required for provider identifiers'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT (
                NEW.provider_order_state = OLD.provider_order_state OR
                (OLD.provider_order_state = 'not_started' AND
                 NEW.provider_order_state = 'creating') OR
                (OLD.provider_order_state = 'creating' AND
                 NEW.provider_order_state IN ('created','uncertain'))
            ) THEN
                RAISE EXCEPTION 'invalid payment-provider order state transition'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS razorpay_credit_purchase_immutable
            ON public.billing_credit_purchases;
        CREATE TRIGGER razorpay_credit_purchase_immutable
        BEFORE INSERT OR UPDATE ON public.billing_credit_purchases
        FOR EACH ROW EXECUTE FUNCTION public.freeze_razorpay_credit_purchase_fields();
    """)


def downgrade() -> None:
    raise RuntimeError("Preserve Razorpay payment references and historical billing data")
