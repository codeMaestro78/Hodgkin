import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.config import Settings
from research_api.db.models import Budget, ResearchRun, SubQuestion
from research_api.graph import builder, collection


@pytest.mark.asyncio
@pytest.mark.parametrize("calls,questions", [(6, 3), (12, 6), (20, 8)])
@pytest.mark.parametrize("route", ["legacy", "tavily", "serper"])
async def test_real_worker_bounds_sources_and_concurrency(
    monkeypatch, calls, questions, route
) -> None:
    question_ids = [str(uuid.uuid4()) for _ in range(questions)]
    records = {
        key: SimpleNamespace(id=uuid.UUID(key), question=key, status="pending", attempts=0)
        for key in question_ids
    }
    slots_used = []
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
    assert peak == 3
    assert all(record.status == "complete" for record in records.values())
    assert len(setup_sessions) == 1, "Worker setup must reuse one tenant transaction"
    assert len(discovery_instances) == (1 if route == "serper" else 0)
    for instance in discovery_instances:
        instance.aclose.assert_awaited_once()
