"""Exercise billing grants, reservation races, and settlement on disposable PostgreSQL.

Set RUN_BILLING_LEDGER_DB_TESTS=1 to opt in. The test creates and drops only a
uniquely named database on the loopback admin service.
"""

import asyncio
import importlib
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api.billing.catalog import BILLING_CATALOG, LEGACY_BILLING_CATALOG
from research_api.billing.entitlements import read_entitlement
from research_api.billing.ledger import (
    BillingAdjustmentConflict,
    BillingAdjustmentUnavailable,
    BillingGrantConflict,
    BillingReservationConflict,
    BillingUnitsExhausted,
    adjust_units,
    ensure_default_free_period,
    ensure_period_grant,
    reserve_units,
    transition_period_state,
)
from research_api.billing.lifecycle import settle_terminal_run
from research_api.db.models import BillingPeriod, BillingUnitEntry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_BILLING_LEDGER_DB_TESTS") != "1",
        reason="set RUN_BILLING_LEDGER_DB_TESTS=1 to use a disposable local database",
    ),
]


async def test_billing_ledger_serializes_last_unit_and_replays_terminal_work() -> None:
    admin_url = make_url(os.environ["TEST_DATABASE_ADMIN_URL"])
    app_url = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    database = "billing_ledger_test_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    owner = create_engine(admin_url.set(database=database))
    sync_app = create_engine(app_url.set(database=database))
    async_app_url = app_url.set(database=database)
    async_engine = create_async_engine(async_app_url)
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    try:
        tenant = uuid.uuid4()
        users = [uuid.uuid4() for _ in range(4)]
        racing_runs = [uuid.uuid4(), uuid.uuid4()]
        period_id = uuid.uuid4()
        account_id = uuid.uuid4()
        now = datetime(2026, 10, 19, 12, tzinfo=UTC)
        starts_at = datetime(2026, 10, 1, tzinfo=UTC)
        ends_at = datetime(2026, 11, 1, tzinfo=UTC)

        with owner.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE tenants (id uuid PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE users (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, "
                "UNIQUE (tenant_id, id))"
            )
            connection.exec_driver_sql(
                "CREATE TABLE research_runs (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, "
                "user_id uuid NOT NULL, mode varchar(16), status varchar(32) NOT NULL, "
                "UNIQUE (tenant_id, id))"
            )
            connection.exec_driver_sql(
                "CREATE TABLE provider_call_reservations (id uuid PRIMARY KEY, "
                "tenant_id uuid NOT NULL, run_id uuid NOT NULL, state varchar(32) NOT NULL)"
            )
            connection.exec_driver_sql("GRANT SELECT ON research_runs TO research_app")
            connection.exec_driver_sql("GRANT SELECT ON provider_call_reservations TO research_app")
            migrations = [
                importlib.import_module(
                    "research_api.db.migrations.versions.0021_billing_shadow_observations"
                ),
                importlib.import_module(
                    "research_api.db.migrations.versions.0022_billing_entitlement_read_model"
                ),
                importlib.import_module(
                    "research_api.db.migrations.versions.0023_billing_ledger_write_guards"
                ),
            ]
            from alembic.migration import MigrationContext
            from alembic.operations import Operations

            with Operations.context(MigrationContext.configure(connection)):
                for migration in migrations:
                    migration.upgrade()

            # 0022 builds current ORM metadata in this checkout; remove only the
            # new audit fields to model an actual database stopped at 0023.
            connection.exec_driver_sql(
                "ALTER TABLE public.billing_unit_entries "
                "DROP CONSTRAINT IF EXISTS ck_billing_adjustment_audit"
            )
            connection.exec_driver_sql(
                "ALTER TABLE public.billing_unit_entries "
                "DROP COLUMN IF EXISTS actor_id, DROP COLUMN IF EXISTS reason"
            )
            adjustment_migration = importlib.import_module(
                "research_api.db.migrations.versions.0024_billing_audited_adjustments"
            )
            with Operations.context(MigrationContext.configure(connection)):
                adjustment_migration.upgrade()

            # Model pre-0025 batch/schedule tables without their new snapshots.
            connection.exec_driver_sql("CREATE TABLE public.research_batches (id uuid PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE public.research_schedules (id uuid PRIMARY KEY)"
            )
            mode_migration = importlib.import_module(
                "research_api.db.migrations.versions.0025_batch_schedule_mode_snapshots"
            )
            with Operations.context(MigrationContext.configure(connection)):
                mode_migration.upgrade()
            webhook_migration = importlib.import_module(
                "research_api.db.migrations.versions.0026_billing_enforcement_webhook"
            )
            with Operations.context(MigrationContext.configure(connection)):
                webhook_migration.upgrade()
            stripe_projection = importlib.import_module(
                "research_api.db.migrations.versions.0027_stripe_subscription_projection"
            )
            with Operations.context(MigrationContext.configure(connection)):
                stripe_projection.upgrade()
            billing_state_migration = importlib.import_module(
                "research_api.db.migrations.versions.0028_billing_period_state_transitions"
            )
            with Operations.context(MigrationContext.configure(connection)):
                billing_state_migration.upgrade()
            webhook_columns = set(
                connection.execute(
                    text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'stripe_webhook_events'
                """)
                ).scalars()
            )
            assert {
                "event_id",
                "event_type",
                "event_created_at",
                "object_id",
                "livemode",
                "processing_status",
                "received_at",
            } <= webhook_columns
            assert connection.scalar(
                text("""
                SELECT has_table_privilege('research_app',
                    'public.stripe_webhook_events', 'INSERT')
            """)
            )
            assert connection.scalar(
                text("""
                SELECT has_table_privilege('research_app',
                    'public.stripe_webhook_events', 'UPDATE')
            """)
            )
            assert not connection.scalar(
                text("""
                SELECT has_table_privilege('anon',
                    'public.stripe_customer_links', 'SELECT')
            """)
            )
            assert connection.scalar(
                text("""
                    SELECT has_function_privilege(
                        'research_app',
                        'public.transition_billing_period_state(uuid,uuid,uuid,text,timestamptz)',
                        'EXECUTE'
                    )
                """)
            )
            assert not connection.scalar(
                text("SELECT has_table_privilege('research_app', 'billing_periods', 'UPDATE')")
            )
            for table in (
                "stripe_webhook_events",
                "stripe_customer_links",
                "stripe_subscriptions",
                "stripe_checkout_attempts",
            ):
                rls = connection.execute(
                    text("""
                        SELECT relrowsecurity, relforcerowsecurity
                        FROM pg_class WHERE oid = to_regclass(:table_name)
                    """),
                    {"table_name": f"public.{table}"},
                ).one()
                assert rls == (True, True)
            for table in ("research_batches", "research_schedules"):
                columns = set(
                    connection.execute(
                        text("""
                            SELECT column_name FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = :table
                        """),
                        {"table": table},
                    ).scalars()
                )
                assert {"mode", "mode_policy_version"} <= columns
                savepoint = connection.begin_nested()
                insert_invalid_snapshot = {
                    "research_batches": text("""
                        INSERT INTO public.research_batches
                            (id, mode, mode_policy_version)
                        VALUES (:id, 'unknown', 'research-mode-policy-v1')
                    """),
                    "research_schedules": text("""
                        INSERT INTO public.research_schedules
                            (id, mode, mode_policy_version)
                        VALUES (:id, 'unknown', 'research-mode-policy-v1')
                    """),
                }[table]
                with pytest.raises(IntegrityError) as invalid_snapshot:
                    connection.execute(
                        insert_invalid_snapshot,
                        {"id": uuid.uuid4()},
                    )
                assert invalid_snapshot.value.orig.sqlstate == "23514"
                savepoint.rollback()

            connection.execute(text("INSERT INTO tenants VALUES (:tenant)"), {"tenant": tenant})
            for user in users:
                connection.execute(
                    text("INSERT INTO users VALUES (:user, :tenant)"),
                    {"user": user, "tenant": tenant},
                )
            connection.execute(
                text(
                    "INSERT INTO billing_accounts (id, tenant_id, user_id, account_type) "
                    "VALUES (:id, :tenant, :user, 'personal')"
                ),
                {"id": account_id, "tenant": tenant, "user": users[0]},
            )
            connection.execute(
                text("""
                    INSERT INTO billing_periods
                        (id, tenant_id, billing_account_id, plan_key, catalog_version,
                         state, allowance_units, starts_at, ends_at)
                    VALUES (:period, :tenant, :account, 'scholar', 'test-catalog',
                            'active', 40, :starts, :ends)
                """),
                {
                    "period": period_id,
                    "tenant": tenant,
                    "account": account_id,
                    "starts": starts_at,
                    "ends": ends_at,
                },
            )
            connection.execute(
                text("""
                    INSERT INTO billing_unit_entries
                        (id, tenant_id, billing_account_id, billing_period_id, entry_type,
                         consumed_delta, reserved_delta, idempotency_key)
                    VALUES (:id, :tenant, :account, :period, 'reservation', 0, 39, 'seed')
                """),
                {
                    "id": uuid.uuid4(),
                    "tenant": tenant,
                    "account": account_id,
                    "period": period_id,
                },
            )
            for run_id in racing_runs:
                connection.execute(
                    text(
                        "INSERT INTO research_runs VALUES "
                        "(:id, :tenant, :user, 'focused', 'queued')"
                    ),
                    {"id": run_id, "tenant": tenant, "user": users[0]},
                )

        approved_catalog = replace(
            LEGACY_BILLING_CATALOG,
            version="test-catalog",
            status="active",
        )
        approved_catalogs = {approved_catalog.version: approved_catalog}

        async def set_identity(session, user_id: uuid.UUID) -> None:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant)},
            )
            await session.execute(
                text("SELECT set_config('app.user_id', :user, true)"),
                {"user": str(user_id)},
            )

        customer_id = "cus_disposable_" + uuid.uuid4().hex
        with sync_app.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant)},
            )
            connection.execute(
                text("SELECT set_config('app.user_id', :user, true)"),
                {"user": str(users[0])},
            )
            connection.execute(
                text("""
                    INSERT INTO stripe_customer_links (stripe_customer_id, tenant_id, user_id)
                    VALUES (:customer, :tenant, :user)
                """),
                {"customer": customer_id, "tenant": tenant, "user": users[0]},
            )
            assert connection.scalar(text("SELECT count(*) FROM stripe_customer_links")) == 1
            connection.execute(
                text("SELECT set_config('app.user_id', :user, true)"),
                {"user": str(users[1])},
            )
            assert connection.scalar(text("SELECT count(*) FROM stripe_customer_links")) == 0
            connection.execute(text("SELECT set_config('app.billing_system', 'on', true)"))
            assert connection.scalar(text("SELECT count(*) FROM stripe_customer_links")) == 1
            connection.execute(
                text("""
                    INSERT INTO stripe_webhook_events
                        (event_id, event_type, livemode, processing_status)
                    VALUES ('evt_disposable', 'customer.subscription.created', false, 'received')
                """)
            )
            connection.execute(
                text(
                    "UPDATE stripe_webhook_events SET processing_status='processed' "
                    "WHERE event_id='evt_disposable'"
                )
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT processing_status FROM stripe_webhook_events "
                        "WHERE event_id='evt_disposable'"
                    )
                )
                == "processed"
            )

        now = datetime.now(UTC).replace(microsecond=0)
        async with session_factory() as session, session.begin():
            await set_identity(session, users[2])
            paid_period = await ensure_period_grant(
                session,
                tenant_id=tenant,
                user_id=users[2],
                plan_key="scholar",
                catalog_version=BILLING_CATALOG.version,
                starts_at=now - timedelta(days=1),
                ends_at=now + timedelta(days=29),
            )
            await session.flush()
            projection = await read_entitlement(
                session, tenant_id=tenant, user_id=users[2], now=now
            )
            assert projection.plan_key == "scholar"
            assert projection.period_start == paid_period.starts_at
            assert projection.period_end == paid_period.ends_at
            assert projection.available_units == 20

        async with session_factory() as session, session.begin():
            await set_identity(session, users[3])
            expired_start = now - timedelta(days=2)
            expired_end = now - timedelta(hours=1)
            await ensure_period_grant(
                session,
                tenant_id=tenant,
                user_id=users[3],
                plan_key="scholar",
                catalog_version=BILLING_CATALOG.version,
                starts_at=expired_start,
                ends_at=expired_end,
            )
            free_period = await ensure_default_free_period(
                session, tenant_id=tenant, user_id=users[3], now=now
            )
            assert free_period.plan_key == "free"
            assert free_period.starts_at == datetime(now.year, now.month, 1, tzinfo=UTC)
            assert (
                await session.scalar(
                    select(BillingPeriod.state).where(
                        BillingPeriod.tenant_id == tenant,
                        BillingPeriod.starts_at == expired_start,
                    )
                )
                == "ended"
            )

        async def verify_and_run() -> None:
            async with session_factory() as session, session.begin():
                await set_identity(session, users[0])
                grant = await ensure_period_grant(
                    session,
                    tenant_id=tenant,
                    user_id=users[0],
                    plan_key="scholar",
                    catalog_version="test-catalog",
                    starts_at=starts_at,
                    ends_at=ends_at,
                    approved_catalogs=approved_catalogs,
                )
                assert grant.id == period_id
                with pytest.raises(BillingGrantConflict):
                    await ensure_period_grant(
                        session,
                        tenant_id=tenant,
                        user_id=users[0],
                        plan_key="scholar",
                        catalog_version="test-catalog",
                        starts_at=datetime(2026, 10, 15, tzinfo=UTC),
                        ends_at=datetime(2026, 11, 15, tzinfo=UTC),
                        approved_catalogs=approved_catalogs,
                    )

            admission_barrier = asyncio.Barrier(2)

            async def try_reserve(run_id: uuid.UUID) -> tuple[str, int | None]:
                try:
                    async with session_factory() as session, session.begin():
                        await set_identity(session, users[0])
                        await admission_barrier.wait()
                        reservation = await reserve_units(
                            session,
                            tenant_id=tenant,
                            user_id=users[0],
                            run_id=run_id,
                            mode="focused",
                            idempotency_key=f"reserve:{run_id}",
                            now=now,
                            approved_catalogs=approved_catalogs,
                        )
                        return "reserved", reservation.reserved_delta
                except BillingUnitsExhausted:
                    return "exhausted", None

            results = await asyncio.gather(*(try_reserve(run_id) for run_id in racing_runs))
            assert sorted(result[0] for result in results) == ["exhausted", "reserved"]
            accepted_index = next(
                index for index, result in enumerate(results) if result[0] == "reserved"
            )
            accepted_run = racing_runs[accepted_index]

            async with session_factory() as session, session.begin():
                await set_identity(session, users[0])
                reservation = await reserve_units(
                    session,
                    tenant_id=tenant,
                    user_id=users[0],
                    run_id=accepted_run,
                    mode="focused",
                    idempotency_key=f"reserve:{accepted_run}",
                    now=now,
                    approved_catalogs=approved_catalogs,
                )
                assert reservation.reserved_delta == 1
                assert await session.scalar(text("SELECT count(*) FROM billing_accounts")) == 1
                with pytest.raises(BillingReservationConflict):
                    await reserve_units(
                        session,
                        tenant_id=tenant,
                        user_id=users[0],
                        run_id=accepted_run,
                        mode="focused",
                        idempotency_key=f"different:{accepted_run}",
                        now=now,
                        approved_catalogs=approved_catalogs,
                    )

            with owner.begin() as connection:
                connection.execute(
                    text("UPDATE research_runs SET status = 'completed' WHERE id = :id"),
                    {"id": accepted_run},
                )

            async with session_factory() as session, session.begin():
                await set_identity(session, users[0])
                terminal_run = SimpleNamespace(
                    tenant_id=tenant,
                    user_id=users[0],
                    id=accepted_run,
                    status="completed",
                )
                assert await settle_terminal_run(session, terminal_run)
                settlement = await session.scalar(
                    select(BillingUnitEntry).where(
                        BillingUnitEntry.run_id == accepted_run,
                        BillingUnitEntry.entry_type == "consumption",
                    )
                )
                assert settlement is not None
                assert settlement.consumed_delta == 1

            async with session_factory() as session, session.begin():
                await set_identity(session, users[0])
                assert await settle_terminal_run(session, terminal_run)
                totals = (
                    await session.execute(
                        text("""
                        SELECT sum(consumed_delta), sum(reserved_delta)
                        FROM billing_unit_entries WHERE billing_period_id = :period
                    """),
                        {"period": period_id},
                    )
                ).one()
                assert tuple(totals) == (1, 39)

                actor_id = uuid.uuid4()
                adjustment = await adjust_units(
                    session,
                    tenant_id=tenant,
                    user_id=users[0],
                    period_id=period_id,
                    delta=-1,
                    idempotency_key="operator-correction-1",
                    actor_id=actor_id,
                    reason="Correct duplicate unit debit",
                )
                assert adjustment.consumed_delta == -1
                assert adjustment.actor_id == actor_id
                assert adjustment.reason == "Correct duplicate unit debit"
                replay = await adjust_units(
                    session,
                    tenant_id=tenant,
                    user_id=users[0],
                    period_id=period_id,
                    delta=-1,
                    idempotency_key="operator-correction-1",
                    actor_id=actor_id,
                    reason="Correct duplicate unit debit",
                )
                assert replay.id == adjustment.id
                with pytest.raises(BillingAdjustmentConflict):
                    await adjust_units(
                        session,
                        tenant_id=tenant,
                        user_id=users[0],
                        period_id=period_id,
                        delta=-1,
                        idempotency_key="operator-correction-1",
                        actor_id=actor_id,
                        reason="Changed audit reason",
                    )
                with pytest.raises(BillingAdjustmentUnavailable):
                    await adjust_units(
                        session,
                        tenant_id=tenant,
                        user_id=users[0],
                        period_id=period_id,
                        delta=2,
                        idempotency_key="operator-correction-over-limit",
                        actor_id=actor_id,
                        reason="Would exceed allowance",
                    )

            async with session_factory() as session, session.begin():
                await set_identity(session, users[1])
                free_period = await ensure_default_free_period(
                    session, tenant_id=tenant, user_id=users[1], now=now
                )
                await transition_period_state(
                    session,
                    tenant_id=tenant,
                    user_id=users[1],
                    period=free_period,
                    next_state="suspended",
                    effective_at=now,
                )
                new_grant = await ensure_period_grant(
                    session,
                    tenant_id=tenant,
                    user_id=users[1],
                    plan_key="scholar",
                    catalog_version="test-catalog",
                    starts_at=starts_at,
                    ends_at=ends_at,
                    approved_catalogs=approved_catalogs,
                )
                assert new_grant.allowance_units == 40

            return accepted_run

        accepted_run = await verify_and_run()

        with sync_app.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant)},
            )
            connection.execute(
                text("SELECT set_config('app.user_id', :user, true)"),
                {"user": str(users[0])},
            )
            assert connection.scalar(text("SELECT count(*) FROM billing_accounts")) == 1
            assert connection.scalar(
                text("""
                SELECT has_table_privilege(current_user, 'billing_accounts', 'INSERT')
                   AND has_table_privilege(current_user, 'billing_periods', 'INSERT')
                   AND has_table_privilege(current_user, 'billing_unit_entries', 'INSERT')
                   AND NOT has_table_privilege(current_user, 'billing_accounts', 'UPDATE')
                   AND NOT has_table_privilege(current_user, 'billing_periods', 'UPDATE')
                   AND NOT has_table_privilege(current_user, 'billing_unit_entries', 'DELETE')
            """)
            )

        with owner.begin() as connection:
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError) as missing_audit_fields:
                connection.execute(
                    text("""
                        INSERT INTO billing_unit_entries
                            (id, tenant_id, billing_account_id, billing_period_id,
                             entry_type, consumed_delta, reserved_delta, idempotency_key)
                        VALUES (:id, :tenant, :account, :period, 'adjustment',
                                -1, 0, 'missing-audit-fields')
                    """),
                    {
                        "id": uuid.uuid4(),
                        "tenant": tenant,
                        "account": account_id,
                        "period": period_id,
                    },
                )
            assert missing_audit_fields.value.orig.sqlstate == "23514"
            savepoint.rollback()

            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError) as duplicate_reservation:
                connection.execute(
                    text("""
                        INSERT INTO billing_unit_entries
                            (id, tenant_id, billing_account_id, billing_period_id, run_id,
                             entry_type, consumed_delta, reserved_delta, idempotency_key)
                        VALUES (:id, :tenant, :account, :period, :run, 'reservation',
                                0, 1, 'database-duplicate')
                    """),
                    {
                        "id": uuid.uuid4(),
                        "tenant": tenant,
                        "account": account_id,
                        "period": period_id,
                        "run": accepted_run,
                    },
                )
            assert duplicate_reservation.value.orig.sqlstate == "23505"
            savepoint.rollback()
    finally:
        await async_engine.dispose()
        owner.dispose()
        sync_app.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}"')
        admin.dispose()
