"""Exercise Supabase-like signup triggers/RLS in a disposable local database."""

import importlib
import os
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_AUTH_SCHEMA_TESTS") != "1",
        reason="set RUN_AUTH_SCHEMA_TESTS=1 for local DB checks",
    ),
]


def test_signup_provisioning_and_user_isolation() -> None:
    # conftest validates this target is local, including CI's selected port.
    admin_url = make_url(os.environ["TEST_DATABASE_ADMIN_URL"])
    admin = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
    )
    name = "research_auth_test_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(admin_url.set(database=name))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("""
                    DO $$ BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                            CREATE ROLE anon NOLOGIN; END IF;
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                            CREATE ROLE authenticated NOLOGIN; END IF;
                    END $$;
                    CREATE SCHEMA auth;
                    CREATE TABLE auth.users (id uuid PRIMARY KEY, raw_user_meta_data jsonb);
                    CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
                        SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
                    $$;
                    GRANT USAGE ON SCHEMA auth, public TO authenticated;
                    -- Mimic Supabase's explicit default API-role function grants.
                    ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;
                """)
                with Operations.context(MigrationContext.configure(connection)):
                    for version in [
                        "0001_authoritative_core",
                        "0002_run_idempotency",
                        "0003_supabase_accounts",
                        "0004_auth_function_grants",
                        "0005_evidence_reliability",
                        "0006_extraction_admission",
                        "0007_durable_runtime",
                    ]:
                        importlib.import_module(
                            f"research_api.db.migrations.versions.{version}"
                        ).upgrade()
                first, second = uuid.uuid4(), uuid.uuid4()
                for subject in [first, second]:
                    connection.execute(
                        text("INSERT INTO auth.users VALUES (:id, CAST(:metadata AS jsonb))"),
                        {
                            "id": subject,
                            "metadata": '{"full_name":"Fixture researcher","tenant_id":"forged"}',
                        },
                    )
                assert connection.execute(text("SELECT count(*) FROM user_profiles")).scalar() == 2
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM users WHERE id = tenant_id")
                    ).scalar()
                    == 2
                )
                # Trigger restores the caller's original tenant transaction context.
                assert (
                    connection.execute(
                        text("SELECT current_setting('app.tenant_id', true)")
                    ).scalar()
                    == ""
                )
                connection.exec_driver_sql("SET LOCAL ROLE authenticated")
                connection.execute(
                    text("SELECT set_config('request.jwt.claim.sub', :id, true)"),
                    {"id": str(first)},
                )
                visible = connection.execute(text("SELECT id, tenant_id FROM user_profiles")).all()
                assert visible == [(first, first)]
                connection.execute(
                    text("UPDATE user_profiles SET full_name = 'Updated' WHERE id = :id"),
                    {"id": first},
                )
                assert (
                    connection.execute(text("SELECT full_name FROM user_profiles")).scalar()
                    == "Updated"
                )
                for sql in [
                    "SELECT * FROM research_runs",
                    "SELECT * FROM extraction_slots",
                    "SELECT * FROM runtime_jobs",
                    "SELECT * FROM plan_approvals",
                    "SELECT * FROM research_batches",
                    "SELECT * FROM research_schedules",
                    "SELECT * FROM dispatch_registry",
                    "SELECT * FROM research_checkpoints.checkpoints",
                    "UPDATE user_profiles SET tenant_id = id",
                    "DELETE FROM user_profiles",
                    "SELECT public.provision_research_account(gen_random_uuid(), '{}'::jsonb)",
                ]:
                    with connection.begin_nested() as savepoint:
                        with pytest.raises(DBAPIError):
                            connection.exec_driver_sql(sql)
                        savepoint.rollback()
                connection.exec_driver_sql("RESET ROLE")
                connection.exec_driver_sql("SET LOCAL ROLE research_app")
                with connection.begin_nested() as savepoint:
                    with pytest.raises(DBAPIError):
                        connection.exec_driver_sql(
                            "SELECT * FROM research_checkpoints.checkpoint_migrations"
                        )
                    savepoint.rollback()
                connection.exec_driver_sql("RESET ROLE")
                connection.exec_driver_sql("SET LOCAL ROLE anon")
                with connection.begin_nested() as savepoint:
                    with pytest.raises(DBAPIError):
                        connection.exec_driver_sql("SELECT * FROM user_profiles")
                    savepoint.rollback()
            finally:
                transaction.rollback()  # Includes fixture rows, schemas and any fixture roles.
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()
