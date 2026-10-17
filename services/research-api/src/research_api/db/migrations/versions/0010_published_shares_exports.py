"""Freeze published report versions and add revocable shares/version exports."""

from typing import cast

from alembic import op
from sqlalchemy import Table

from research_api.db.models import ReportExport, ReportShare

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS published_at timestamptz")
    op.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS content_hash varchar(64)")
    op.execute(
        "UPDATE reports SET published_at = COALESCE(published_at, updated_at, created_at) "
        "WHERE published AND published_at IS NULL"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION reject_published_report_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.published THEN
                RAISE EXCEPTION 'published report versions are immutable'
                    USING ERRCODE = '55000';
            END IF;
            -- Pre-0010 application versions insert published reports without
            -- these columns. Preserve rolling rollback compatibility; new
            -- writers persist the hash, while legacy rows are hashed on read.
            IF NEW.published AND NEW.published_at IS NULL THEN
                NEW.published_at := COALESCE(NEW.created_at, statement_timestamp());
            END IF;
            RETURN NEW;
        END;
        $$;
        DROP TRIGGER IF EXISTS reports_immutable_after_publish ON reports;
        CREATE TRIGGER reports_immutable_after_publish
            BEFORE INSERT OR UPDATE ON reports FOR EACH ROW
            EXECUTE FUNCTION reject_published_report_mutation();
    """)

    for model in (ReportShare, ReportExport):
        cast(Table, model.__table__).create(op.get_bind(), checkfirst=True)
        table = model.__tablename__
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        owner = (
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
            "AND user_id = NULLIF(current_setting('app.user_id', true), '')::uuid"
        )
        op.execute(f"CREATE POLICY owner_scope ON {table} USING ({owner}) WITH CHECK ({owner})")
        if model is ReportShare:
            # Anonymous capability lookup is constrained to a single SHA-256
            # token digest supplied through a transaction-local setting.
            op.execute("""
                CREATE POLICY capability_lookup ON report_shares FOR SELECT USING (
                    token_hash = NULLIF(current_setting('app.share_token_hash', true), '')
                    AND revoked_at IS NULL AND expires_at > statement_timestamp()
                )
            """)
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='research_app') THEN
                REVOKE ALL ON {table} FROM research_app;
                GRANT SELECT, INSERT ON {table} TO research_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
                REVOKE ALL ON {table} FROM anon; END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
                REVOKE ALL ON {table} FROM authenticated; END IF;
        END $$;""")  # noqa: S608
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='research_app') THEN
            GRANT UPDATE (revoked_at) ON report_shares TO research_app;
        END IF;
    END $$;""")


def downgrade() -> None:
    raise RuntimeError(
        "Migration 0010 downgrade is disabled because share and export history may be "
        "in use. Revoke links and preserve artifacts before an operator-managed rollback."
    )
