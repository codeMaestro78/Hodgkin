import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def test_migration_adds_nullable_bounded_snapshot_without_rewriting_reports():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0018_report_retrieval_snapshot.py"
    )
    spec = importlib.util.spec_from_file_location("report_snapshot_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0018" and module.down_revision == "0017"
    with patch.object(module, "op") as operation:
        module.upgrade()
    sql = "\n".join(call.args[0] for call in operation.execute.call_args_list)
    assert "ADD COLUMN IF NOT EXISTS retrieval_accounting jsonb" in sql
    assert "retrieval_accounting IS NULL" in sql
    assert "schemaVersion' = '1.1'" in sql
    assert "octet_length(retrieval_accounting::text) <= 65536" in sql
    assert "UPDATE reports" not in sql and "DROP TRIGGER" not in sql
    with pytest.raises(RuntimeError, match="publication-time report accounting"):
        module.downgrade()
