"""Add the minimal Stripe event inbox and scheduled quota-block diagnostics.

Revision ID: 0026
Revises: 0025
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.models import StripeWebhookEvent

    op.execute("SET LOCAL search_path TO public")
    op.execute(
        "ALTER TABLE public.research_schedules "
        "ADD COLUMN IF NOT EXISTS last_quota_blocked_at timestamptz"
    )
    op.execute(
        "ALTER TABLE public.research_schedules "
        "ADD COLUMN IF NOT EXISTS last_quota_blocked_reason varchar(64)"
    )
    cast(Table, StripeWebhookEvent.__table__).create(op.get_bind(), checkfirst=True)
    op.execute("REVOKE ALL ON public.stripe_webhook_events FROM PUBLIC")
    op.execute("""
        DO $$
        DECLARE role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'research_app'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE pg_roles.rolname = role_name) THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE public.stripe_webhook_events FROM %I', role_name
                    );
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT ON TABLE public.stripe_webhook_events TO %I',
                    'research_app'
                );
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Preserve Stripe webhook deduplication history; roll back application code only"
    )
