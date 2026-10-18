import importlib.util
from pathlib import Path

from sqlalchemy import Table


def test_webhook_migration_creates_minimal_deduplication_inbox_and_grants_no_public_access(
    monkeypatch,
):
    path = (
        Path(__file__).parents[2]
        / "src/research_api/db/migrations/versions/0026_billing_enforcement_webhook.py"
    )
    spec = importlib.util.spec_from_file_location("billing_webhook_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    created_tables: list[str] = []

    def record_create(table, bind, checkfirst):
        created_tables.append(table.name)

    class Bind:
        def execute(self, statement):
            statements.append(str(statement))

    class Operations:
        def execute(self, statement):
            statements.append(str(statement))

        def get_bind(self):
            return Bind()

    migration.op = Operations()
    monkeypatch.setattr(Table, "create", record_create)
    migration.upgrade()
    sql = "\n".join(statements)

    assert migration.revision == "0026"
    assert migration.down_revision == "0025"
    assert created_tables == ["stripe_webhook_events"]
    assert "REVOKE ALL ON public.stripe_webhook_events FROM PUBLIC" in sql
    assert "GRANT SELECT, INSERT ON TABLE public.stripe_webhook_events" in sql
    assert "last_quota_blocked_at" in sql
