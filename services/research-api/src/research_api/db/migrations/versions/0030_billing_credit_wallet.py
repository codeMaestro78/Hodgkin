"""Add isolated one-time research-credit purchase and append-only lot ledger.

Revision ID: 0030
Revises: 0029
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.models import BillingCreditEntry, BillingCreditPurchase

    op.execute("SET LOCAL search_path TO public")
    bind = op.get_bind()
    for model in (BillingCreditPurchase, BillingCreditEntry):
        cast(Table, model.__table__).create(bind, checkfirst=True)

    op.execute("ALTER TABLE public.billing_credit_purchases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_credit_purchases FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_credit_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.billing_credit_entries FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS personal_owner_scope ON public.billing_credit_purchases")
    op.execute("DROP POLICY IF EXISTS personal_owner_scope ON public.billing_credit_entries")
    op.execute("REVOKE ALL ON public.billing_credit_purchases FROM PUBLIC")
    op.execute("REVOKE ALL ON public.billing_credit_entries FROM PUBLIC")

    purchase_policy = """current_user = 'research_app' AND (
        current_setting('app.billing_system', true) = 'on' OR (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND EXISTS (
                SELECT 1 FROM public.billing_accounts AS account
                WHERE account.tenant_id = billing_credit_purchases.tenant_id
                  AND account.id = billing_credit_purchases.billing_account_id
                  AND account.user_id =
                    (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
            )
        )
    )"""
    op.execute(f"""
        CREATE POLICY personal_owner_scope ON public.billing_credit_purchases
        TO PUBLIC USING ({purchase_policy}) WITH CHECK ({purchase_policy})
    """)  # noqa: S608
    entry_policy = """current_user = 'research_app' AND (
        current_setting('app.billing_system', true) = 'on' OR (
            tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            AND EXISTS (
                SELECT 1 FROM public.billing_accounts AS account
                WHERE account.tenant_id = billing_credit_entries.tenant_id
                  AND account.id = billing_credit_entries.billing_account_id
                  AND account.user_id =
                    (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)
            )
        )
    )"""
    op.execute(f"""
        CREATE POLICY personal_owner_scope ON public.billing_credit_entries
        TO PUBLIC USING ({entry_policy}) WITH CHECK ({entry_policy})
    """)  # noqa: S608

    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_billing_credit_purchase()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'pending' OR NEW.stripe_payment_intent_id IS NOT NULL THEN
                    RAISE EXCEPTION 'credit purchase must begin in pending state'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'billing credit purchase history is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.tenant_id, NEW.id, NEW.billing_account_id, NEW.user_id, NEW.package_key,
                   NEW.stripe_price_id, NEW.request_key_hash, NEW.stripe_idempotency_key,
                   NEW.terms_version, NEW.amount_minor, NEW.currency, NEW.unit_grant,
                   NEW.created_at) IS DISTINCT FROM
               ROW(OLD.tenant_id, OLD.id, OLD.billing_account_id, OLD.user_id, OLD.package_key,
                   OLD.stripe_price_id, OLD.request_key_hash, OLD.stripe_idempotency_key,
                   OLD.terms_version, OLD.amount_minor, OLD.currency, OLD.unit_grant,
                   OLD.created_at) OR
               (OLD.stripe_checkout_session_id IS NOT NULL AND
                NEW.stripe_checkout_session_id IS DISTINCT FROM OLD.stripe_checkout_session_id) OR
               (OLD.stripe_payment_intent_id IS NOT NULL AND
                NEW.stripe_payment_intent_id IS DISTINCT FROM OLD.stripe_payment_intent_id) THEN
                RAISE EXCEPTION 'billing credit purchase terms are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF (NEW.state IS DISTINCT FROM OLD.state OR
                NEW.stripe_payment_intent_id IS DISTINCT FROM OLD.stripe_payment_intent_id)
               AND current_setting('app.billing_system', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'billing system context required to process credit purchase'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT (
                NEW.state = OLD.state OR
                (OLD.state = 'pending' AND NEW.state IN (
                    'paid','failed','reconciliation_required'
                )) OR
                (OLD.state = 'paid' AND NEW.state IN (
                    'refunded','disputed','reconciliation_required'
                )) OR
                (OLD.state = 'disputed' AND NEW.state IN (
                    'paid','refunded','reconciliation_required'
                )) OR
                (OLD.state = 'failed' AND NEW.state = 'reconciliation_required')
            ) THEN
                RAISE EXCEPTION 'invalid billing credit purchase state transition'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS billing_credit_purchase_immutable
            ON public.billing_credit_purchases;
        CREATE TRIGGER billing_credit_purchase_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON public.billing_credit_purchases
        FOR EACH ROW EXECUTE FUNCTION public.freeze_billing_credit_purchase();

        CREATE OR REPLACE FUNCTION public.freeze_billing_credit_entry()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.entry_type IN ('grant', 'reversal') AND
                   current_setting('app.billing_system', true) IS DISTINCT FROM 'on' THEN
                    RAISE EXCEPTION
                        'billing system context required for credit grants and reversals'
                        USING ERRCODE = '42501';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'billing credit ledger is append-only'
                USING ERRCODE = '23514';
        END $$;
        DROP TRIGGER IF EXISTS billing_credit_entry_append_only
            ON public.billing_credit_entries;
        CREATE TRIGGER billing_credit_entry_append_only
        BEFORE INSERT OR UPDATE OR DELETE ON public.billing_credit_entries
        FOR EACH ROW EXECUTE FUNCTION public.freeze_billing_credit_entry();
    """)

    op.execute("""
        DO $$
        DECLARE role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'research_app'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE pg_roles.rolname = role_name) THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE public.billing_credit_purchases, '
                        'public.billing_credit_entries FROM %I', role_name
                    );
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT, UPDATE ON TABLE '
                    'public.billing_credit_purchases TO %I', 'research_app'
                );
                EXECUTE format(
                    'GRANT SELECT, INSERT ON TABLE '
                    'public.billing_credit_entries TO %I', 'research_app'
                );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Preserve purchased-credit purchase and ledger history; roll back application code only"
    )
