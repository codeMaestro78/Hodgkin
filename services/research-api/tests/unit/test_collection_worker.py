import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.config import Settings
from research_api.db.models import Budget, ResearchRun, SubQuestion
from research_api.graph import builder


@pytest.mark.asyncio
@pytest.mark.parametrize("calls,questions", [(6, 3), (12, 6), (20, 8)])
async def test_real_worker_bounds_sources_and_concurrency(monkeypatch, calls, questions) -> None:
    question_ids = [str(uuid.uuid4()) for _ in range(questions)]
    records = {
        key: SimpleNamespace(id=uuid.UUID(key), question=key, status="pending", attempts=0)
        for key in question_ids
    }
    slots_used = []
    active = peak = 0

    class Session:
        def add(self, _record):
            pass

        async def flush(self):
            pass

        async def scalar(self, statement):
            entity = statement.column_descriptions[0].get("entity")
            if entity is Budget:
                return SimpleNamespace(max_search_calls=calls)
            if entity is ResearchRun:
                # Collection cleanup reads cancellation intent under the real
                # lifecycle lock; this fixture models an active, uncancelled run.
                return SimpleNamespace(concurrency_limit=3, cancellation_requested_at=None)
            if entity is SubQuestion:
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

    monkeypatch.setattr(builder, "tenant_session", session)
    monkeypatch.setattr(builder, "TavilyEvidenceIngestor", Ingestor)
    monkeypatch.setattr(builder, "S3ArtifactStore", lambda **_kwargs: object())
    monkeypatch.setattr(
        builder, "TavilyAdapter", lambda **_kwargs: SimpleNamespace(aclose=AsyncMock())
    )
    monkeypatch.setattr(builder, "_cancel_if_requested", AsyncMock(return_value=False))
    monkeypatch.setattr(builder, "_transition", AsyncMock())
    monkeypatch.setattr(builder, "start_node", AsyncMock(return_value=uuid.uuid4()))
    monkeypatch.setattr(builder, "finish_node", AsyncMock())
    monkeypatch.setattr(builder, "EventOutbox", lambda *_args: SimpleNamespace(append=AsyncMock()))
    worker = (
        builder.build_graph(Settings(_env_file=None, TAVILY_API_KEY="test"))
        .nodes["research_worker"]
        .bound.afunc
    )
    result = await worker(
        {
            "tenant_id": str(uuid.uuid4()),
            "run_id": str(uuid.uuid4()),
            "sub_question_ids": question_ids,
            "quick_mode": False,
        }
    )
    assert len(result["source_ids"]) <= calls
    assert sum(slots_used) == calls
    assert peak == 3
    assert all(record.status == "complete" for record in records.values())
