"""Bootstrap scope must not depend on which future ORM models were imported."""

import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import Column, ForeignKey, MetaData, Table, Uuid

# Register both late families deliberately, matching migrations/env.py.
from research_api.db.assessments import ResearchAssessment
from research_api.db.source_relationships import SourceRelationship


def migration():
    return importlib.import_module("research_api.db.migrations.versions.0001_authoritative_core")


def test_bootstrap_excludes_registered_late_models_and_scopes_ddl_and_grants(monkeypatch):
    module = migration()
    tables = module._bootstrap_tables()
    assert {table.name for table in tables} == {"tenants", *module.TENANT_TABLES}
    assert ResearchAssessment.__table__ not in tables
    assert SourceRelationship.__table__ not in tables
    assert all(fk.column.table in tables for table in tables for fk in table.foreign_keys)
    operations = Mock()
    create, drop = Mock(), Mock()
    monkeypatch.setattr(module, "op", operations)
    monkeypatch.setattr(module.Base.metadata, "create_all", create)
    monkeypatch.setattr(module.Base.metadata, "drop_all", drop)
    module.upgrade()
    create.assert_called_once_with(bind=operations.get_bind.return_value, tables=tables)
    statements = "\n".join(call.args[0] for call in operations.execute.call_args_list)
    assert "ON ALL TABLES" not in statements
    assert 'public."sources"' in statements
    assert "research_assessments" not in statements
    module.downgrade()
    drop.assert_called_once_with(bind=operations.get_bind.return_value, tables=tables)


def test_bootstrap_rejects_future_fk_before_issuing_ddl(monkeypatch):
    module = migration()
    metadata = MetaData()
    for name in ("tenants", *module.TENANT_TABLES):
        Table(name, metadata, Column("id", Uuid, primary_key=True))
    Table("future_private_data", metadata, Column("id", Uuid, primary_key=True))
    metadata.tables["users"].append_column(
        Column("future_id", Uuid, ForeignKey("future_private_data.id"))
    )
    create = Mock()
    monkeypatch.setattr(metadata, "create_all", create)
    monkeypatch.setattr(module, "Base", SimpleNamespace(metadata=metadata))
    operations = Mock()
    monkeypatch.setattr(module, "op", operations)
    with pytest.raises(RuntimeError, match="references a later table"):
        module.upgrade()
    create.assert_not_called()
    operations.execute.assert_not_called()
