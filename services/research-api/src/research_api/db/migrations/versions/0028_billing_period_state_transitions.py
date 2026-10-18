"""Add a narrow owner-scoped function for billing-period lifecycle changes.

Revision ID: 0028
Revises: 0027

Grant terms remain immutable and the application receives no table UPDATE grant.
Only the lifecycle state can change through the validated transition function.
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        ALTER TABLE public.billing_periods
            DROP CONSTRAINT IF EXISTS uq_billing_period_start;
        ALTER TABLE public.billing_periods
            DROP CONSTRAINT IF EXISTS uq_billing_period_plan_start;
        ALTER TABLE public.billing_periods
            ADD CONSTRAINT uq_billing_period_plan_start
            UNIQUE (tenant_id, billing_account_id, starts_at, plan_key);
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.transition_billing_period_state(
            p_tenant_id uuid,
            p_user_id uuid,
            p_period_id uuid,
            p_next_state text,
            p_effective_at timestamptz
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE changed boolean;
        BEGIN
            IF p_next_state NOT IN ('active', 'suspended', 'ended') THEN
                RAISE EXCEPTION 'invalid billing period state transition'
                    USING ERRCODE = '23514';
            END IF;
            IF p_effective_at IS NULL OR
               p_tenant_id IS DISTINCT FROM
                   NULLIF(current_setting('app.tenant_id', true), '')::uuid OR
               p_user_id IS DISTINCT FROM
                   NULLIF(current_setting('app.user_id', true), '')::uuid THEN
                RAISE EXCEPTION 'billing period owner context required'
                    USING ERRCODE = '42501';
            END IF;

            UPDATE public.billing_periods AS period
            SET state = p_next_state
            WHERE period.id = p_period_id
              AND period.tenant_id = p_tenant_id
              AND EXISTS (
                  SELECT 1 FROM public.billing_accounts AS account
                  WHERE account.id = period.billing_account_id
                    AND account.tenant_id = period.tenant_id
                    AND account.user_id = p_user_id
              )
              AND (
                  period.state = p_next_state
                  OR (period.state = 'pending' AND
                      p_next_state IN ('active', 'suspended', 'ended'))
                  OR (period.state = 'active' AND
                      p_next_state IN ('suspended', 'ended'))
                  OR (period.state = 'suspended' AND
                      p_next_state IN ('active', 'ended'))
                  OR (period.state = 'ended' AND period.plan_key = 'free' AND
                      p_next_state = 'active' AND
                      period.starts_at <= p_effective_at AND
                      period.ends_at > p_effective_at)
              )
            RETURNING true INTO changed;
            RETURN COALESCE(changed, false);
        END
        $$;
        REVOKE ALL ON FUNCTION public.transition_billing_period_state(
            uuid, uuid, uuid, text, timestamptz
        ) FROM PUBLIC;
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                GRANT EXECUTE ON FUNCTION public.transition_billing_period_state(
                    uuid, uuid, uuid, text, timestamptz
                ) TO research_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Keep the scoped billing-period transition and plan-key idempotency safeguards; "
        "roll back application code only"
    )
