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
    milestone_event,
    operation_event,
    request_id,
)


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
