import json
import logging
import uuid
from time import monotonic
from unittest.mock import AsyncMock

import pytest

from research_api import auth
from research_api.config import Settings
from research_api.telemetry import (
    dependency_event,
    error_facts,
    langsmith_trace_context,
    milestone_event,
    operation_event,
    request_id,
)


@pytest.fixture
def clear_langsmith_client_cache():
    from research_api.telemetry import _langsmith_client

    _langsmith_client.cache_clear()
    yield
    _langsmith_client.cache_clear()


def test_langsmith_trace_context_is_opt_in_and_redacts_graph_io(
    monkeypatch, clear_langsmith_client_cache
):
    from contextlib import nullcontext
    from types import ModuleType

    created = {}
    entered = []

    class Client:
        def __init__(self, **kwargs):
            created.update(kwargs)

    def tracing_context(**kwargs):
        entered.append(kwargs)
        return nullcontext()

    langsmith_module = ModuleType("langsmith")
    langsmith_module.Client = Client
    helpers_module = ModuleType("langsmith.run_helpers")
    helpers_module.tracing_context = tracing_context
    monkeypatch.setitem(__import__("sys").modules, "langsmith", langsmith_module)
    monkeypatch.setitem(__import__("sys").modules, "langsmith.run_helpers", helpers_module)

    disabled = Settings(_env_file=None)
    with langsmith_trace_context(
        disabled, run_id=uuid.uuid4(), graph_version="v1", mode="balanced"
    ):
        pass
    assert created == {}
    assert entered[0] == {"enabled": False}

    enabled = Settings(
        _env_file=None,
        LANGSMITH_TRACING_ENABLED=True,
        LANGSMITH_API_KEY="fixture-key",
        LANGSMITH_PROJECT="research-test",
    )
    run_id = uuid.uuid4()
    with langsmith_trace_context(enabled, run_id=run_id, graph_version="v7", mode="deep"):
        pass

    assert created["api_key"] == "fixture-key"
    assert created["hide_inputs"] is True
    assert created["hide_outputs"] is True
    assert created["anonymizer"]({"error": "private provider message"}) == {
        "error": "exception details redacted"
    }
    assert callable(created["hide_metadata"])
    allowed_run_id = str(uuid.uuid4())
    assert created["hide_metadata"](
        {"run_id": allowed_run_id, "graph_version": "v2", "mode": "deep", "prompt": "private"}
    ) == {
        "run_id": allowed_run_id,
        "graph_version": "v2",
        "mode": "deep",
    }
    assert created["hide_metadata"](
        {"run_id": "private prompt", "graph_version": "private prompt", "mode": "private"}
    ) == {}
    assert entered[1]["enabled"] is True
    assert entered[1]["project_name"] == "research-test"
    assert entered[1]["metadata"] == {
        "run_id": str(run_id),
        "graph_version": "v7",
        "mode": "deep",
    }


def test_langsmith_trace_setup_failure_does_not_interrupt_application(
    monkeypatch, clear_langsmith_client_cache
):
    from types import ModuleType

    class BrokenClient:
        def __init__(self, **_kwargs):
            raise RuntimeError("private client initialization detail")

    langsmith_module = ModuleType("langsmith")
    langsmith_module.Client = BrokenClient
    helpers_module = ModuleType("langsmith.run_helpers")
    helpers_module.tracing_context = lambda **_kwargs: None
    monkeypatch.setitem(__import__("sys").modules, "langsmith", langsmith_module)
    monkeypatch.setitem(__import__("sys").modules, "langsmith.run_helpers", helpers_module)
    settings = Settings(
        _env_file=None,
        LANGSMITH_TRACING_ENABLED=True,
        LANGSMITH_API_KEY="fixture-key",
    )

    with langsmith_trace_context(settings, run_id=uuid.uuid4(), graph_version="v1", mode="focused"):
        assert True


def test_langsmith_export_failure_is_best_effort_and_preserves_graph_error(
    monkeypatch, clear_langsmith_client_cache, caplog
):
    from types import ModuleType

    class FailingExit:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            raise RuntimeError("sensitive trace exporter detail")

    class Client:
        def __init__(self, **_kwargs):
            pass

    langsmith_module = ModuleType("langsmith")
    langsmith_module.Client = Client
    helpers_module = ModuleType("langsmith.run_helpers")
    helpers_module.tracing_context = lambda **_kwargs: FailingExit()
    monkeypatch.setitem(__import__("sys").modules, "langsmith", langsmith_module)
    monkeypatch.setitem(__import__("sys").modules, "langsmith.run_helpers", helpers_module)
    settings = Settings(
        _env_file=None,
        LANGSMITH_TRACING_ENABLED=True,
        LANGSMITH_API_KEY="fixture-key",
    )

    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        with langsmith_trace_context(
            settings, run_id=uuid.uuid4(), graph_version="v1", mode="focused"
        ):
            pass
        original = ValueError("graph failure")
        with pytest.raises(ValueError) as caught:
            with langsmith_trace_context(
                settings, run_id=uuid.uuid4(), graph_version="v1", mode="focused"
            ):
                raise original
    assert caught.value is original
    assert "sensitive trace exporter detail" not in caplog.text


def test_dispatcher_slot_observation_emits_replica_scoped_counts(caplog):
    from research_api.telemetry import dispatcher_slot_event

    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        dispatcher_slot_event(
            worker_instance_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            run_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            phase="acquired",
            active_workers=2,
            concurrency_limit=3,
        )

    event = json.loads(caplog.records[-1].message)
    assert event["operation"] == "dispatcher.worker.slot"
    assert event["phase"] == "acquired"
    assert event["workerInstanceId"] == "00000000-0000-0000-0000-000000000001"
    assert event["runId"] == "00000000-0000-0000-0000-000000000002"
    assert event["activeWorkers"] == 2
    assert event["concurrencyLimit"] == 3
    assert event["processInstanceId"]


async def test_dispatcher_loop_releases_replica_slot_on_worker_cancellation(monkeypatch, caplog):
    import asyncio

    from research_api import dispatcher
    from research_api.runtime_context import JobFence

    tenant_id, run_id = uuid.uuid4(), uuid.uuid4()
    fence = JobFence(tenant_id, run_id, uuid.uuid4(), 1)
    claimed = False
    worker_started = asyncio.Event()

    async def discover():
        return [tenant_id]

    async def claim(_tenant, _owner, _settings):
        nonlocal claimed
        if claimed:
            return None
        claimed = True
        return fence

    async def wait_for_cancellation(*_args):
        worker_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(dispatcher.jobs, "discover", discover)
    monkeypatch.setattr(dispatcher.jobs, "claim", claim)
    monkeypatch.setattr(dispatcher, "execute", wait_for_cancellation)
    settings = Settings(_env_file=None, WORKER_CONCURRENCY=2)

    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        loop_task = asyncio.create_task(dispatcher.dispatch_loop(settings, object()))
        await asyncio.wait_for(worker_started.wait(), timeout=2)
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task

    events = [
        json.loads(record.message)
        for record in caplog.records
        if '"operation": "dispatcher.worker.slot"' in record.message
    ]
    assert [event["phase"] for event in events] == ["acquired", "released"]
    assert [event["activeWorkers"] for event in events] == [1, 0]
    assert all(event["concurrencyLimit"] == 2 for event in events)


def test_graph_state_contract_keeps_source_ids_unique_and_checkpoint_keys_stable():
    from typing import get_type_hints

    from research_api.graph.state import RunState, merge_source_ids

    assert merge_source_ids(["source-a", "source-b"], ["source-b", "source-c"]) == [
        "source-a",
        "source-b",
        "source-c",
    ]
    assert set(get_type_hints(RunState, include_extras=True)) == {
        "run_id",
        "tenant_id",
        "user_id",
        "question",
        "sub_question_ids",
        "source_ids",
        "quick_mode",
        "mode",
        "mode_policy_version",
        "graph_version",
        "discovery_provider",
        "openalex_discovery_enabled",
        "error",
        "reflection_round",
        "expand",
        "assessment_id",
        "repair_admitted",
    }


def test_group_leaves_include_sqlstate_without_exception_contents(caplog):
    from psycopg.errors import DeadlockDetected
    from sqlalchemy.exc import OperationalError

    error = ExceptionGroup(
        "secret question",
        [
            OperationalError("secret SQL", {"token": "secret token"}, DeadlockDetected("secret")),
            ValueError("secret body"),
        ],
    )
    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        operation_event("research.graph", started=monotonic(), outcome="failed", error=error)
    record = json.loads(caplog.records[-1].message)
    assert any(fact.get("sqlstate") == "40P01" for fact in record["errors"])
    assert "secret" not in caplog.text
    assert len(error_facts(ExceptionGroup("x", [ValueError("x")] * 100))) == 8


async def test_shared_auth_transport_still_verifies_each_request(monkeypatch):
    import httpx

    subject = uuid.uuid4()
    get = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "id": str(subject),
                "role": "authenticated",
                "email_confirmed_at": "2026-01-01",
            },
        )
    )
    client = AsyncMock()
    client.get = get
    monkeypatch.setattr(auth, "_identity_client", client)
    settings = Settings(
        _env_file=None,
        SUPABASE_URL="https://identity.example.test",
        SUPABASE_PUBLISHABLE_KEY="fixture",
    )
    for _ in range(2):
        assert await auth.verified_subject(settings, "Bearer fixture") == subject
    assert get.await_count == 2
    client.aclose.assert_not_awaited()


def test_request_context_is_reset(caplog):
    identity = str(uuid.uuid4())
    token = request_id.set(identity)
    try:
        with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
            operation_event("fixture", started=monotonic())
        assert json.loads(caplog.records[-1].message)["requestId"] == identity
    finally:
        request_id.reset(token)
    assert request_id.get() is None


async def test_asgi_timing_propagates_safe_id_and_does_not_log_path_or_body(caplog):
    from research_api.main import RequestTiming

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"secret body"})

    sent = []

    async def send(message):
        sent.append(message)

    with caplog.at_level(logging.DEBUG, logger="research_api.dependencies"):
        await RequestTiming(app)(
            {
                "type": "http",
                "path": "/secret-question",
                "headers": [(b"x-request-id", b"secret token")],
            },
            AsyncMock(),
            send,
        )
    identity = dict(sent[0]["headers"])[b"x-request-id"].decode()
    uuid.UUID(identity)
    records = [json.loads(record.message) for record in caplog.records]
    assert all(record["requestId"] == identity for record in records)
    assert records[-1]["firstByteMs"] is not None
    assert "secret" not in caplog.text
    assert request_id.get() is None


def test_default_logs_keep_failures_but_drop_routine_database_noise(caplog):
    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        operation_event("db.transaction", started=monotonic())
        operation_event("auth.verify", started=monotonic())
        operation_event(
            "node.synthesizer", started=monotonic(), outcome="failed", error=ValueError("secret")
        )
    records = [json.loads(record.message) for record in caplog.records]
    assert [row["operation"] for row in records] == ["node.synthesizer"]
    assert "secret" not in caplog.text


def test_debug_logging_retains_transaction_details(caplog):
    with caplog.at_level(logging.DEBUG, logger="research_api.dependencies"):
        operation_event("db.transaction", started=monotonic(), setupMs=42)
    assert json.loads(caplog.records[-1].message)["setupMs"] == 42


def test_model_token_telemetry_contains_only_validated_usage_counts(caplog):
    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        dependency_event(
            provider="openai",
            operation="model",
            outcome="consumed",
            input_tokens=120,
            output_tokens=24,
        )
    record = json.loads(caplog.records[-1].message)
    assert record["inputTokens"] == 120
    assert record["outputTokens"] == 24
    assert "prompt" not in caplog.text and "response" not in caplog.text
    with pytest.raises(ValueError):
        dependency_event(
            provider="openai", operation="model", outcome="consumed", input_tokens=True
        )


def test_research_milestone_is_timestamped_and_contains_only_allowlisted_facts(caplog):
    with caplog.at_level(logging.INFO, logger="research_api.dependencies"):
        milestone_event("research.first_verified_finding", verified_finding_count=2)
    record = json.loads(caplog.records[-1].message)
    assert record["event"] == "research.milestone"
    assert record["milestone"] == "research.first_verified_finding"
    assert record["verifiedFindingCount"] == 2
    assert "durationMs" not in record
    with pytest.raises(ValueError):
        milestone_event("research.first_verified_finding", verified_finding_count=True)
    with pytest.raises(ValueError):
        milestone_event("unknown", verified_finding_count=2)


@pytest.mark.parametrize("status,outcome", [(200, "succeeded"), (401, "rejected"), (503, "failed")])
async def test_http_error_responses_are_never_logged_as_success(caplog, status, outcome):
    from research_api.main import RequestTiming

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    with caplog.at_level(logging.DEBUG, logger="research_api.dependencies"):
        await RequestTiming(app)({"type": "http", "headers": []}, AsyncMock(), AsyncMock())
    events = [json.loads(record.message) for record in caplog.records]
    request = next(event for event in events if event["operation"] == "http.request")
    assert request["statusCode"] == status
    assert request["outcome"] == outcome
