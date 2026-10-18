"""Persist explicit operational mode snapshots for batches and schedules.

Revision ID: 0025
Revises: 0024

Legacy rows remain mode-null. This does not enable monthly quota admission or
pin a billing catalog; those require separate approved commercial policy.
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    for table in ("research_batches", "research_schedules"):
        op.execute(f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS mode varchar(16)")
        op.execute(
            f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS mode_policy_version varchar(64)"
        )
        constraint = f"ck_{table}_mode_snapshot"
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.{table}'::regclass
                      AND conname = '{constraint}'
                ) THEN
                    ALTER TABLE public.{table}
                        ADD CONSTRAINT {constraint} CHECK (
                            (mode IS NULL AND mode_policy_version IS NULL) OR
                            (mode IN ('focused','balanced','deep') AND
                             mode_policy_version IS NOT NULL AND
                             length(btrim(mode_policy_version)) > 0)
                        );
                END IF;
            END $$;
        """)  # noqa: S608  # table/constraint names come from a fixed allowlist.


def downgrade() -> None:
    raise RuntimeError(
        "Preserve mode snapshots for scheduled and batched work; roll back application code only"
    )
