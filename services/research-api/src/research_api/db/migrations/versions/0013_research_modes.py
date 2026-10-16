"""Nullable explicit research modes and independent admission ceilings."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 creates current Base.metadata, so every addition must tolerate that path.
    op.execute("SET LOCAL search_path TO public")
    for table, column, sql_type in (
        ("research_runs", "mode", "varchar(16)"),
        ("research_runs", "mode_policy_version", "varchar(64)"),
        ("budgets", "max_provider_operations", "integer"),
        ("budgets", "max_sources", "integer"),
    ):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_type}")
    constraints = (
        (
            "research_runs",
            "ck_run_mode_snapshot",
            "(mode IS NULL AND mode_policy_version IS NULL) OR "
            "(mode IN ('focused','balanced','deep') AND mode IS NOT NULL "
            "AND mode_policy_version IS NOT NULL)",
        ),
        (
            "budgets",
            "ck_budget_provider_operations_compat",
            "max_provider_operations IS NULL OR "
            "(max_provider_operations BETWEEN 2 AND 50 "
            "AND max_provider_operations = max_search_calls)",
        ),
        (
            "budgets",
            "ck_budget_sources_ceiling",
            "max_sources IS NULL OR max_sources BETWEEN 1 AND 20",
        ),
    )
    for table, name, expression in constraints:
        op.execute(f"""  -- Static migration-owned identifiers and expressions.
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = '{name}' AND conrelid = 'public.{table}'::regclass)
                THEN ALTER TABLE public.{table} ADD CONSTRAINT {name} CHECK ({expression});
                END IF;
            END $$;
        """)  # noqa: S608
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_research_mode_snapshot()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        BEGIN
            IF NEW.mode IS DISTINCT FROM OLD.mode
               OR NEW.mode_policy_version IS DISTINCT FROM OLD.mode_policy_version THEN
                RAISE EXCEPTION 'research mode policy snapshot is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS research_mode_snapshot_immutable ON public.research_runs;
        CREATE TRIGGER research_mode_snapshot_immutable
        BEFORE UPDATE OF mode, mode_policy_version ON public.research_runs
        FOR EACH ROW EXECUTE FUNCTION public.freeze_research_mode_snapshot();
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.freeze_explicit_research_budget()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        BEGIN
            -- Plain MVCC read: do not take a run lock after the budget lock.
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
        CREATE TRIGGER explicit_research_budget_immutable BEFORE UPDATE ON public.budgets
        FOR EACH ROW EXECUTE FUNCTION public.freeze_explicit_research_budget();
    """)


def downgrade() -> None:
    raise RuntimeError("0013 preserves immutable policy provenance; retain columns on app rollback")
