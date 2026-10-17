"""Private folders and saves pinned to immutable report/source IDs."""

from typing import cast

from alembic import op
from sqlalchemy import Table

from research_api.db.models import LibraryItem, Project

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0007 sets a transaction-local checkpoint search path; Alembic may run
    # several revisions in one transaction on both fresh and upgraded installs.
    op.execute("SET LOCAL search_path TO public")
    owner = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
        "AND user_id = NULLIF(current_setting('app.user_id', true), '')::uuid"
    )
    target = """(
        EXISTS (SELECT 1 FROM reports r JOIN research_runs run
            ON run.tenant_id=r.tenant_id AND run.id=r.run_id
            WHERE r.tenant_id=library_items.tenant_id AND r.id=library_items.report_id
                AND r.published AND run.user_id=library_items.user_id)
        OR EXISTS (SELECT 1 FROM sources s JOIN research_runs run
            ON run.tenant_id=s.tenant_id AND run.id=s.run_id
            WHERE s.tenant_id=library_items.tenant_id AND s.id=library_items.source_id
                AND run.user_id=library_items.user_id)
    )"""
    for model in (Project, LibraryItem):
        cast(Table, model.__table__).create(op.get_bind(), checkfirst=True)
        table = model.__tablename__
        predicate = owner if model is Project else f"({owner}) AND {target}"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_scope ON {table} USING ({predicate}) WITH CHECK ({predicate})"
        )
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        # 0001 creates today's metadata and may have granted broad runtime access.
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
            GRANT DELETE ON library_items TO research_app;
            GRANT UPDATE (project_id, tags, notes) ON library_items TO research_app;
        END IF;
    END $$;""")


def downgrade() -> None:
    raise RuntimeError(
        "Migration 0009 downgrade is disabled because it would delete saved library data. "
        "Preserve or export library_items and projects before an operator-managed rollback."
    )
