import importlib.util
from pathlib import Path

from sqlalchemy import Table


def test_0027_adds_minimal_stripe_ownership_projection_with_service_only_access(monkeypatch):
    path = (
        Path(__file__).parents[2]
        / "src/research_api/db/migrations/versions/0027_stripe_subscription_projection.py"
    )
    spec = importlib.util.spec_from_file_location("stripe_projection_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
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

    def record_create(table, bind, checkfirst):
        created.append(table.name)

    migration.op = Operations()
    monkeypatch.setattr(Table, "create", record_create)
    migration.upgrade()
    sql = "\n".join(statements)

    assert migration.revision == "0027"
    assert migration.down_revision == "0026"
    assert created == [
        "stripe_customer_links",
        "stripe_subscriptions",
        "stripe_checkout_attempts",
    ]
    assert "processing_status IN" in sql
    assert "reconciliation_required" in sql
    assert "ALTER COLUMN processing_status TYPE varchar(32)" in sql
    assert sql.count("ENABLE ROW LEVEL SECURITY") == 4
    assert sql.count("FORCE ROW LEVEL SECURITY") == 4
    assert "current_user = 'research_app'" in sql
    assert "REVOKE ALL ON public.stripe_customer_links FROM PUBLIC" in sql
    assert "stripe_checkout_attempts" in sql
