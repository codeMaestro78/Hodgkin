import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0024_billing_audited_adjustments.py"
    )
    spec = importlib.util.spec_from_file_location("billing_adjustment_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_adjustment_migration_adds_audit_data_without_expanding_privileges():
    migration = _load_migration()
    assert migration.revision == "0024" and migration.down_revision == "0023"
    statements: list[str] = []
    with patch.object(migration, "op") as operation:
        operation.execute.side_effect = lambda statement: statements.append(statement)
        migration.upgrade()

    sql = " ".join(" ".join(statement.split()) for statement in statements)
    assert "ADD COLUMN IF NOT EXISTS actor_id uuid" in sql
    assert "ADD COLUMN IF NOT EXISTS reason varchar(500)" in sql
    assert "ck_billing_adjustment_audit" in sql
    assert "UPDATE" not in sql
    assert "GRANT" not in sql


def test_adjustment_migration_downgrade_preserves_audit_history():
    migration = _load_migration()
    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "Retain immutable adjustment actor and reason history" in str(error)
    else:
        raise AssertionError("downgrade must retain audit history")
