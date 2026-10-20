import importlib.util
from pathlib import Path

from sqlalchemy import Table


def _load_migration():
    path = (
        Path(__file__).parents[2]
        / "src/research_api/db/migrations/versions/0030_billing_credit_wallet.py"
    )
    spec = importlib.util.spec_from_file_location("billing_credit_wallet_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_credit_wallet_migration_creates_owner_scoped_append_only_ledger(monkeypatch):
    migration = _load_migration()
    statements: list[str] = []
    created: list[str] = []

    class Bind:
        def execute(self, statement):
            statements.append(str(statement))

    class Operations:
        def execute(self, statement):
            statements.append(str(statement))

        def get_bind(self):
            return Bind()

    monkeypatch.setattr(Table, "create", lambda table, bind, checkfirst: created.append(table.name))
    monkeypatch.setattr(migration, "op", Operations())

    migration.upgrade()
    sql = "\n".join(statements)

    assert migration.revision == "0030"
    assert migration.down_revision == "0029"
    assert created == ["billing_credit_purchases", "billing_credit_entries"]
    assert sql.count("ENABLE ROW LEVEL SECURITY") == 2
    assert sql.count("FORCE ROW LEVEL SECURITY") == 2
    assert "billing credit ledger is append-only" in sql
    assert "billing credit purchase terms are immutable" in sql
    assert "credit purchase must begin in pending state" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE ON public.billing_credit_purchases" in sql
    assert "current_setting('app.billing_system', true) = 'on'" in sql
    assert "billing system context required for credit grants and reversals" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE ON public.billing_credit_entries" in sql
    assert "REVOKE ALL ON public.billing_credit_purchases FROM PUBLIC" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE '" in sql
    assert "GRANT SELECT, INSERT ON TABLE '" in sql
    assert "GRANT UPDATE ON TABLE 'public.billing_credit_entries" not in sql
    assert "GRANT DELETE" not in sql


def test_credit_wallet_migration_cannot_delete_financial_history():
    migration = _load_migration()
    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "Preserve purchased-credit purchase and ledger history" in str(error)
    else:
        raise AssertionError("downgrade must preserve purchased-credit history")
