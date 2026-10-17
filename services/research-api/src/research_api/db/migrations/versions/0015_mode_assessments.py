"""Isolated, tenant-bound explicit-mode evidence assessments.

HOLD: apply only after lead GO at the Phase 1 gate.

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    # 0001 uses current Base.metadata; additions must tolerate already-created
    # model tables and constraints as well as an existing pre-0015 database.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_research_plans_tenant_run_id'
                  AND conrelid = 'public.research_plans'::regclass) THEN
                ALTER TABLE public.research_plans
                    ADD CONSTRAINT uq_research_plans_tenant_run_id
                    UNIQUE (tenant_id, run_id, id);
            END IF;
        END $$;
        CREATE TABLE IF NOT EXISTS public.research_assessments (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES public.tenants(id),
            run_id uuid NOT NULL,
            plan_id uuid NOT NULL,
            evidence_key varchar(64) NOT NULL,
            manifest jsonb NOT NULL,
            result jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_assessment_plan UNIQUE (tenant_id, run_id, plan_id),
            CONSTRAINT uq_assessment_evidence
                UNIQUE (tenant_id, run_id, plan_id, evidence_key),
            CONSTRAINT fk_assessment_plan_scope
                FOREIGN KEY (tenant_id, run_id, plan_id)
                REFERENCES public.research_plans(tenant_id, run_id, id),
            CONSTRAINT ck_assessment_key CHECK (length(evidence_key) BETWEEN 1 AND 64),
            CONSTRAINT ck_assessment_manifest CHECK (
                jsonb_typeof(manifest) = 'object'
                AND octet_length(manifest::text) <= 262144),
            CONSTRAINT ck_assessment_result CHECK (result IS NULL OR (
                jsonb_typeof(result) = 'object'
                AND octet_length(result::text) <= 524288))
        );
        CREATE INDEX IF NOT EXISTS ix_research_assessments_tenant_id
            ON public.research_assessments (tenant_id);
        ALTER TABLE public.research_assessments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.research_assessments FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_scope ON public.research_assessments;
        CREATE POLICY tenant_scope ON public.research_assessments
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_research_assessment()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.result IS NOT NULL THEN
                    RAISE EXCEPTION 'assessment must start without a result'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                IF (to_jsonb(NEW) - 'result') IS DISTINCT FROM
                   (to_jsonb(OLD) - 'result') THEN
                    RAISE EXCEPTION 'assessment identity and manifest are immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF OLD.result IS NOT NULL AND NEW.result IS DISTINCT FROM OLD.result THEN
                    RAISE EXCEPTION 'assessment result is write-once'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION public.freeze_research_assessment() FROM PUBLIC;
        DROP TRIGGER IF EXISTS assessment_immutable ON public.research_assessments;
        CREATE TRIGGER assessment_immutable BEFORE INSERT OR UPDATE
            ON public.research_assessments FOR EACH ROW
            EXECUTE FUNCTION public.freeze_research_assessment();
        REVOKE ALL ON public.research_assessments FROM PUBLIC;
        DO $$ DECLARE role_name text; BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'research_app'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON public.research_assessments FROM %I',
                                   role_name);
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                GRANT SELECT, INSERT, UPDATE ON public.research_assessments TO research_app;
            END IF;
        END $$;
    """)
    op.execute("""
        ALTER TABLE public.reports DROP CONSTRAINT IF EXISTS ck_report_document_v1;
        ALTER TABLE public.reports ADD CONSTRAINT ck_report_document_v1 CHECK (
            document IS NULL OR (
                jsonb_typeof(document) = 'object'
                AND COALESCE(document->>'version' IN ('1', '2'), false)
                AND octet_length(document::text) <= 524288
            )
        );
    """)


def downgrade() -> None:
    # Reinstating v1-only validation could reject published v2 data; dropping the
    # table would destroy paid-work provenance. Retain both on application rollback.
    raise RuntimeError("0015 preserves assessment provenance and version-2 report compatibility")
