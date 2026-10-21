import asyncio
import uuid
from contextlib import asynccontextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.config import Settings
from research_api.db.models import Budget, ResearchRun, SubQuestion, SubQuestionAttempt
from research_api.graph import builder, collection


@pytest.mark.parametrize("planned_count", [0, 3])
def test_collection_rejects_planned_questions_left_unattempted(planned_count: int) -> None:
    question_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    expected_ids = question_ids[:planned_count]
    rows = (
        [(question_ids[0], "failed"), (question_ids[1], "pending"), (question_ids[2], "pending")]
        if planned_count
        else []
    )

    with pytest.raises(RuntimeError, match="collection left planned questions unresolved"):
        collection.ensure_collection_questions_resolved(expected_ids, rows)


def test_collection_allows_pending_questions_after_bounded_collection_window() -> None:
    question_ids = [uuid.uuid4(), uuid.uuid4()]

    collection.ensure_collection_questions_resolved(
        question_ids,
        [(question_ids[0], "complete"), (question_ids[1], "pending")],
        allow_pending=True,
    )


def test_collection_still_rejects_running_questions_after_bounded_window() -> None:
    question_ids = [uuid.uuid4(), uuid.uuid4()]

    with pytest.raises(RuntimeError, match="unresolved=1"):
        collection.ensure_collection_questions_resolved(
            question_ids,
            [(question_ids[0], "complete"), (question_ids[1], "running")],
            allow_pending=True,
        )


@pytest.mark.parametrize(
    "user_cancelled,reserve_timeout,expected",
    [
        (True, True, "run_cancelled"),
        (True, False, "run_cancelled"),
        (False, True, "assessment_time_reserved"),
        (False, False, "worker_interrupted"),
    ],
)
def test_collection_attempt_cancellation_records_the_actual_cause(
    user_cancelled, reserve_timeout, expected
):
    assert (
        collection.collection_attempt_cancel_reason(
            user_cancelled=user_cancelled,
            reserve_timeout=reserve_timeout,
        )
        == expected
    )


@pytest.mark.asyncio
async def test_expired_explicit_collection_window_continues_with_pending_questions(
    monkeypatch,
) -> None:
    question_ids = [uuid.uuid4(), uuid.uuid4()]
    rows = {
        question_id: SimpleNamespace(id=question_id, status="pending")
        for question_id in question_ids
    }

    class Session:
        async def scalar(self, statement):
            entity = statement.column_descriptions[0].get("entity")
            if entity is Budget:
                return SimpleNamespace(max_search_calls=6)
            if entity is ResearchRun:
                return SimpleNamespace(
                    concurrency_limit=3,
                    cancellation_requested_at=None,
                    mode=None,
                    active_plan_id=None,
                )
            return 0 if entity is None else None

        async def execute(self, _statement):
            return SimpleNamespace(
                all=lambda: [(question.id, question.status) for question in rows.values()]
            )

    @asynccontextmanager
    async def session(_tenant):
        yield Session()

    monkeypatch.setattr(collection, "tenant_session", session)
    monkeypatch.setattr(collection, "S3ArtifactStore", lambda **_kwargs: object())
    monkeypatch.setattr(
        collection, "TavilyAdapter", lambda **_kwargs: SimpleNamespace(aclose=AsyncMock())
    )
    monkeypatch.setattr(collection, "_cancel_if_requested", AsyncMock(return_value=False))
    transition = AsyncMock()
    monkeypatch.setattr(collection, "_transition", transition)
    monkeypatch.setattr(builder, "_cancel_if_requested", AsyncMock(return_value=False))
    monkeypatch.setattr(builder, "start_node", AsyncMock(return_value=uuid.uuid4()))
    monkeypatch.setattr(builder, "finish_node", AsyncMock())
    monkeypatch.setattr(collection, "TavilyEvidenceIngestor", lambda **_kwargs: SimpleNamespace())
    deadline_token = builder.assessment_deadline.set(monotonic() - 1)
    try:
        worker = (
            builder.build_graph(Settings(_env_file=None, TAVILY_API_KEY="test"))
            .nodes["research_worker"]
            .bound.afunc
        )
        result = await worker(
            {
                "tenant_id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "sub_question_ids": [str(question_id) for question_id in question_ids],
                "quick_mode": False,
                "mode": "focused",
                "graph_version": next(iter(builder.PROTECTED_EXPLICIT_GRAPH_VERSIONS)),
            }
        )
    finally:
        builder.assessment_deadline.reset(deadline_token)

    assert result == {"source_ids": []}
    assert all(question.status == "pending" for question in rows.values())
    transition.assert_awaited_once()


@pytest.mark.asyncio
async def test_collection_cancellation_during_attempt_finalization_reconciles_pending(
    monkeypatch,
) -> None:
    question_id = uuid.uuid4()
    question = SimpleNamespace(
        id=question_id,
        status="pending",
        attempts=0,
        question="LangGraph fan-out semantics",
        payload={},
    )
    run = SimpleNamespace(
        concurrency_limit=3,
        cancellation_requested_at=None,
        mode=None,
        active_plan_id=None,
    )
    attempts = []
    finalizer_cancelled = False

    class Session:
        def add(self, record):
            attempts.append(record)

        async def flush(self):
            pass

        async def scalar(self, statement):
            nonlocal finalizer_cancelled
            entity = statement.column_descriptions[0].get("entity")
            if entity is Budget:
                return SimpleNamespace(max_search_calls=2)
            if entity is ResearchRun:
                return run
            if entity is SubQuestion:
                return question
            if entity is SubQuestionAttempt:
                if not finalizer_cancelled:
                    finalizer_cancelled = True
                    # Model the transaction rollback after cancellation interrupts
                    # the attempt lookup, undoing the earlier status assignment.
                    question.status = "running"
                    raise asyncio.CancelledError
                return attempts[0]
            return 0 if entity is None else None

        async def execute(self, _statement):
            return SimpleNamespace(all=lambda: [(question.id, question.status)])

    @asynccontextmanager
    async def session(_tenant):
        yield Session()

    monkeypatch.setattr(collection, "tenant_session", session)
    monkeypatch.setattr(collection, "S3ArtifactStore", lambda **_kwargs: object())
    monkeypatch.setattr(
        collection, "TavilyAdapter", lambda **_kwargs: SimpleNamespace(aclose=AsyncMock())
    )
    monkeypatch.setattr(collection, "_cancel_if_requested", AsyncMock(return_value=False))
    monkeypatch.setattr(builder, "_cancel_if_requested", AsyncMock(return_value=False))
    monkeypatch.setattr(builder, "start_node", AsyncMock(return_value=uuid.uuid4()))
    monkeypatch.setattr(builder, "finish_node", AsyncMock())
    transition = AsyncMock()
    monkeypatch.setattr(collection, "_transition", transition)
    monkeypatch.setattr(collection, "_explicit_assessment_tail_seconds", lambda *_args: 0)
    monkeypatch.setattr(
        collection,
        "TavilyEvidenceIngestor",
        lambda **_kwargs: SimpleNamespace(ingest=AsyncMock(return_value=[uuid.uuid4()])),
    )
    monkeypatch.setattr(
        collection, "EventOutbox", lambda *_args: SimpleNamespace(append=AsyncMock())
    )
    deadline_token = builder.assessment_deadline.set(monotonic() + 30)
    try:
        worker = (
            builder.build_graph(Settings(_env_file=None, TAVILY_API_KEY="test"))
            .nodes["research_worker"]
            .bound.afunc
        )
        result = await worker(
            {
                "tenant_id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "sub_question_ids": [str(question_id)],
                "quick_mode": False,
                "mode": "focused",
                "graph_version": next(iter(builder.PROTECTED_EXPLICIT_GRAPH_VERSIONS)),
            }
        )
    finally:
        builder.assessment_deadline.reset(deadline_token)

    assert result["source_ids"]
    assert question.status == "pending"
    assert attempts[0].status == "cancelled"
    transition.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("calls,questions", [(6, 3), (12, 6), (20, 8)])
@pytest.mark.parametrize("route", ["legacy", "tavily", "serper"])
async def test_real_worker_bounds_sources_and_concurrency(
    monkeypatch, calls, questions, route
) -> None:
    question_ids = [str(uuid.uuid4()) for _ in range(questions)]
    records = {
        key: SimpleNamespace(
            id=uuid.UUID(key),
            question=key,
            status="pending",
            attempts=0,
            payload={"allowed_domains": ["docs.langchain.com"]},
        )
        for key in question_ids
    }
    slots_used = []
    forwarded_domains = []
    active = peak = 0
    collection_started = False
    session_count = 0
    setup_sessions = set()
    discovery_instances = []

    class Session:
        def __init__(self):
            nonlocal session_count
            session_count += 1
            self.number = session_count

        def add(self, _record):
            pass

        async def flush(self):
            pass

        async def scalar(self, statement):
            nonlocal collection_started
            entity = statement.column_descriptions[0].get("entity")
            if not collection_started and entity in {Budget, ResearchRun}:
                setup_sessions.add(self.number)
            if entity is Budget:
                return SimpleNamespace(max_search_calls=calls)
            if entity is ResearchRun:
                # Collection cleanup reads cancellation intent under the real
                # lifecycle lock; this fixture models an active, uncancelled run.
                return SimpleNamespace(
                    concurrency_limit=3,
                    cancellation_requested_at=None,
                    mode=None,
                    active_plan_id=None,
                )
            if entity is SubQuestion:
                collection_started = True
                key = str(statement.compile().params["id_1"])
                return records[key]
            return 0 if entity is None else None

        async def execute(self, _statement):
            return SimpleNamespace(
                all=lambda: [(record.id, record.status) for record in records.values()]
            )

    @asynccontextmanager
    async def session(_tenant):
        yield Session()

    class Ingestor:
        def __init__(self, **_kwargs):
            pass

        async def ingest(self, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            slots_used.append(kwargs["max_results"])
            forwarded_domains.append(kwargs["allowed_domains"])
            await asyncio.sleep(0)
            active -= 1
            return [uuid.uuid4() for _ in range(kwargs["max_results"])]

    monkeypatch.setattr(collection, "tenant_session", session)
    monkeypatch.setattr(collection, "TavilyEvidenceIngestor", Ingestor)
    monkeypatch.setattr(collection, "S3ArtifactStore", lambda **_kwargs: object())
    monkeypatch.setattr(
        collection, "TavilyAdapter", lambda **_kwargs: SimpleNamespace(aclose=AsyncMock())
    )

    def discovery(**_kwargs):
        instance = SimpleNamespace(aclose=AsyncMock())
        discovery_instances.append(instance)
        return instance

    monkeypatch.setattr(collection, "SerperAdapter", discovery)
    monkeypatch.setattr(collection, "_cancel_if_requested", AsyncMock(return_value=False))
    monkeypatch.setattr(builder, "_cancel_if_requested", AsyncMock(return_value=False))
    monkeypatch.setattr(collection, "_transition", AsyncMock())
    monkeypatch.setattr(builder, "start_node", AsyncMock(return_value=uuid.uuid4()))
    monkeypatch.setattr(builder, "finish_node", AsyncMock())
    monkeypatch.setattr(
        collection, "EventOutbox", lambda *_args: SimpleNamespace(append=AsyncMock())
    )
    worker = (
        builder.build_graph(
            Settings(
                _env_file=None,
                TAVILY_API_KEY="test",
                SERPER_API_KEY="fixture",
                SERPER_DISCOVERY_ENABLED=True,
            )
        )
        .nodes["research_worker"]
        .bound.afunc
    )
    result = await worker(
        {
            "tenant_id": str(uuid.uuid4()),
            "run_id": str(uuid.uuid4()),
            "sub_question_ids": question_ids,
            "quick_mode": False,
            **({"discovery_provider": route} if route != "legacy" else {}),
        }
    )
    assert len(result["source_ids"]) <= calls
    assert sum(slots_used) == calls
    assert forwarded_domains == [["docs.langchain.com"]] * questions
    assert peak == 3
    assert all(record.status == "complete" for record in records.values())
    assert len(setup_sessions) == 1, "Worker setup must reuse one tenant transaction"
    assert len(discovery_instances) == (1 if route == "serper" else 0)
    for instance in discovery_instances:
        instance.aclose.assert_awaited_once()
