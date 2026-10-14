-- Apply after migration 0007 using the migration principal.
-- No password belongs in this file. Enable LOGIN separately with a generated
-- SCRAM verifier, verify connectivity, then switch the server DATABASE_URL.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
    CREATE ROLE research_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOINHERIT NOREPLICATION NOBYPASSRLS;
  ELSE
    RAISE EXCEPTION 'research_app already exists; review rather than overwrite it';
  END IF;
END $$;

GRANT CONNECT ON DATABASE postgres TO research_app;
GRANT USAGE ON SCHEMA public, research_checkpoints TO research_app;
GRANT SELECT ON public.users TO research_app;
GRANT SELECT, INSERT, UPDATE ON
  public.research_runs, public.research_plans, public.sub_questions,
  public.sub_question_attempts, public.sources, public.evidence_claims,
  public.citations, public.gaps, public.budgets, public.usage_ledger,
  public.provider_call_reservations, public.provider_calls,
  public.node_executions, public.run_events, public.reports,
  public.extraction_slots, public.dispatch_registry, public.runtime_jobs,
  public.plan_approvals, public.research_batches, public.research_schedules
TO research_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  research_checkpoints.checkpoints, research_checkpoints.checkpoint_blobs,
  research_checkpoints.checkpoint_writes TO research_app;
-- No memberships, table ownership, migration metadata, auth/storage access,
-- sequence grants (all identifiers are UUIDs), blanket/default grants or DDL.
