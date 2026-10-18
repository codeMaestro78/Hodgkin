"""Run the shadow-table migration and tenant/grant checks in a disposable DB.

Set RUN_BILLING_SHADOW_DB_TESTS=1 to opt in. The test refuses non-loopback
database URLs via tests/conftest.py and drops only the database it creates.
"""

import importlib
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_BILLING_SHADOW_DB_TESTS") != "1",
        reason="set RUN_BILLING_SHADOW_DB_TESTS=1 to use a disposable local database",
    ),
]


def test_shadow_observations_are_tenant_isolated_and_append_only() -> None:
    admin_url = make_url(os.environ["TEST_DATABASE_ADMIN_URL"])
    app_url = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    database = "billing_shadow_test_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    owner = create_engine(admin_url.set(database=database))
    app = create_engine(app_url.set(database=database))
    try:
        with owner.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE tenants (id uuid PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE users (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, "
                "UNIQUE (tenant_id, id))"
            )
            connection.exec_driver_sql(
                "CREATE TABLE research_runs (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, "
                "UNIQUE (tenant_id, id))"
            )
            shadow_migration = importlib.import_module(
                "research_api.db.migrations.versions.0021_billing_shadow_observations"
            )
            entitlement_migration = importlib.import_module(
                "research_api.db.migrations.versions.0022_billing_entitlement_read_model"
            )
            from alembic.migration import MigrationContext
            from alembic.operations import Operations

            with Operations.context(MigrationContext.configure(connection)):
                shadow_migration.upgrade()
                entitlement_migration.upgrade()

        tenants = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        users = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        runs = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        tenants[1] = tenants[0]
        accounts = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        periods = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        with owner.begin() as connection:
            for tenant, user, run in zip(tenants, users, runs, strict=True):
                connection.execute(
                    text("INSERT INTO tenants VALUES (:tenant) ON CONFLICT DO NOTHING"),
                    {"tenant": tenant},
                )
                connection.execute(
                    text("INSERT INTO users VALUES (:user, :tenant)"),
                    {"user": user, "tenant": tenant},
                )
                connection.execute(
                    text("INSERT INTO research_runs VALUES (:run, :tenant)"),
                    {"run": run, "tenant": tenant},
                )
            for index, (tenant, user) in enumerate(zip(tenants, users, strict=True)):
                connection.execute(
                    text("""
                        INSERT INTO billing_accounts (id, tenant_id, user_id, account_type)
                        VALUES (:account, :tenant, :user, 'personal')
                    """),
                    {"account": accounts[index], "tenant": tenant, "user": user},
                )
                connection.execute(
                    text("""
                        INSERT INTO billing_periods
                            (id, tenant_id, billing_account_id, plan_key, catalog_version,
                             state, allowance_units, starts_at, ends_at)
                        VALUES (:period, :tenant, :account, 'scholar', 'test-catalog',
                                'active', 40, '2026-10-01T00:00:00Z', '2026-11-01T00:00:00Z')
                    """),
                    {
                        "period": periods[index],
                        "tenant": tenant,
                        "account": accounts[index],
                    },
                )
                connection.execute(
                    text("""
                        INSERT INTO billing_unit_entries
                            (id, tenant_id, billing_account_id, billing_period_id,
                             entry_type, consumed_delta, reserved_delta, idempotency_key)
                        VALUES (:id, :tenant, :account, :period, 'reservation', 0, 4, 'seed')
                    """),
                    {
                        "id": uuid.uuid4(),
                        "tenant": tenant,
                        "account": accounts[index],
                        "period": periods[index],
                    },
                )

        with owner.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenants[0])},
            )
            connection.execute(
                text("SELECT set_config('app.user_id', :user, true)"),
                {"user": str(users[0])},
            )
            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError) as immutable_period:
                connection.execute(
                    text("UPDATE billing_periods SET allowance_units = 41 WHERE id = :id"),
                    {"id": periods[0]},
                )
            assert immutable_period.value.orig.sqlstate == "23514"
            savepoint.rollback()

            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError) as append_only_entry:
                connection.execute(
                    text("DELETE FROM billing_unit_entries WHERE billing_period_id = :id"),
                    {"id": periods[0]},
                )
            assert append_only_entry.value.orig.sqlstate == "23514"
            savepoint.rollback()

        for index in (0, 2):
            with app.begin() as connection:
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant, true)"),
                    {"tenant": str(tenants[index])},
                )
                connection.execute(
                    text("SELECT set_config('app.user_id', :user, true)"),
                    {"user": str(users[index])},
                )
                connection.execute(
                    text("""
                        INSERT INTO billing_shadow_observations
                            (id, tenant_id, user_id, run_id, mode, decision_status,
                             proposed_units, policy_version, catalog_version)
                        VALUES (:id, :tenant, :user, :run, 'focused', 'provisional', 1,
                                'approved-mode-weights-1-2-4-v1',
                                'research-units-v2-2026-10-19')
                    """),
                    {
                        "id": uuid.uuid4(),
                        "tenant": tenants[index],
                        "user": users[index],
                        "run": runs[index],
                    },
                )

        with app.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenants[0])},
            )
            connection.execute(
                text("SELECT set_config('app.user_id', :user, true)"),
                {"user": str(users[0])},
            )
            assert connection.scalar(text("SELECT count(*) FROM billing_shadow_observations")) == 1
            assert connection.scalar(text("SELECT count(*) FROM billing_accounts")) == 1
            assert connection.scalar(text("SELECT count(*) FROM billing_periods")) == 1
            assert connection.scalar(text("SELECT count(*) FROM billing_unit_entries")) == 1
            assert connection.scalar(
                text("""
                    SELECT has_table_privilege(
                        current_user, 'billing_shadow_observations', 'SELECT'
                    ) AND has_table_privilege(
                        current_user, 'billing_shadow_observations', 'INSERT'
                    ) AND NOT has_table_privilege(
                        current_user, 'billing_shadow_observations', 'UPDATE'
                    ) AND NOT has_table_privilege(
                        current_user, 'billing_shadow_observations', 'DELETE'
                    )
                """)
            )
            assert connection.scalar(
                text("""
                    SELECT has_table_privilege(
                        current_user, 'billing_accounts', 'SELECT'
                    ) AND NOT has_table_privilege(
                        current_user, 'billing_accounts', 'INSERT'
                    ) AND NOT has_table_privilege(
                        current_user, 'billing_periods', 'UPDATE'
                    ) AND NOT has_table_privilege(
                        current_user, 'billing_unit_entries', 'DELETE'
                    )
                """)
            )
            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("""
                        INSERT INTO billing_shadow_observations
                            (id, tenant_id, user_id, run_id, mode, decision_status,
                             proposed_units, policy_version, catalog_version)
                        VALUES (:id, :tenant, :user, :run, 'focused', 'provisional', 1,
                                'approved-mode-weights-1-2-4-v1',
                                'research-units-v2-2026-10-19')
                    """),
                    {
                        "id": uuid.uuid4(),
                        "tenant": tenants[2],
                        "user": users[2],
                        "run": runs[2],
                    },
                )
            savepoint.rollback()
    finally:
        owner.dispose()
        app.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}"')
        admin.dispose()
