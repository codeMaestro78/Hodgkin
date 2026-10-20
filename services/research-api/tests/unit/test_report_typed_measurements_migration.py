import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_migration():
    path = (
        Path(__file__).parents[2]
        / "src/research_api/db/migrations/versions/0031_report_typed_measurements.py"
    )
    spec = importlib.util.spec_from_file_location("report_typed_measurements_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_extends_immutable_report_allowlist_for_v6():
    migration = _load_migration()
    assert migration.revision == "0031"
    assert migration.down_revision == "0030"

    with patch.object(migration, "op") as operation:
        migration.upgrade()

    statements = "\n".join(call.args[0] for call in operation.execute.call_args_list)
    assert "ck_report_document_v1" in statements
    assert "'5', '6'" in statements
    assert "524288" in statements
    assert "SET LOCAL search_path TO public" in statements


def test_migration_refuses_to_drop_published_v6_reports():
    with pytest.raises(RuntimeError, match="Preserve published V6"):
        _load_migration().downgrade()
