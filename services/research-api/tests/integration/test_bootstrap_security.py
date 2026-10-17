"""Fresh committed revision targets in disposable loopback databases only.

Opt in with RUN_BOOTSTRAP_SCHEMA_TESTS=1. No shared database schema changes,
cluster role creation, provider requests or hosted credentials are used.
"""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from research_api.db.assessments import ResearchAssessment
from research_api.db.models import Base, Report, ResearchPlan, ResearchRun, Source, Tenant, User
from research_api.db.source_relationships import SourceIdentityRecord, SourceRelationship

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_BOOTSTRAP_SCHEMA_TESTS") != "1",
        reason="set RUN_BOOTSTRAP_SCHEMA_TESTS=1 for disposable local schema checks",
    ),
]
SERVICE_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("bootstrap_db", ["0018"], indirect=True)
def test_0019_upgrades_preexisting_mode_guards(bootstrap_db):
    """A database that already applied old 0013 gets the new guards at 0019."""
    _target, owner, runtime = bootstrap_db
    with owner.begin() as connection:
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION public.freeze_research_mode_snapshot()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
            DROP TRIGGER research_mode_snapshot_immutable ON public.research_runs;
            CREATE TRIGGER research_mode_snapshot_immutable
            BEFORE UPDATE OF mode, mode_policy_version ON public.research_runs
            FOR EACH ROW EXECUTE FUNCTION public.freeze_research_mode_snapshot();
            CREATE OR REPLACE FUNCTION public.freeze_explicit_research_budget()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END $$;
            DROP TRIGGER explicit_research_budget_immutable ON public.budgets;
            CREATE TRIGGER explicit_research_budget_immutable BEFORE UPDATE ON public.budgets
            FOR EACH ROW EXECUTE FUNCTION public.freeze_explicit_research_budget();
        """)
    environment = os.environ.copy()
    environment.update(
        APP_ENV="test",
        DATABASE_ADMIN_URL=owner.url.render_as_string(hide_password=False),
        DATABASE_URL=runtime.url.render_as_string(hide_password=False),
    )
    subprocess.run(  # noqa: S603 -- fixed local fixture URLs and migration target
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(SERVICE_ROOT / "alembic.ini"),
            "upgrade",
            "0019",
        ],
        cwd=SERVICE_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    with owner.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0019"
        run_trigger = connection.scalar(
            text("""
            SELECT pg_get_triggerdef(oid) FROM pg_trigger
            WHERE tgrelid = 'public.research_runs'::regclass
              AND tgname = 'research_mode_snapshot_immutable'
        """)
        )
        budget_trigger = connection.scalar(
            text("""
            SELECT pg_get_triggerdef(oid) FROM pg_trigger
            WHERE tgrelid = 'public.budgets'::regclass
              AND tgname = 'explicit_research_budget_immutable'
        """)
        )
        run_guard = connection.scalar(
            text(
                "SELECT pg_get_functiondef('public.freeze_research_mode_snapshot()'::regprocedure)"
            )
        )
        budget_guard = connection.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'public.freeze_explicit_research_budget()'::regprocedure)"
            )
        )
    assert "original_question" in run_trigger
    assert "report_requirements" in run_trigger
    assert "explicit research brief snapshot is immutable" in run_guard
    assert "DELETE" in budget_trigger
    assert "research budget ownership is immutable" in budget_guard
    fixtures = seed(owner, "0019")
    run_id = fixtures[0]["run"]
    with owner.connect() as connection:
        denied(
            connection,
            "UPDATE research_runs SET original_question='rewritten' WHERE id=:run_id",
            {"run_id": run_id},
            "23514",
        )


@pytest.fixture
def bootstrap_db(request):
    target = request.param
    assert target in {"0001", "0014", "0015", "0016", "0017", "0018", "0019"}
    admin_url = make_url(os.environ["TEST_DATABASE_ADMIN_URL"])
    runtime_url = make_url(os.environ["DATABASE_URL"])
    assert admin_url.host in {"localhost", "127.0.0.1", "::1"}
    assert runtime_url.host == admin_url.host and runtime_url.port == admin_url.port
    assert runtime_url.username == "research_app"
    name = "research_bootstrap_test_" + uuid.uuid4().hex[:12]
    # psycopg identifier quoting ensures cleanup can target only this generated DB.
    connect = dict(
        host=admin_url.host,
        port=admin_url.port,
        user=admin_url.username,
        password=admin_url.password,
        dbname=admin_url.database,
    )
    with psycopg.connect(**connect, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    owner = create_engine(admin_url.set(database=name))
    runtime = create_engine(runtime_url.set(database=name))
    try:
        with owner.begin() as connection:
            # A table outside Base metadata must never inherit bootstrap grants.
            connection.exec_driver_sql(
                "CREATE TABLE public.future_private_fixture (id bigserial, secret text)"
            )
            connection.exec_driver_sql(
                "INSERT INTO public.future_private_fixture (secret) VALUES ('private')"
            )
        environment = os.environ.copy()
        environment.update(
            APP_ENV="test",
            DATABASE_ADMIN_URL=admin_url.set(database=name).render_as_string(hide_password=False),
            DATABASE_URL=runtime_url.set(database=name).render_as_string(hide_password=False),
        )
        subprocess.run(  # noqa: S603 -- fixed module, validated target and local fixture URLs
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(SERVICE_ROOT / "alembic.ini"),
                "upgrade",
                target,
            ],
            cwd=SERVICE_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        yield target, owner, runtime
    finally:
        runtime.dispose()
        owner.dispose()
        with psycopg.connect(**connect, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def seed(owner, target):
    fixtures = []
    with Session(owner) as session, session.begin():
        for _ in range(2):
            tenant, user, run, plan = (uuid.uuid4() for _ in range(4))
            source_ids = sorted([uuid.uuid4(), uuid.uuid4()])
            session.add(Tenant(id=tenant, name="Bootstrap private fixture"))
            session.flush()
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
            session.flush()
            session.add(
                ResearchRun(
                    id=run,
                    tenant_id=tenant,
                    user_id=user,
                    original_question="Private fixture",
                    normalized_question="Fixture",
                    thread_id=str(run),
                    mode="focused" if target == "0019" else None,
                    mode_policy_version=("research-mode-policy-v1" if target == "0019" else None),
                    report_requirements=[] if target == "0019" else None,
                )
            )
            session.flush()
            session.add(
                ResearchPlan(id=plan, tenant_id=tenant, run_id=run, plan_version=1, plan={})
            )
            for id_ in source_ids:
                session.add(
                    Source(
                        id=id_,
                        tenant_id=tenant,
                        run_id=run,
                        canonical_url=f"https://example.test/{id_}",
                        title="Private source",
                        provider="tavily",
                        source_class="unknown",
                        retrieved_at=datetime.now(UTC),
                        content_hash="a" * 64,
                        artifact_ref="fixture/private",
                    )
                )
            session.flush()
            assessment = uuid.uuid4()
            if target != "0001":
                session.add(
                    SourceIdentityRecord(
                        tenant_id=tenant,
                        run_id=run,
                        source_id=source_ids[0],
                        work_id=None,
                        publisher=None,
                        metadata_basis={"fixture": "private"},
                    )
                )
                session.add(
                    SourceRelationship(
                        tenant_id=tenant,
                        run_id=run,
                        from_source_id=source_ids[0],
                        to_source_id=source_ids[1],
                        kind="same_content",
                        confidence="observed",
                        basis={"fixture": "private"},
                    )
                )
            if target in {"0015", "0016", "0017", "0018", "0019"}:
                row = ResearchAssessment(
                    id=assessment,
                    tenant_id=tenant,
                    run_id=run,
                    plan_id=plan,
                    evidence_key="fixture",
                    manifest={"selected_context": "private"},
                )
                session.add(row)
                session.flush()
                row.result = {"accepted": True}
            report_id = uuid.uuid4()
            if target in {"0016", "0017", "0018", "0019"}:
                session.add(
                    Report(
                        id=report_id,
                        tenant_id=tenant,
                        run_id=run,
                        version=1,
                        markdown=f"Immutable V{3 if target == '0016' else 4} fixture",
                        document={"version": 3 if target == "0016" else 4},
                        retrieval_accounting=(
                            {"schemaVersion": "1.1", "extractedSources": 0}
                            if target in {"0018", "0019"}
                            else None
                        ),
                        published=True,
                        published_at=datetime.now(UTC),
                        content_hash="a" * 64,
                    )
                )
            fixtures.append(
                dict(
                    tenant=tenant,
                    run=run,
                    plan=plan,
                    source=source_ids[0],
                    other_source=source_ids[1],
                    assessment=assessment,
                    report=report_id,
                )
            )
    return fixtures


def denied(connection, statement, parameters, state):
    with pytest.raises(DBAPIError) as error:
        with connection.begin_nested():
            connection.execute(text(statement), parameters)
    assert error.value.orig.sqlstate == state


@pytest.mark.parametrize(
    "bootstrap_db", ["0001", "0014", "0015", "0016", "0017", "0018", "0019"], indirect=True
)
def test_fresh_targets_deny_cross_tenant_access_and_unfrozen_assessment_writes(bootstrap_db):
    target, owner, runtime = bootstrap_db
    first, second = seed(owner, target)
    expected_late = {"source_identities", "source_relationships"} if target != "0001" else set()
    if target in {"0015", "0016", "0017", "0018", "0019"}:
        expected_late.add("research_assessments")
    with owner.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == target
        for table in ("research_assessments", "source_identities", "source_relationships"):
            exists = connection.scalar(
                text("SELECT to_regclass(:table) IS NOT NULL"), {"table": "public." + table}
            )
            assert exists == (table in expected_late)
        for table in {"research_runs", "sources", *expected_late}:
            flags = connection.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid=to_regclass(:table)"
                ),
                {"table": "public." + table},
            ).one()
            assert tuple(flags) == (True, True)
    with runtime.begin() as connection:
        assert connection.scalar(text("SELECT current_user")) == "research_app"
        assert connection.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one() == (False, False)
        denied(connection, "SELECT * FROM public.future_private_fixture", {}, "42501")
        denied(connection, "SELECT nextval('public.future_private_fixture_id_seq')", {}, "42501")
        for context in ("", str(uuid.uuid4())):
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": context}
            )
            for table in {"research_runs", "sources", *expected_late}:
                assert (
                    connection.scalar(select(func.count()).select_from(Base.metadata.tables[table]))
                    == 0
                )
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(first["tenant"])},
        )
        assert connection.scalar(text("SELECT count(*) FROM research_runs")) == 1
        assert connection.scalar(text("SELECT count(*) FROM sources")) == 2
        assert (
            connection.execute(
                text("UPDATE sources SET title='tamper' WHERE id=:id"), {"id": second["source"]}
            ).rowcount
            == 0
        )
        denied(
            connection,
            "UPDATE sources SET tenant_id=:other WHERE id=:id",
            {"other": second["tenant"], "id": first["source"]},
            "42501",
        )
        for table in expected_late:
            assert (
                connection.scalar(select(func.count()).select_from(Base.metadata.tables[table]))
                == 1
            )
        if target != "0001":
            denied(
                connection,
                "INSERT INTO source_identities "
                "(tenant_id,run_id,source_id,metadata_basis) "
                "VALUES (:tenant,:run,:source,'{}'::jsonb)",
                second,
                "42501",
            )
            denied(
                connection,
                "INSERT INTO source_relationships "
                "(tenant_id,run_id,from_source_id,to_source_id,kind,basis,confidence) "
                "VALUES (:tenant,:run,:source,:other_source,'same_work',"
                "jsonb_build_object('fixture',true),'observed')",
                second,
                "42501",
            )
        if target not in {"0015", "0016", "0017", "0018", "0019"}:
            denied(connection, "SELECT * FROM research_assessments", {}, "42P01")
            denied(
                connection,
                "INSERT INTO research_assessments(id) VALUES (:id)",
                {"id": uuid.uuid4()},
                "42P01",
            )
        else:
            params = {**first, "id": uuid.uuid4()}
            denied(
                connection,
                "INSERT INTO research_assessments "
                "(id,tenant_id,run_id,plan_id,evidence_key,manifest,result) "
                "VALUES (:id,:tenant,:run,:plan,'bad','{}'::jsonb,'{}'::jsonb)",
                params,
                "23514",
            )
            denied(
                connection,
                "UPDATE research_assessments SET manifest='{}'::jsonb WHERE id=:id",
                {"id": first["assessment"]},
                "23514",
            )
            denied(
                connection,
                "UPDATE research_assessments SET result='{}'::jsonb WHERE id=:id",
                {"id": first["assessment"]},
                "23514",
            )
            assert (
                connection.execute(
                    text("UPDATE research_assessments SET result=NULL WHERE id=:id"),
                    {"id": second["assessment"]},
                ).rowcount
                == 0
            )
        if target in {"0016", "0017", "0018", "0019"}:
            assert connection.scalar(
                text("SELECT document->>'version' FROM reports WHERE id=:id"),
                {"id": first["report"]},
            ) == ("3" if target == "0016" else "4")
            denied(
                connection,
                "UPDATE reports SET markdown='tampered' WHERE id=:id",
                {"id": first["report"]},
                "55000",
            )
            if target in {"0018", "0019"}:
                assert (
                    connection.scalar(
                        text(
                            "SELECT retrieval_accounting->>'schemaVersion' "
                            "FROM reports WHERE id=:id"
                        ),
                        {"id": first["report"]},
                    )
                    == "1.1"
                )
                denied(
                    connection,
                    "UPDATE reports SET retrieval_accounting='{}'::jsonb WHERE id=:id",
                    {"id": first["report"]},
                    "55000",
                )
