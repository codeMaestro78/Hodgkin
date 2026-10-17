"""Phase 2 G source identity/relationships. HOLD: lead GO after Phase 1 gate."""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from research_api.db.source_relationships import SourceIdentityRecord, SourceRelationship

    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_sources_tenant_run_id'
                AND conrelid = 'public.sources'::regclass) THEN
                ALTER TABLE public.sources ADD CONSTRAINT uq_sources_tenant_run_id
                    UNIQUE (tenant_id, run_id, id);
            END IF;
        END $$;
    """)
    for model in (SourceIdentityRecord, SourceRelationship):
        model.metadata.tables[model.__tablename__].create(bind=op.get_bind(), checkfirst=True)
        table = model.__tablename__
        # Identifiers below come exclusively from fixed model and role names.
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_scope ON public.{table}")
        op.execute(  # noqa: S608
            f"CREATE POLICY tenant_scope ON public.{table} "
            "USING (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) "
            "WITH CHECK (tenant_id = "
            "(SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
        )
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        for role in ("anon", "authenticated", "research_app"):
            op.execute(  # noqa: S608
                f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "  # noqa: S608
                f"THEN REVOKE ALL ON public.{table} FROM {role}; END IF; END $$;"
            )
        op.execute(  # noqa: S608
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') "  # noqa: S608
            f"THEN GRANT SELECT, INSERT, DELETE ON public.{table} TO research_app; END IF; END $$;"
        )


def downgrade() -> None:
    raise RuntimeError("0014 preserves provenance; retain additive schema on application rollback")
