import importlib.util
from pathlib import Path
from unittest.mock import patch

from research_api.db.models import BillingShadowObservation


def test_migration_adds_private_tenant_scoped_append_only_table():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0021_billing_shadow_observations.py"
    )
    spec = importlib.util.spec_from_file_location("billing_shadow_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0021" and migration.down_revision == "0020"

    statements: list[str] = []
    with (
        patch.object(migration, "op") as operation,
        patch.object(BillingShadowObservation.__table__, "create") as create_table,
    ):
        operation.execute.side_effect = lambda statement: statements.append(statement)
        migration.upgrade()
        create_table.assert_called_once_with(operation.get_bind(), checkfirst=True)

    sql = " ".join(" ".join(statement.split()) for statement in statements)
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "current_setting('app.tenant_id', true)" in sql
    assert "REVOKE ALL ON public.billing_shadow_observations FROM PUBLIC" in sql
    assert "GRANT SELECT, INSERT ON TABLE public.billing_shadow_observations TO %I" in sql


def test_migration_downgrade_retains_shadow_audit_records():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0021_billing_shadow_observations.py"
    )
    spec = importlib.util.spec_from_file_location(
        "billing_shadow_migration_downgrade", migration_path
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "Retain append-only" in str(error)
    else:
        raise AssertionError("downgrade must not drop shadow evidence")
