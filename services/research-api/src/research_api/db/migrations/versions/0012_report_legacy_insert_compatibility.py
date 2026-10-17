"""Restore rolling compatibility for pre-0010 published report inserts."""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_published_report_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.published THEN
                RAISE EXCEPTION 'published report versions are immutable'
                    USING ERRCODE = '55000';
            END IF;
            -- Older application versions omit published_at and content_hash.
            -- New writers still persist both; legacy rows are hashed on read.
            IF NEW.published AND NEW.published_at IS NULL THEN
                NEW.published_at := COALESCE(NEW.created_at, statement_timestamp());
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0012 downgrade is disabled: restoring the prior trigger would break rolling "
        "compatibility. Keep the corrected trigger on application rollback."
    )
