"""Supabase profiles and automatic personal workspace provisioning.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.user_profiles (
            id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL REFERENCES public.tenants(id),
            full_name varchar(120) NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT profile_personal_workspace CHECK (tenant_id = id),
            CONSTRAINT profile_user_workspace FOREIGN KEY (tenant_id, id)
                REFERENCES public.users(tenant_id, id)
        );
        ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.user_profiles FORCE ROW LEVEL SECURITY;
        CREATE POLICY profile_tenant_scope ON public.user_profiles
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

        CREATE FUNCTION public.provision_research_account(account_id uuid, metadata jsonb)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE old_tenant text := current_setting('app.tenant_id', true);
        BEGIN
            PERFORM set_config('app.tenant_id', account_id::text, true);
            INSERT INTO public.tenants (id, name) VALUES (account_id, 'Personal workspace')
                ON CONFLICT (id) DO NOTHING;
            INSERT INTO public.users (id, tenant_id, external_subject)
                VALUES (account_id, account_id, 'supabase:' || account_id::text)
                ON CONFLICT (id) DO NOTHING;
            INSERT INTO public.user_profiles (id, tenant_id, full_name)
                VALUES (account_id, account_id,
                    left(coalesce(metadata->>'full_name', metadata->>'name', ''), 120))
                ON CONFLICT (id) DO NOTHING;
            PERFORM set_config('app.tenant_id', coalesce(old_tenant, ''), true);
        END $$;
        REVOKE ALL ON FUNCTION public.provision_research_account(uuid, jsonb) FROM PUBLIC;

        CREATE FUNCTION public.handle_research_auth_user()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            PERFORM public.provision_research_account(NEW.id, NEW.raw_user_meta_data);
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION public.handle_research_auth_user() FROM PUBLIC;

        CREATE FUNCTION public.touch_research_profile()
        RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION public.touch_research_profile() FROM PUBLIC;
        CREATE TRIGGER research_profile_updated BEFORE UPDATE ON public.user_profiles
            FOR EACH ROW EXECUTE FUNCTION public.touch_research_profile();

        DO $$ DECLARE account record; table_name text; BEGIN
            IF to_regclass('auth.users') IS NOT NULL THEN
                ALTER TABLE public.user_profiles ADD CONSTRAINT profile_auth_user
                    FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;
                CREATE TRIGGER research_auth_user_created AFTER INSERT ON auth.users
                    FOR EACH ROW EXECUTE FUNCTION public.handle_research_auth_user();
                FOR account IN SELECT id, raw_user_meta_data FROM auth.users LOOP
                    PERFORM public.provision_research_account(
                        account.id, account.raw_user_meta_data);
                END LOOP;
                -- Browser access is limited to the user's own profile. The app's
                -- research tables remain reachable only through the verified BFF.
                REVOKE ALL ON public.user_profiles FROM anon, authenticated;
                GRANT SELECT ON public.user_profiles TO authenticated;
                GRANT UPDATE (full_name) ON public.user_profiles TO authenticated;
                CREATE POLICY profile_self_read ON public.user_profiles FOR SELECT
                    TO authenticated USING ((SELECT auth.uid()) = id);
                CREATE POLICY profile_self_update ON public.user_profiles FOR UPDATE
                    TO authenticated USING ((SELECT auth.uid()) = id)
                    WITH CHECK ((SELECT auth.uid()) = id);
                FOR table_name IN SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public' AND tablename IN (
                        'tenants','users','research_runs','research_plans','sub_questions',
                        'sub_question_attempts','sources','evidence_claims','citations',
                        'contradictions','gaps','budgets','usage_ledger','provider_call_reservations',
                        'provider_calls','node_executions','run_events','reports','evaluations'
                    ) LOOP
                    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', table_name);
                END LOOP;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_profiles TO research_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Existing auth identities and research rows are intentionally preserved.
    op.execute("""
        DO $$ BEGIN IF to_regclass('auth.users') IS NOT NULL THEN
            DROP TRIGGER IF EXISTS research_auth_user_created ON auth.users;
        END IF; END $$;
        DROP TABLE public.user_profiles;
        DROP FUNCTION public.touch_research_profile();
        DROP FUNCTION public.handle_research_auth_user();
        DROP FUNCTION public.provision_research_account(uuid, jsonb);
    """)
