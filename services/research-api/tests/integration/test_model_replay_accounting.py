"""Milestone 6: real local PG, SDK mock transport, private replay and proof only."""

import asyncio
import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from research_api import accounting_ops, model_budget
from research_api.db.models import (
    ProviderCall,
    ProviderCallReservation,
    ResearchRun,
    Tenant,
    UsageLedger,
    User,
)
from research_api.db.session import tenant_session
from research_api.graph.builder import SynthesisOutput
from research_api.model_budget import model_response, model_run
from research_api.model_routing import pin_run_model_routing
from research_api.repositories.budgets import (
    BudgetExceededError,
    BudgetReservationRepository,
    InvalidReservationTransitionError,
    ReservationReplayError,
)
from research_api.repositories.runs import RunBudgetDefaults, RunRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("failed", [False, True])
async def test_remote_timing_excludes_slow_accounting_and_replay(monkeypatch, failed):
    identity = await seed()
    sdk = client()
    clock = [10.0]
    returned = False
    emitted = []
    original_session = model_budget.tenant_session

    async def remote(**_):
        nonlocal returned
        clock[0] += 0.25
        returned = True
        if failed:
            raise ValueError("private remote failure")
        return sdk.responses.create.return_value

    @asynccontextmanager
    async def slow_settlement(tenant):
        async with original_session(tenant) as session:
            yield session
        if returned:
            clock[0] += 5.0  # Deterministic accounting delay, no real sleep.

    sdk.responses.create.side_effect = remote
    monkeypatch.setattr(model_budget, "monotonic", lambda: clock[0])
    monkeypatch.setattr(model_budget, "tenant_session", slow_settlement)
    monkeypatch.setattr(model_budget, "dependency_event", lambda **facts: emitted.append(facts))
    if failed:
        with pytest.raises(ValueError, match="private remote failure"):
            await invoke(identity, sdk, role="writer")
    else:
        await invoke(identity, sdk, role="writer")
        await invoke(
            identity, sdk, role="writer"
        )  # Replay must not count as a new remote observation.
    assert sdk.responses.create.await_count == 1
    assert [event["outcome"] for event in emitted] == [
        "started",
        "uncertain" if failed else "consumed",
    ]
    assert emitted[0]["model"] == "gpt-4o-mini"
    assert emitted[0]["role"] == "writer"
    assert "remote_duration_ms" not in emitted[0]
    assert emitted[1]["remote_duration_ms"] == 250
    assert clock[0] >= 15.25


TEXT = json.dumps(
    {
        "answer_markdown": "Evidence supports this claim [1].",
        "claims": [
            {
                "claim": "Evidence supports this claim.",
                "caveats": [],
                "citations": [{"source_number": 1, "quote": "Exact evidence quotation"}],
            }
        ],
    }
)


async def seed():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Model replay fixture"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await engine.dispose()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user, question="Model replay fixture", budget=RunBudgetDefaults()
        )
        return tenant, run.id


async def test_model_routes_stay_pinned_when_runtime_configuration_changes():
    tenant, run_id = await seed()
    original = {
        "planner": {"provider": "openai", "model": "gpt-4o-mini"},
        "writer": {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash"},
        "claim_review": {"provider": "openai", "model": "gpt-5.4-mini"},
    }
    async with tenant_session(str(tenant)) as session:
        run = await session.scalar(
            select(ResearchRun).where(ResearchRun.tenant_id == tenant, ResearchRun.id == run_id)
        )
        assert run is not None
        run.model_routing = original

    changed = {
        "planner": {"provider": "openai", "model": "gpt-6-luna"},
        "writer": {"provider": "openai", "model": "gpt-6-luna"},
        "claim_review": {"provider": "openai", "model": "gpt-6-luna"},
    }
    pinned = await pin_run_model_routing(tenant, run_id, changed, changed)

    assert {role: route.as_dict() for role, route in pinned.items()} == original


def client(*, error=None, text=TEXT):
    return SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                side_effect=error,
                return_value=SimpleNamespace(
                    id="resp_fixture",
                    output_text=text,
                    usage=SimpleNamespace(input_tokens=5, output_tokens=8),
                    raw_web_body="must never be persisted",
                    authorization="private secret",
                ),
            )
        )
    )


async def invoke(identity, sdk, **kwargs):
    token = model_run.set(identity)
    try:
        return await model_response(sdk, model="gpt-4o-mini", input="q", **kwargs)
    finally:
        model_run.reset(token)


async def snapshot(identity):
    tenant, run = identity
    async with tenant_session(str(tenant)) as session:
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        reservations = list(
            await session.scalars(
                select(ProviderCallReservation)
                .where(ProviderCallReservation.run_id == run)
                .order_by(ProviderCallReservation.attempt)
            )
        )
        calls = list(await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run)))
        return usage, reservations, calls


def totals(usage):
    return (
        usage.input_tokens,
        usage.output_tokens,
        usage.estimated_cost_usd,
        usage.reserved_estimated_cost_usd,
        usage.search_calls,
    )


async def test_real_sdk_response_replays_and_synthesis_parses_without_double_charge():
    identity = await seed()
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4o-mini",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_fixture",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": TEXT, "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 8, "total_tokens": 13},
            },
        )

    async with AsyncOpenAI(
        api_key="fixture",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    ) as sdk:
        original = await invoke(identity, sdk, store=False)
        before, _, _ = await snapshot(identity)
        replay = await invoke(identity, sdk, store=False)
        after, reservations, calls = await snapshot(identity)
    assert len(requests) == len(reservations) == len(calls) == 1
    assert replay.output_text == original.output_text == TEXT
    assert replay.usage.input_tokens == original.usage.input_tokens == 5
    assert replay.usage.total_tokens == 13
    assert SynthesisOutput.model_validate_json(replay.output_text).claims[0].caveats == []
    assert totals(before) == totals(after)


async def test_crash_after_commit_reuses_same_fingerprint_and_sanitized_metadata(monkeypatch):
    identity, sdk = await seed(), client()

    def crash(**event):
        if event.get("outcome") == "consumed":
            raise RuntimeError("crash after accounting commit")

    monkeypatch.setattr(model_budget, "dependency_event", crash)
    with pytest.raises(RuntimeError, match="after accounting"):
        await invoke(identity, sdk)
    monkeypatch.setattr(model_budget, "dependency_event", lambda **_: None)
    before, reservations, calls = await snapshot(identity)
    replay = await invoke(identity, sdk)
    after, again, _ = await snapshot(identity)
    assert replay.output_text == TEXT and totals(before) == totals(after)
    assert reservations[0].request_fingerprint == again[0].request_fingerprint
    assert reservations[0].id == again[0].id
    sdk.responses.create.assert_awaited_once()
    metadata = json.dumps(calls[0].provider_usage)
    assert "private secret" not in metadata and "must never be persisted" not in metadata
    foreign = uuid.uuid4()
    async with tenant_session(str(foreign)) as session:
        assert await session.get(ProviderCall, calls[0].id) is None


async def test_crash_before_success_persistence_stays_pending_even_when_old(monkeypatch):
    identity, sdk = await seed(), client()

    def crash(*_):
        raise RuntimeError("crash before receipt")

    monkeypatch.setattr(model_budget, "_replay_projection", crash)
    with pytest.raises(RuntimeError, match="before receipt"):
        await invoke(identity, sdk)
    tenant, run = identity
    async with tenant_session(str(tenant)) as session:
        call = await session.scalar(select(ProviderCall).where(ProviderCall.run_id == run))
        call.started_at = datetime.now(UTC) - timedelta(days=365)
    with pytest.raises(ReservationReplayError):
        await invoke(identity, sdk)
    _, reservations, calls = await snapshot(identity)
    assert reservations[0].state == "reserved" and calls[0].outcome == "pending"
    with pytest.raises(InvalidReservationTransitionError):
        await accounting_ops.reconcile(tenant, run, reservations[0].id, release=True)
    sdk.responses.create.assert_awaited_once()


async def test_safe_retry_policy_survives_crash_without_expanding_attempt_limit(monkeypatch):
    identity = await seed()

    class Rejection(Exception):
        status_code = 429

    sdk = client(error=Rejection())

    async def crash(_):
        raise RuntimeError("crash during backoff")

    monkeypatch.setattr(model_budget, "retry_delay", crash)
    with pytest.raises(RuntimeError, match="backoff"):
        await invoke(identity, sdk, max_attempts=2)
    monkeypatch.setattr(model_budget, "retry_delay", AsyncMock())
    with pytest.raises(Rejection):
        await invoke(identity, sdk, max_attempts=3)
    _, reservations, calls = await snapshot(identity)
    assert [row.attempt for row in reservations] == [1, 2]
    assert all(row.state == "released" for row in reservations)
    assert all(row.provider_usage["attemptPolicy"]["maxAttempts"] == 2 for row in calls)
    assert sdk.responses.create.await_count == 2


@pytest.mark.parametrize("text", [None, "é" * 40000])
async def test_missing_or_oversized_response_is_charged_but_never_redispatched(text):
    identity, sdk = await seed(), client(text=text)
    await invoke(identity, sdk)
    with pytest.raises(ReservationReplayError):
        await invoke(identity, sdk)
    _, reservations, calls = await snapshot(identity)
    assert reservations[0].state == "consumed"
    assert calls[0].provider_usage["replay"]["unavailable"] == "missing_or_oversized_text"
    sdk.responses.create.assert_awaited_once()


async def unresolved_receipt(identity, *, success=False, proof=False):
    tenant, run = identity
    async with tenant_session(str(tenant)) as session:
        repo = BudgetReservationRepository(session, tenant)
        reservation = await repo.reserve(
            run_id=run,
            provider="internal",
            operation="model",
            request_fingerprint="receipt",
            estimated_cost_usd=Decimal("0.10"),
            search_calls=0,
            input_tokens=100,
            output_tokens=4096,
        )
        metadata = {
            "accounting": {
                "reservedInputTokens": 100,
                "reservedOutputTokens": 4096,
                "inputTokens": 5,
                "outputTokens": 8,
                "costUsd": "0.000006",
            }
        }
        if proof:
            metadata["nonexecution"] = {
                "version": "model-nonexecution-v1",
                "source": "model_boundary",
                "reason": "rejected_without_usage",
                "kind": "http_rejection",
                "statusCode": 429,
                "retryable": True,
            }
        session.add(
            ProviderCall(
                tenant_id=tenant,
                run_id=run,
                reservation_id=reservation.id,
                provider="internal",
                operation="model",
                request_fingerprint="receipt",
                request_schema_version="fixture",
                provider_usage=metadata,
                outcome="succeeded" if success else "failed" if proof else "uncertain",
                started_at=datetime.now(UTC) - timedelta(days=365),
                completed_at=datetime.now(UTC),
            )
        )
        await repo.transition(reservation.id, new_state="uncertain")
        return reservation.id


@pytest.mark.parametrize("release", [False, True])
async def test_proof_settlement_is_concurrent_idempotent_run_and_tenant_scoped(release):
    identity = await seed()
    tenant, run = identity
    reservation = await unresolved_receipt(identity, success=not release, proof=release)
    summaries = await accounting_ops.unresolved(tenant, run)
    assert summaries[0].nonexecution_proof_available is release
    results = await asyncio.gather(
        *(accounting_ops.reconcile(tenant, run, reservation, release=release) for _ in range(4))
    )
    assert results == ["released" if release else "consumed"] * 4
    usage, _, _ = await snapshot(identity)
    assert usage.reserved_estimated_cost_usd == 0
    assert (usage.input_tokens, usage.output_tokens) == ((0, 0) if release else (5, 8))
    assert usage.estimated_cost_usd == (0 if release else Decimal("0.000006"))
    for foreign_tenant, foreign_run in [(uuid.uuid4(), run), (tenant, uuid.uuid4())]:
        with pytest.raises(LookupError):
            await accounting_ops.reconcile(
                foreign_tenant, foreign_run, reservation, release=release
            )


async def test_old_uncertainty_and_provider_payload_are_not_release_proof():
    identity = await seed()
    tenant, run = identity
    reservation = await unresolved_receipt(identity)
    with pytest.raises(InvalidReservationTransitionError, match="proof missing"):
        await accounting_ops.reconcile(tenant, run, reservation, release=True)
    async with tenant_session(str(tenant)) as session:
        call = await session.scalar(select(ProviderCall).where(ProviderCall.run_id == run))
        call.provider_usage = {
            **call.provider_usage,
            "nonexecution": {
                "version": "model-nonexecution-v1",
                "source": "provider_payload",
                "reason": "rejected_without_usage",
                "retryable": True,
            },
        }
        call.outcome = "failed"
    with pytest.raises(InvalidReservationTransitionError):
        await accounting_ops.reconcile(tenant, run, reservation, release=True)
    usage, rows, _ = await snapshot(identity)
    assert rows[0].state == "uncertain" and usage.reserved_estimated_cost_usd == Decimal("0.10")


async def test_replay_cannot_bypass_actual_overspend(monkeypatch):
    identity, sdk = await seed(), client()
    sdk.responses.create.return_value.usage.input_tokens = 10_000_000
    with pytest.raises(BudgetExceededError):
        await invoke(identity, sdk)
    with pytest.raises(BudgetExceededError):
        await invoke(identity, sdk)
    sdk.responses.create.assert_awaited_once()


@pytest.mark.parametrize("state", ["reserved", "uncertain"])
@pytest.mark.parametrize("overspent", [False, True])
async def test_replay_settles_persisted_success_once_before_enforcing_budget(state, overspent):
    identity, sdk = await seed(), client()
    if overspent:
        sdk.responses.create.return_value.usage.input_tokens = 10_000_000
        with pytest.raises(BudgetExceededError):
            await invoke(identity, sdk)
    else:
        await invoke(identity, sdk)
    tenant, run = identity
    # Simulate a trusted receipt durably recovered independently of settlement.
    async with tenant_session(str(tenant)) as session:
        reservation = await session.scalar(
            select(ProviderCallReservation).where(ProviderCallReservation.run_id == run)
        )
        call = await session.scalar(select(ProviderCall).where(ProviderCall.run_id == run))
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run))
        accounting = call.provider_usage["accounting"]
        reservation.state = state
        usage.estimated_cost_usd = 0
        usage.reserved_estimated_cost_usd = reservation.reserved_estimated_cost_usd
        usage.input_tokens = accounting["reservedInputTokens"]
        usage.output_tokens = accounting["reservedOutputTokens"]
    for _ in range(2):
        if overspent:
            with pytest.raises(BudgetExceededError):
                await invoke(identity, sdk, role="writer")
        else:
            replay = await invoke(identity, sdk)
            assert replay.output_text == TEXT
        usage, reservations, _ = await snapshot(identity)
        assert reservations[0].state == "consumed" and usage.reserved_estimated_cost_usd == 0
        assert usage.input_tokens == (10_000_000 if overspent else 5)
        assert usage.output_tokens == 8
    sdk.responses.create.assert_awaited_once()


async def test_retry_after_restart_reuses_successful_later_attempt(monkeypatch):
    identity, sdk = await seed(), client()

    class Rejection(Exception):
        status_code = 429

    sdk.responses.create.side_effect = [Rejection(), sdk.responses.create.return_value]
    monkeypatch.setattr(model_budget, "retry_delay", AsyncMock())
    await invoke(identity, sdk, max_attempts=2)
    before, reservations, _ = await snapshot(identity)
    assert [row.state for row in reservations] == ["released", "consumed"]
    assert (await invoke(identity, sdk, max_attempts=3)).output_text == TEXT
    after, _, _ = await snapshot(identity)
    assert totals(before) == totals(after) and sdk.responses.create.await_count == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500])
async def test_permanent_or_ambiguous_errors_cannot_unlock_new_attempts(status):
    identity = await seed()

    class Failure(Exception):
        status_code = status

    sdk = client(error=Failure())
    with pytest.raises(Failure):
        await invoke(identity, sdk)
    with pytest.raises(ReservationReplayError):
        await invoke(identity, sdk)
    sdk.responses.create.assert_awaited_once()


async def test_ambiguous_timeout_persists_safe_failure_diagnostics_without_retry():
    identity = await seed()
    error = TimeoutError("private request content must not be persisted")
    sdk = client(error=error)

    with pytest.raises(TimeoutError):
        await invoke(identity, sdk, role="writer")
    with pytest.raises(ReservationReplayError):
        await invoke(identity, sdk, role="writer")

    _, reservations, calls = await snapshot(identity)
    assert len(reservations) == len(calls) == 1
    assert reservations[0].state == "uncertain"
    assert calls[0].outcome == "uncertain"
    failure = calls[0].provider_usage["failure"]
    assert failure == {
        "version": "model-failure-v1",
        "exceptionType": "TimeoutError",
        "statusCode": None,
        "outcome": "uncertain",
        "retryable": False,
    }
    assert "private request content" not in json.dumps(calls[0].provider_usage)
    sdk.responses.create.assert_awaited_once()


async def test_concurrent_successful_replay_is_read_only_accounting():
    identity, sdk = await seed(), client()
    await invoke(identity, sdk)
    before, _, _ = await snapshot(identity)
    replays = await asyncio.gather(*(invoke(identity, sdk) for _ in range(6)))
    after, reservations, calls = await snapshot(identity)
    assert all(response.output_text == TEXT for response in replays)
    assert totals(before) == totals(after) and len(reservations) == len(calls) == 1
    sdk.responses.create.assert_awaited_once()


async def test_missing_usage_replays_as_none_with_conservative_accounting():
    identity, sdk = await seed(), client()
    sdk.responses.create.return_value.usage = None
    await invoke(identity, sdk)
    before, _, _ = await snapshot(identity)
    replay = await invoke(identity, sdk)
    after, _, _ = await snapshot(identity)
    assert replay.usage is None and replay.output_text == TEXT
    assert totals(before) == totals(after) and after.output_tokens == 4096
    sdk.responses.create.assert_awaited_once()


@pytest.mark.parametrize("attempts", [True, 0, 4, 1.5])
async def test_invalid_attempt_policy_never_dispatches(attempts):
    sdk = client()
    with pytest.raises(ValueError, match="attempts"):
        await model_response(sdk, max_attempts=attempts)
    sdk.responses.create.assert_not_called()


def test_accounting_cli_accepts_only_record_ids_for_release():
    args = [
        "release",
        "--tenant-id",
        str(uuid.uuid4()),
        "--run-id",
        str(uuid.uuid4()),
        "--reservation-id",
        str(uuid.uuid4()),
    ]
    assert accounting_ops.parser().parse_args(args).action == "release"
    with pytest.raises(SystemExit):
        accounting_ops.parser().parse_args([*args, "--cost-usd", "0"])


async def test_existing_reservation_without_dispatch_receipt_fails_closed():
    identity, sdk = await seed(), client()
    tenant, run = identity
    request = {"model": "gpt-4o-mini", "input": "q", "max_output_tokens": 4096}
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    async with tenant_session(str(tenant)) as session:
        await BudgetReservationRepository(session, tenant).reserve(
            run_id=run,
            provider="internal",
            operation="model",
            request_fingerprint=fingerprint,
            estimated_cost_usd=Decimal("0.10"),
            search_calls=0,
        )
    with pytest.raises(ReservationReplayError, match="no dispatch evidence"):
        await invoke(identity, sdk)
    sdk.responses.create.assert_not_called()
