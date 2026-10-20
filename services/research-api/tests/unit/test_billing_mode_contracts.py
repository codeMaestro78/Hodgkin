import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import patch

from research_api.db.models import ResearchBatch, ResearchSchedule
from research_api.mode_policy import MODE_POLICIES
from research_api.runtime_api import budget_from
from research_api.schemas.generated.batch_request import BatchRequest
from research_api.schemas.generated.schedule_request import ScheduleRequest


def test_batch_and_schedule_keep_legacy_mode_optional():
    batch = BatchRequest(questions=["Compare queues"], idempotencyKey="legacy-batch-key-01")
    schedule = ScheduleRequest(
        question="Compare queues",
        intervalMinutes=60,
        idempotencyKey="legacy-schedule-key-01",
    )
    assert batch.mode is None
    assert schedule.mode is None
    assert "mode" not in batch.model_dump(exclude={"mode"})


def test_mode_budget_uses_server_ceiling_and_allows_tightening_overrides():
    deep = budget_from(
        BatchRequest(
            questions=["Compare queues"],
            idempotencyKey="explicit-batch-key-01",
            mode="deep",
        )
    )
    focused_tightened = budget_from(
        ScheduleRequest(
            question="Compare queues",
            intervalMinutes=60,
            idempotencyKey="explicit-schedule-key-01",
            mode="focused",
            budgetOverrides={"maxProviderOperations": 4, "maxSources": 3},
        )
    )
    assert deep.max_provider_operations == deep.max_sources == 20
    assert deep.max_output_tokens == 40_000
    assert focused_tightened.max_provider_operations == 4
    assert focused_tightened.max_sources == 3


def test_replayed_mode_request_can_resolve_against_its_pinned_policy(monkeypatch):
    old_version = "research-mode-policy-test-old"
    monkeypatch.setitem(
        MODE_POLICIES,
        old_version,
        {
            "focused": (4, 120_000),
            "balanced": (8, 240_000),
            "deep": (16, 480_000),
        },
    )
    request = ScheduleRequest(
        question="Compare queues",
        intervalMinutes=60,
        idempotencyKey="policy-version-replay-01",
        mode="deep",
        budgetOverrides={"maxProviderOperations": 10},
    )
    assert budget_from(request, old_version).max_provider_operations == 10


def test_batch_and_schedule_persist_mode_policy_as_a_pair():
    for model in (ResearchBatch, ResearchSchedule):
        constraint = next(
            item
            for item in model.__table__.constraints
            if item.name == "ck_" + model.__tablename__ + "_mode_snapshot"
        )
        assert "mode IS NULL AND mode_policy_version IS NULL" in str(constraint.sqltext)
        assert "mode_policy_version IS NOT NULL" in str(constraint.sqltext)
        assert "length(btrim(mode_policy_version)) > 0" in str(constraint.sqltext)


def test_mode_snapshot_migration_is_additive_and_non_destructive():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0025_batch_schedule_mode_snapshots.py"
    )
    spec = importlib.util.spec_from_file_location("batch_schedule_modes_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0025" and migration.down_revision == "0024"
    statements: list[str] = []
    with patch.object(migration, "op") as operation:
        operation.execute.side_effect = lambda statement: statements.append(statement)
        migration.upgrade()
    sql = " ".join(" ".join(statement.split()) for statement in statements)
    assert sql.count("ADD COLUMN IF NOT EXISTS mode varchar(16)") == 2
    assert sql.count("ADD COLUMN IF NOT EXISTS mode_policy_version varchar(64)") == 2
    assert "UPDATE" not in sql and "DELETE" not in sql


def test_legacy_batch_fingerprint_excludes_absent_mode():
    from research_api.runtime_api import _batch_request_fingerprint

    request = BatchRequest(questions=["Compare queues"], idempotencyKey="legacy-batch-key-02")
    expected = request.model_dump_json(exclude={"mode"})
    assert _batch_request_fingerprint(request) == hashlib.sha256(expected.encode()).hexdigest()


def test_explicit_batch_mode_is_part_of_the_idempotency_fingerprint():
    from research_api.runtime_api import _batch_request_fingerprint

    common = {
        "questions": ["Compare queues"],
        "idempotencyKey": "explicit-batch-key-02",
    }
    focused = BatchRequest(**common, mode="focused")
    deep = BatchRequest(**common, mode="deep")
    assert _batch_request_fingerprint(focused) != _batch_request_fingerprint(deep)
