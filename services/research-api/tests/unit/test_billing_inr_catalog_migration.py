import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0035_inr_billing_catalog.py"
    )
    spec = importlib.util.spec_from_file_location("billing_inr_catalog_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_allows_new_inr_catalog_and_preserves_prior_versions():
    migration = _load_migration()
    assert migration.revision == "0035"
    assert migration.down_revision == "0034"
    statements: list[str] = []
    with patch.object(migration, "op") as operation:
        operation.execute.side_effect = lambda statement: statements.append(statement)
        migration.upgrade()

    sql = " ".join(" ".join(statement.split()) for statement in statements)
    assert "research-units-v1-2026-10-19" in sql
    assert "research-units-v2-2026-10-19" in sql
    assert "research-units-v3-2026-10-22" in sql


def test_migration_downgrade_preserves_catalog_history():
    migration = _load_migration()
    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "Retain INR catalog observations" in str(error)
    else:
        raise AssertionError("downgrade must not drop catalog history")
