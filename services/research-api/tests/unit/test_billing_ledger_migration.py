import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0023_billing_ledger_write_guards.py"
    )
    spec = importlib.util.spec_from_file_location("billing_ledger_write_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_write_migration_only_adds_owner_scoped_insert_privilege():
    migration = _load_migration()
    assert migration.revision == "0023" and migration.down_revision == "0022"
    statements: list[str] = []
    with patch.object(migration, "op") as operation:
        operation.execute.side_effect = lambda statement: statements.append(statement)
        migration.upgrade()

    sql = " ".join(" ".join(statement.split()) for statement in statements)
    assert "REVOKE ALL ON public.billing_accounts FROM PUBLIC" in sql
    assert "GRANT SELECT, INSERT ON TABLE public.billing_accounts" in sql
    assert "billing_periods, public.billing_unit_entries TO %I" in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql
    assert "FORCE ROW LEVEL SECURITY" not in sql  # 0022 owns RLS policy setup.


def test_write_migration_cannot_be_downgraded_and_erase_ledger_guarantees():
    migration = _load_migration()
    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "Retain billing ledger idempotency guarantees" in str(error)
    else:
        raise AssertionError("downgrade must preserve billing ledger history")
