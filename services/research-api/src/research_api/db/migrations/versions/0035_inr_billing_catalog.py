"""Allow shadow observations to reference the INR catalog version.

Revision ID: 0035
Revises: 0034
"""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute(
        "ALTER TABLE public.billing_shadow_observations "
        "DROP CONSTRAINT IF EXISTS ck_billing_shadow_decision_shape"
    )
    op.execute("""
        ALTER TABLE public.billing_shadow_observations
        ADD CONSTRAINT ck_billing_shadow_decision_shape CHECK (
            (decision_status = 'provisional' AND
             policy_version = 'approved-mode-weights-1-2-4-v1' AND
             catalog_version IN (
                'research-units-v1-2026-10-19',
                'research-units-v2-2026-10-19',
                'research-units-v3-2026-10-22'
             ) AND
             ((mode = 'focused' AND proposed_units = 1) OR
              (mode = 'balanced' AND proposed_units = 2) OR
              (mode = 'deep' AND proposed_units = 4))) OR
            (decision_status = 'unpriced_legacy_mode' AND mode IS NULL AND
             proposed_units IS NULL AND policy_version IS NULL AND
             catalog_version IS NULL)
        )
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Retain INR catalog observations; downgrade application code without removing history"
    )
