import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def test_migration_accepts_v11_and_v12_without_rewriting_snapshots():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0020_retrieval_accounting_v12.py"
    )
    spec = importlib.util.spec_from_file_location("retrieval_accounting_v12", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0020" and module.down_revision == "0019"

    with patch.object(module, "op") as operation:
        module.upgrade()

    sql = "\n".join(call.args[0] for call in operation.execute.call_args_list)
    assert "DROP CONSTRAINT IF EXISTS ck_report_retrieval_accounting_snapshot" in sql
    assert "schemaVersion' IN ('1.1', '1.2')" in sql
    assert "octet_length(retrieval_accounting::text) <= 65536" in sql
    assert "UPDATE reports" not in sql
    with pytest.raises(RuntimeError, match="persisted retrieval-accounting v1.2"):
        module.downgrade()
