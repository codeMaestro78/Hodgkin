"""Apply explicit-mode snapshot guards to databases already past revision 0013.

Revision ID: 0019
Revises: 0018

The tightened 0013 bootstrap definition protects fresh installs, but editing an
applied migration cannot change an existing database. Reinstall both functions
and their triggers as an additive forward migration.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_research_mode_snapshot()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF NEW.mode IS DISTINCT FROM OLD.mode
               OR NEW.mode_policy_version IS DISTINCT FROM OLD.mode_policy_version THEN
                RAISE EXCEPTION 'research mode policy snapshot is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.mode IS NOT NULL AND (
                NEW.original_question IS DISTINCT FROM OLD.original_question
                OR NEW.normalized_question IS DISTINCT FROM OLD.normalized_question
                OR NEW.report_requirements IS DISTINCT FROM OLD.report_requirements
            ) THEN
                RAISE EXCEPTION 'explicit research brief snapshot is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS research_mode_snapshot_immutable ON public.research_runs;
        CREATE TRIGGER research_mode_snapshot_immutable
        BEFORE UPDATE OF mode, mode_policy_version, original_question,
                         normalized_question, report_requirements ON public.research_runs
        FOR EACH ROW EXECUTE FUNCTION public.freeze_research_mode_snapshot();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_explicit_research_budget()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            -- Do not take a run lock after the budget lock.
            IF TG_OP = 'DELETE' THEN
                -- The exact table owner may perform FK-ordered retention erasure.
                IF current_user = pg_catalog.pg_get_userbyid(
                    (SELECT c.relowner FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID)
                ) THEN
                    RETURN OLD;
                END IF;
                IF EXISTS (SELECT 1 FROM public.research_runs r
                    WHERE r.tenant_id = OLD.tenant_id AND r.id = OLD.run_id AND r.mode IS NOT NULL)
                THEN
                    RAISE EXCEPTION 'explicit research budget snapshot is immutable'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF ROW(NEW.tenant_id, NEW.run_id, NEW.id) IS DISTINCT FROM
               ROW(OLD.tenant_id, OLD.run_id, OLD.id) THEN
                RAISE EXCEPTION 'research budget ownership is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.max_wall_clock_ms, NEW.max_search_calls, NEW.max_provider_operations,
                   NEW.max_sources, NEW.max_browser_sessions, NEW.max_reflection_rounds,
                   NEW.max_input_tokens, NEW.max_output_tokens, NEW.max_estimated_cost_usd)
               IS DISTINCT FROM
               ROW(OLD.max_wall_clock_ms, OLD.max_search_calls, OLD.max_provider_operations,
                   OLD.max_sources, OLD.max_browser_sessions, OLD.max_reflection_rounds,
                   OLD.max_input_tokens, OLD.max_output_tokens, OLD.max_estimated_cost_usd)
               AND EXISTS (SELECT 1 FROM public.research_runs r
                   WHERE r.tenant_id = OLD.tenant_id AND r.id = OLD.run_id AND r.mode IS NOT NULL)
            THEN
                RAISE EXCEPTION 'explicit research budget snapshot is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS explicit_research_budget_immutable ON public.budgets;
        CREATE TRIGGER explicit_research_budget_immutable BEFORE UPDATE OR DELETE ON public.budgets
        FOR EACH ROW EXECUTE FUNCTION public.freeze_explicit_research_budget();
    """)


def downgrade() -> None:
    raise RuntimeError("0019 preserves explicit-mode snapshot immutability on application rollback")
