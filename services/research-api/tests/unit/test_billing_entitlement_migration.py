import importlib.util
from pathlib import Path
from unittest.mock import patch

from research_api.db.models import BillingAccount, BillingPeriod, BillingUnitEntry


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0022_billing_entitlement_read_model.py"
    )
    spec = importlib.util.spec_from_file_location("billing_entitlement_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_creates_owner_scoped_read_only_billing_tables():
    migration = _load_migration()
    assert migration.revision == "0022" and migration.down_revision == "0021"
    statements: list[str] = []
    with (
        patch.object(migration, "op") as operation,
        patch.object(BillingAccount.__table__, "create") as create_account,
        patch.object(BillingPeriod.__table__, "create") as create_period,
        patch.object(BillingUnitEntry.__table__, "create") as create_entry,
    ):
        operation.execute.side_effect = lambda statement: statements.append(statement)
        migration.upgrade()
        for create_table in (create_account, create_period, create_entry):
            create_table.assert_called_once_with(operation.get_bind(), checkfirst=True)

    sql = " ".join(" ".join(statement.split()) for statement in statements)
    assert sql.count("ENABLE ROW LEVEL SECURITY") == 3
    assert sql.count("FORCE ROW LEVEL SECURITY") == 3
    assert "billing period grant snapshot is immutable" in sql
    assert "billing unit ledger is append-only" in sql
    assert sql.count("current_setting('app.tenant_id', true)") == 6
    assert sql.count("current_setting('app.user_id', true)") == 6
    assert "REVOKE ALL ON public.billing_accounts FROM PUBLIC" in sql
    assert "GRANT SELECT ON TABLE public.billing_accounts" in sql
    assert "GRANT SELECT, INSERT" not in sql


def test_migration_downgrade_preserves_billing_history():
    migration = _load_migration()
    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "Retain billing period and unit-ledger history" in str(error)
    else:
        raise AssertionError("downgrade must not drop billing history")
