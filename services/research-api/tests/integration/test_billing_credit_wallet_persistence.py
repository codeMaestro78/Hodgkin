"""Apply all current migrations in an isolated, generated loopback database.

Opt in with RUN_BILLING_CREDIT_DB_TESTS=1. The test creates and drops only its
uniquely named disposable database; it never migrates the configured database.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api.billing import credits
from research_api.billing.catalog import BILLING_CATALOG
from research_api.billing.ledger import (
    BillingReservationConflict,
    BillingUnitsExhausted,
    reserve_units,
)
from research_api.billing.lifecycle import settle_terminal_run
from research_api.db.models import ResearchRun

apply_credit_checkout = getattr(credits, "apply_credit_checkout", None)
apply_credit_reversal = getattr(credits, "apply_credit_reversal", None)
credit_balance = credits.credit_balance
wallet_frozen = credits.wallet_frozen

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_BILLING_CREDIT_DB_TESTS") != "1"
        or not callable(apply_credit_checkout)
        or not callable(apply_credit_reversal),
        reason=(
            "optional legacy credit refund/dispute integration suite requires the old helpers "
            "and disposable PostgreSQL"
        ),
    ),
]
SERVICE_ROOT = Path(__file__).resolve().parents[2]


def test_all_migrations_through_0033_and_credit_guards_on_disposable_postgres():
    admin_url = make_url(os.environ["TEST_DATABASE_ADMIN_URL"])
    app_url = make_url(os.environ["DATABASE_URL"])
    assert admin_url.host in {"localhost", "127.0.0.1", "::1"}
    assert (admin_url.host, admin_url.port) == (app_url.host, app_url.port)
    assert app_url.username == "research_app"

    database = "billing_credit_test_" + uuid.uuid4().hex
    admin_connect = {
        "host": admin_url.host,
        "port": admin_url.port,
        "user": admin_url.username,
        "password": admin_url.password,
        "dbname": admin_url.database,
    }
    with psycopg.connect(**admin_connect, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {} ").format(sql.Identifier(database)))

    owner = create_engine(admin_url.set(database=database))
    try:
        environment = os.environ.copy()
        environment.update(
            APP_ENV="test",
            DATABASE_ADMIN_URL=admin_url.set(database=database).render_as_string(
                hide_password=False
            ),
            DATABASE_URL=app_url.set(database=database).render_as_string(hide_password=False),
        )
        migration = subprocess.run(  # noqa: S603 - DB is a generated disposable name
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(SERVICE_ROOT / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=SERVICE_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert migration.returncode == 0, migration.stderr

        with owner.begin() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0033"
            history_columns = {
                row[0]
                for row in connection.execute(
                    text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'research_runs'
                          AND column_name IN ('pinned_at', 'deleted_at')
                    """)
                )
            }
            assert history_columns == {"pinned_at", "deleted_at"}
            assert connection.scalar(
                text("""
                    SELECT to_regclass('public.ix_research_runs_owner_pinned_created')
                    IS NOT NULL
                """)
            )
            razorpay_columns = {
                row[0]
                for row in connection.execute(
                    text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema='public'
                          AND table_name='billing_credit_purchases'
                          AND column_name IN (
                              'payment_provider', 'provider_order_state',
                              'provider_order_id', 'provider_payment_id'
                          )
                    """)
                )
            }
            assert razorpay_columns == {
                "payment_provider",
                "provider_order_state",
                "provider_order_id",
                "provider_payment_id",
            }
            assert connection.scalar(
                text("SELECT to_regclass('public.razorpay_webhook_events') IS NOT NULL")
            )
            for table in ("billing_credit_purchases", "billing_credit_entries"):
                assert connection.execute(
                    text("""
                        SELECT relrowsecurity, relforcerowsecurity
                        FROM pg_class WHERE oid = to_regclass(:table_name)
                    """),
                    {"table_name": f"public.{table}"},
                ).one() == (True, True)
            trigger_count = connection.scalar(
                text("""
                SELECT count(*) FROM pg_trigger
                WHERE tgrelid IN (
                    'public.billing_credit_purchases'::regclass,
                    'public.billing_credit_entries'::regclass
                ) AND NOT tgisinternal
            """)
            )
            assert trigger_count == 3
            assert connection.scalar(
                text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgrelid='public.billing_credit_purchases'::regclass
                          AND tgname='razorpay_credit_purchase_immutable'
                          AND NOT tgisinternal
                    )
                """)
            )
            assert connection.scalar(
                text("""
                SELECT has_table_privilege(
                    'research_app', 'public.billing_credit_entries', 'INSERT'
                )
            """)
            )
            assert not connection.scalar(
                text("""
                SELECT has_table_privilege(
                    'research_app', 'public.billing_credit_entries', 'UPDATE'
                )
            """)
            )

            tenant = uuid.uuid4()
            user = uuid.uuid4()
            account = uuid.uuid4()
            purchase = uuid.uuid4()
            connection.execute(
                text("INSERT INTO public.tenants (id, name) VALUES (:id, 'credit migration test')"),
                {"id": tenant},
            )
            connection.execute(
                text(
                    "INSERT INTO public.users (id, tenant_id, external_subject) "
                    "VALUES (:id, :tenant, :subject)"
                ),
                {"id": user, "tenant": tenant, "subject": str(user)},
            )
            connection.execute(
                text(
                    "INSERT INTO public.billing_accounts "
                    "(id, tenant_id, user_id, account_type) "
                    "VALUES (:id, :tenant, :user, 'personal')"
                ),
                {"id": account, "tenant": tenant, "user": user},
            )
            connection.execute(
                text("""
                INSERT INTO public.billing_credit_purchases
                    (id, tenant_id, billing_account_id, user_id, package_key, stripe_price_id,
                     request_key_hash, stripe_idempotency_key, terms_version,
                     amount_minor, currency, unit_grant, state)
                VALUES (:id, :tenant, :account, :user, 'test-pack', 'price_test_pack',
                        repeat('a', 64), 'credit-idempotency-test', 'terms-test-v1',
                        500, 'USD', 10, 'pending')
            """),
                {"id": purchase, "tenant": tenant, "account": account, "user": user},
            )
            connection.execute(
                text("""
                    UPDATE public.billing_credit_purchases
                    SET stripe_checkout_session_id = 'cs_test_original'
                    WHERE id = :id
                """),
                {"id": purchase},
            )

            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("""
                    UPDATE public.billing_credit_purchases
                    SET stripe_checkout_session_id = 'cs_test_replacement'
                    WHERE id = :id
                """),
                    {"id": purchase},
                )
            savepoint.rollback()
            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("UPDATE public.billing_credit_purchases SET state='paid' WHERE id=:id"),
                    {"id": purchase},
                )
            savepoint.rollback()

            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("""
                    UPDATE public.billing_credit_purchases
                    SET terms_version = 'silently-changed'
                    WHERE id = :id
                """),
                    {"id": purchase},
                )
            savepoint.rollback()

            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("""
                    INSERT INTO public.billing_credit_purchases
                        (id, tenant_id, billing_account_id, user_id, package_key,
                         stripe_price_id,
                         request_key_hash, stripe_idempotency_key, terms_version,
                         amount_minor, currency, unit_grant, state)
                    VALUES (:id, :tenant, :account, :user, 'other-pack', 'price_other_pack',
                            repeat('a', 64), 'another-stripe-key', 'terms-test-v1',
                            700, 'USD', 14, 'pending')
                """),
                    {"id": uuid.uuid4(), "tenant": tenant, "account": account, "user": user},
                )
            savepoint.rollback()

            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("""
                    INSERT INTO public.billing_credit_entries
                        (id, tenant_id, billing_account_id, purchase_id, entry_type,
                         available_delta, reserved_delta, idempotency_key)
                    VALUES (:id, :tenant, :account, :purchase, 'grant', 10, 0, 'test-grant')
                """),
                    {
                        "id": uuid.uuid4(),
                        "tenant": tenant,
                        "account": account,
                        "purchase": purchase,
                    },
                )
            savepoint.rollback()
        run_id = uuid.uuid4()
        concurrent_run_ids = [uuid.uuid4() for _ in range(21)]
        second_purchase = uuid.uuid4()
        unspent_purchase = uuid.uuid4()
        period_id = uuid.uuid4()
        now = datetime.now(UTC)
        with owner.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO public.stripe_customer_links
                        (stripe_customer_id, tenant_id, user_id)
                    VALUES ('cus_credit_test', :tenant, :user)
                """),
                {"tenant": tenant, "user": user},
            )
            connection.execute(
                text("""
                    INSERT INTO public.billing_periods
                        (id, tenant_id, billing_account_id, plan_key, catalog_version,
                         state, allowance_units, starts_at, ends_at)
                    VALUES (:id, :tenant, :account, 'free', :version, 'active', 5,
                            :start, :end)
                """),
                {
                    "id": period_id,
                    "tenant": tenant,
                    "account": account,
                    "version": BILLING_CATALOG.version,
                    "start": now - timedelta(days=1),
                    "end": now + timedelta(days=20),
                },
            )
            connection.execute(
                text("""
                    INSERT INTO public.billing_unit_entries
                        (id, tenant_id, billing_account_id, billing_period_id,
                         entry_type, consumed_delta, reserved_delta,
                         idempotency_key, actor_id, reason)
                    VALUES (:id, :tenant, :account, :period,
                            'adjustment', 6, 0, 'exhaust-monthly', :user, 'test setup')
                """),
                {
                    "id": uuid.uuid4(),
                    "tenant": tenant,
                    "account": account,
                    "period": period_id,
                    "user": user,
                },
            )
            connection.execute(
                text("""
                    INSERT INTO public.billing_credit_purchases
                        (id, tenant_id, billing_account_id, user_id, package_key,
                         stripe_price_id, request_key_hash, stripe_idempotency_key,
                         terms_version, amount_minor, currency, unit_grant, state,
                         stripe_checkout_session_id)
                    VALUES (:id, :tenant, :account, :user, 'test-pack',
                            'price_test_pack', repeat('b', 64), 'credit-test-second',
                            'terms-test-v1', 500, 'USD', 10, 'pending', 'cs_test_second')
                """),
                {"id": second_purchase, "tenant": tenant, "account": account, "user": user},
            )
            connection.execute(
                text("""
                    INSERT INTO public.billing_credit_purchases
                        (id, tenant_id, billing_account_id, user_id, package_key,
                         stripe_price_id, request_key_hash, stripe_idempotency_key,
                         terms_version, amount_minor, currency, unit_grant, state,
                         stripe_checkout_session_id)
                    VALUES (:id, :tenant, :account, :user, 'test-pack',
                            'price_test_pack', repeat('c', 64), 'credit-test-unspent',
                            'terms-test-v1', 500, 'USD', 10, 'pending', 'cs_test_unspent')
                """),
                {"id": unspent_purchase, "tenant": tenant, "account": account, "user": user},
            )
            run_insert = text("""
                    INSERT INTO public.research_runs
                        (id, tenant_id, user_id, status, original_question,
                         normalized_question, mode, mode_policy_version, thread_id,
                         report_requirements, model_routing, plan_version,
                         concurrency_limit, next_event_sequence, approval_required)
                    VALUES (:id, :tenant, :user, 'queued', 'test question',
                            'test question', 'focused', 'test-policy', :thread,
                            '[]'::jsonb, '{}'::jsonb, 0, 3, 0, false)
                """)
            for candidate in [run_id, *concurrent_run_ids]:
                connection.execute(
                    run_insert,
                    {"id": candidate, "tenant": tenant, "user": user, "thread": str(candidate)},
                )

        async def exercise_credit_lifecycle():
            async_url = app_url.set(database=database)
            engine = create_async_engine(async_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async def install_context(session, *, billing_system=False):
                if billing_system:
                    await session.execute(
                        text("SELECT set_config('app.billing_system', 'on', true)")
                    )
                    return
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :value, true)"),
                    {"value": str(tenant)},
                )
                await session.execute(
                    text("SELECT set_config('app.user_id', :value, true)"),
                    {"value": str(user)},
                )

            event = {
                "id": "cs_test_original",
                "mode": "payment",
                "livemode": False,
                "client_reference_id": str(purchase),
                "customer": "cus_credit_test",
                "amount_total": 500,
                "currency": "usd",
                "payment_status": "paid",
                "payment_intent": "pi_credit_test",
                "metadata": {
                    "purchase_id": str(purchase),
                    "tenant_id": str(tenant),
                    "user_id": str(user),
                },
            }
            try:
                async with sessions.begin() as session:
                    await install_context(session, billing_system=True)
                    assert (
                        await apply_credit_checkout(
                            session,
                            event_type="checkout.session.completed",
                            obj={**event, "amount_total": 501},
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "reconciliation_required"
                    )
                    assert (
                        await apply_credit_checkout(
                            session,
                            event_type="checkout.session.completed",
                            obj={**event, "payment_status": "unpaid"},
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert await credit_balance(session, tenant_id=tenant, account_id=account) == (
                        0,
                        0,
                    )
                    assert (
                        await apply_credit_checkout(
                            session,
                            event_type="checkout.session.async_payment_succeeded",
                            obj=event,
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert (
                        await apply_credit_checkout(
                            session,
                            event_type="checkout.session.completed",
                            obj=event,
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert await credit_balance(session, tenant_id=tenant, account_id=account) == (
                        10,
                        0,
                    )
                async with sessions.begin() as session:
                    await install_context(session)
                    reservation = await reserve_units(
                        session,
                        tenant_id=tenant,
                        user_id=user,
                        run_id=run_id,
                        mode="focused",
                        idempotency_key="credit-run-test",
                        allow_wallet=True,
                    )
                    assert reservation.entry_type == "reservation"
                    replay = await reserve_units(
                        session,
                        tenant_id=tenant,
                        user_id=user,
                        run_id=run_id,
                        mode="focused",
                        idempotency_key="credit-run-test",
                        allow_wallet=False,
                    )
                    assert replay.id == reservation.id
                    with pytest.raises(BillingReservationConflict):
                        await reserve_units(
                            session,
                            tenant_id=tenant,
                            user_id=user,
                            run_id=run_id,
                            mode="focused",
                            idempotency_key="different-credit-run-request",
                            allow_wallet=False,
                        )
                    assert await credit_balance(session, tenant_id=tenant, account_id=account) == (
                        9,
                        1,
                    )
                    run = await session.get(ResearchRun, run_id)
                    assert run is not None
                    run.status = "failed"
                    await session.flush()
                    assert await settle_terminal_run(session, run)
                    assert await settle_terminal_run(session, run)
                    assert await credit_balance(session, tenant_id=tenant, account_id=account) == (
                        10,
                        0,
                    )
                refund = {
                    "payment_intent": "pi_credit_test",
                    "amount": 500,
                    "currency": "usd",
                }
                async with sessions.begin() as session:
                    await install_context(session, billing_system=True)
                    assert (
                        await apply_credit_reversal(
                            session,
                            event_type="charge.dispute.created",
                            obj=refund,
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert await wallet_frozen(session, tenant_id=tenant, account_id=account)
                    assert (
                        await apply_credit_reversal(
                            session,
                            event_type="charge.dispute.closed",
                            obj={**refund, "status": "won"},
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert not await wallet_frozen(session, tenant_id=tenant, account_id=account)

                async with sessions.begin() as session:
                    await install_context(session, billing_system=True)
                    second_event = {
                        **event,
                        "id": "cs_test_second",
                        "client_reference_id": str(second_purchase),
                        "payment_intent": "pi_credit_second",
                        "metadata": {**event["metadata"], "purchase_id": str(second_purchase)},
                    }
                    assert (
                        await apply_credit_checkout(
                            session,
                            event_type="checkout.session.completed",
                            obj=second_event,
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )

                async def attempt_spend(candidate):
                    try:
                        async with sessions.begin() as session:
                            await install_context(session)
                            await reserve_units(
                                session,
                                tenant_id=tenant,
                                user_id=user,
                                run_id=candidate,
                                mode="focused",
                                idempotency_key=f"concurrent-{candidate}",
                                allow_wallet=True,
                            )
                        return "reserved"
                    except BillingUnitsExhausted:
                        return "exhausted"

                results = await asyncio.gather(
                    *(attempt_spend(candidate) for candidate in concurrent_run_ids)
                )
                assert results.count("reserved") == 20
                assert results.count("exhausted") == 1
                async with sessions.begin() as session:
                    await install_context(session)
                    assert await credit_balance(session, tenant_id=tenant, account_id=account) == (
                        0,
                        20,
                    )
                async with sessions.begin() as session:
                    await install_context(session, billing_system=True)
                    unspent_event = {
                        **event,
                        "id": "cs_test_unspent",
                        "client_reference_id": str(unspent_purchase),
                        "payment_intent": "pi_credit_unspent",
                        "metadata": {**event["metadata"], "purchase_id": str(unspent_purchase)},
                    }
                    assert (
                        await apply_credit_checkout(
                            session,
                            event_type="checkout.session.completed",
                            obj=unspent_event,
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert (
                        await apply_credit_reversal(
                            session,
                            event_type="refund.created",
                            obj={
                                "payment_intent": "pi_credit_unspent",
                                "amount": 500,
                                "currency": "usd",
                            },
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert await credit_balance(session, tenant_id=tenant, account_id=account) == (
                        0,
                        20,
                    )
                    assert not await wallet_frozen(session, tenant_id=tenant, account_id=account)
                async with sessions.begin() as session:
                    await install_context(session, billing_system=True)
                    assert (
                        await apply_credit_reversal(
                            session,
                            event_type="refund.created",
                            obj=refund,
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert (
                        await apply_credit_reversal(
                            session,
                            event_type="refund.updated",
                            obj=refund,
                            livemode=False,
                            expected_livemode=False,
                        )
                        == "processed"
                    )
                    assert await credit_balance(session, tenant_id=tenant, account_id=account) == (
                        0,
                        20,
                    )
                    assert await wallet_frozen(session, tenant_id=tenant, account_id=account)
            finally:
                await engine.dispose()

        asyncio.run(exercise_credit_lifecycle())
    finally:
        owner.dispose()
        with psycopg.connect(**admin_connect, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} ").format(sql.Identifier(database)))
