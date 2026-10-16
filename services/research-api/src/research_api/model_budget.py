"""Private model replay and accounting boundary (milestone 6 integration notes).

Graph recovery must keep the tenant/run and identical model request, including
ordered evidence, schema and instructions. Do not add crash timestamps or fresh
attempt IDs to the request. Only persisted successful output is reusable; an
ambiguous dispatch raises ReservationReplayError until trusted reconciliation.
The graph owner must implement checkpoint recovery and handle this error; this
module does not resume failed/terminal runs. Current ProviderCall JSONB suffices:
accounting, attemptPolicy, replay and nonexecution are server-owned metadata,
never browser receipts, API event payloads or global raw evidence storage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from research_api.db.models import Budget, ProviderCall, ResearchRun, UsageLedger
from research_api.db.session import tenant_session
from research_api.pricing import POLICY_MODEL_COST, PRICING_VERSION, model_rate
from research_api.providers.retry_policy import (
    pre_dispatch_failure,
    rejected_without_usage,
    retry_delay,
    retryable_openai,
)
from research_api.repositories.budgets import (
    BudgetExceededError,
    BudgetReservationRepository,
    ReservationReplayError,
    nonexecution_proof,
)
from research_api.telemetry import dependency_event

model_run: ContextVar[tuple[uuid.UUID, uuid.UUID] | None] = ContextVar("model_run", default=None)

REPLAY_VERSION = "model-text-v1"
MAX_REPLAY_BYTES = 65536


class ReplayInputTokenDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cached_tokens: int = Field(ge=0)


class ReplayUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    input_tokens_details: ReplayInputTokenDetails


class ReplayResponse(BaseModel):
    """Private text/usage projection compatible with graph SDK consumers.

    Recovery must re-enter the same tenant/run with the same request, not a new
    fingerprint or attempt number. Pending/uncertain dispatches fail closed;
    graph recovery must surface these for operator reconciliation. This boundary
    does not recover graph checkpoints or expose response metadata through APIs.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    output_text: str
    usage: ReplayUsage | None = None


def _replay_projection(response: Any, accounting: dict[str, Any]) -> dict[str, Any]:
    # Never serialize the SDK response wholesale: tool payloads, request echoes,
    # raw web bodies and headers are outside the replay contract. Preserve exact
    # structured text, including quotes; truncation would corrupt synthesis JSON.
    output = getattr(response, "output_text", None)
    if not isinstance(output, str) or len(output.encode("utf-8")) > MAX_REPLAY_BYTES:
        return {"version": REPLAY_VERSION, "unavailable": "missing_or_oversized_text"}
    usage = None
    if "inputTokens" in accounting:
        usage = ReplayUsage(
            input_tokens=accounting["inputTokens"],
            output_tokens=accounting["outputTokens"],
            total_tokens=accounting["inputTokens"] + accounting["outputTokens"],
            input_tokens_details=ReplayInputTokenDetails(
                cached_tokens=accounting.get("cachedInputTokens", 0)
            ),
        )
    return {
        "version": REPLAY_VERSION,
        "response": ReplayResponse(output_text=output, usage=usage).model_dump(),
    }


def _restore_response(call: ProviderCall) -> ReplayResponse:
    replay = (call.provider_usage or {}).get("replay", {})
    if not isinstance(replay, dict) or replay.get("version") != REPLAY_VERSION:
        raise ReservationReplayError("successful model receipt has no compatible replay output")
    try:
        response = ReplayResponse.model_validate(replay.get("response"))
        if len(response.output_text.encode("utf-8")) > MAX_REPLAY_BYTES:
            raise ValueError("oversized replay")
        return response
    except (ValidationError, ValueError) as error:
        raise ReservationReplayError(
            "successful model receipt has no valid replay output"
        ) from error


async def model_response(client: Any, *, max_attempts: int = 3, **request: Any) -> Any:
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError("model attempts must be between one and three")
    if isinstance(client, AsyncOpenAI) and client.max_retries != 0:
        raise ValueError("model boundary requires SDK retries disabled")
    identity = model_run.get()
    requested_output = request.get("max_output_tokens", 4096)
    if type(requested_output) is not int or requested_output <= 0:
        raise ValueError("model output allowance must be a positive integer")
    # The caller can explicitly choose a depth allowance; run-level caps still gate admission.
    output_bound = min(8192, requested_output)
    request = {**request, "max_output_tokens": output_bound}
    if identity is None:
        # Isolated callers have no run ledger. Production graph always sets it.
        return await client.responses.create(**request)
    tenant, run = identity
    # UTF-8 length is an admission heuristic, not a guaranteed provider-token bound.
    input_bound = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    rate = model_rate(str(request.get("model", "")))
    estimated = rate.cost(input_bound, output_bound) if rate else POLICY_MODEL_COST
    basis = PRICING_VERSION if rate else "policy-estimate-v1"

    attempt_limit = max_attempts
    for attempt in range(1, max_attempts + 1):
        if attempt > attempt_limit:
            raise ReservationReplayError("persisted model attempt policy exhausted")
        replay_result = None
        overspent = False
        async with tenant_session(str(tenant)) as session:
            active_run = await session.scalar(
                select(ResearchRun).where(
                    ResearchRun.tenant_id == tenant,
                    ResearchRun.id == run,
                )
            )
            if active_run is None:
                raise LookupError("research run missing")
            if active_run.cancellation_requested_at is not None or active_run.status in {
                "cancelled",
                "completed",
                "failed",
            }:
                raise asyncio.CancelledError
            reservation = await BudgetReservationRepository(session, tenant).reserve(
                run_id=run,
                provider="internal",
                operation="model",
                request_fingerprint=fingerprint,
                estimated_cost_usd=estimated,
                search_calls=0,
                attempt=attempt,
                input_tokens=input_bound,
                output_tokens=output_bound,
                require_existing_call=True,
            )
            existing = await session.scalar(
                select(ProviderCall).where(
                    ProviderCall.tenant_id == tenant,
                    ProviderCall.reservation_id == reservation.id,
                )
            )
            if existing is not None:
                if (
                    existing.run_id != run
                    or existing.provider != "internal"
                    or existing.operation != "model"
                    or existing.request_fingerprint != fingerprint
                ):
                    raise ReservationReplayError("model receipt identity mismatch")
                if existing.outcome == "succeeded" and existing.completed_at is not None:
                    replay_result = _restore_response(existing)
                    if reservation.state in {"reserved", "uncertain"}:
                        await BudgetReservationRepository(session, tenant).reconcile_from_receipt(
                            reservation.id
                        )
                    elif reservation.state != "consumed":
                        raise ReservationReplayError("success receipt conflicts with reservation")
                    usage = await session.scalar(
                        select(UsageLedger).where(
                            UsageLedger.tenant_id == tenant, UsageLedger.run_id == run
                        )
                    )
                    budget = await session.scalar(
                        select(Budget).where(Budget.tenant_id == tenant, Budget.run_id == run)
                    )
                    if usage is None or budget is None:
                        raise LookupError("model-call budget missing")
                    overspent = (
                        usage.input_tokens > budget.max_input_tokens
                        or usage.output_tokens > budget.max_output_tokens
                        or usage.estimated_cost_usd + usage.reserved_estimated_cost_usd
                        > budget.max_estimated_cost_usd
                    )
                else:
                    proof = nonexecution_proof(existing, reservation)
                    policy = (existing.provider_usage or {}).get("attemptPolicy", {})
                    ceiling = policy.get("maxAttempts", 1)
                    valid_policy = type(ceiling) is int and 1 <= ceiling <= 3
                    attempt_limit = min(attempt_limit, ceiling) if valid_policy else 1
                    if (
                        reservation.state == "released"
                        and proof is not None
                        and proof.get("retryable") is True
                        and valid_policy
                        and attempt < attempt_limit
                    ):
                        continue
                    raise ReservationReplayError("existing model attempt cannot be re-dispatched")
            else:
                if reservation.state != "reserved":
                    raise ReservationReplayError("existing model attempt cannot be re-dispatched")
                reservation_id = reservation.id
                accounting = {
                    "reservedInputTokens": input_bound,
                    "reservedOutputTokens": output_bound,
                    "pricingVersion": basis,
                    "model": str(request.get("model", "")),
                }
                session.add(
                    ProviderCall(
                        tenant_id=tenant,
                        run_id=run,
                        reservation_id=reservation_id,
                        provider="internal",
                        operation="model",
                        request_fingerprint=fingerprint,
                        request_schema_version="responses-2026-10-13",
                        provider_usage={
                            "accounting": accounting,
                            "attemptPolicy": {"maxAttempts": attempt_limit},
                        },
                        outcome="pending",
                        started_at=datetime.now(UTC),
                    )
                )
        if replay_result is not None:
            # Persist recovery settlement even when actual usage exceeds admission.
            if overspent:
                raise BudgetExceededError("actual model usage exceeded admission heuristic")
            return replay_result
        started = monotonic()
        try:
            response = await client.responses.create(**request)
        except BaseException as error:
            remote_ms = (monotonic() - started) * 1000
            state = "released" if rejected_without_usage(error) else "uncertain"
            async with tenant_session(str(tenant)) as session:
                call = await session.scalar(
                    select(ProviderCall).where(
                        ProviderCall.tenant_id == tenant,
                        ProviderCall.reservation_id == reservation_id,
                    )
                )
                if call is None:
                    raise LookupError("model call missing for reservation") from error
                call.outcome = "failed" if state == "released" else "uncertain"
                call.completed_at = datetime.now(UTC)
                if state == "released":
                    before_dispatch = pre_dispatch_failure(error)
                    call.provider_usage = {
                        **(call.provider_usage or {}),
                        "nonexecution": {
                            "version": "model-nonexecution-v1",
                            "source": "model_boundary",
                            "reason": "rejected_without_usage",
                            "kind": "pre_dispatch" if before_dispatch else "http_rejection",
                            "statusCode": (
                                None if before_dispatch else getattr(error, "status_code", None)
                            ),
                            "retryable": retryable_openai(error),
                        },
                    }
                await session.flush()
                await BudgetReservationRepository(session, tenant).transition(
                    reservation_id,
                    new_state=state,
                )
            dependency_event(
                provider="openai",
                operation="model",
                outcome=state,
                attempt=attempt,
                started=started,
                reason=type(error).__name__,
                remote_duration_ms=remote_ms,
            )
            if (
                state == "released"
                and isinstance(error, Exception)
                and retryable_openai(error)
                and attempt < attempt_limit
            ):
                await retry_delay(attempt)
                continue
            raise

        remote_ms = (monotonic() - started) * 1000
        actual = getattr(response, "usage", None)
        actual_cost: Decimal | None = None
        if actual is not None:
            try:
                input_tokens, output_tokens = actual.input_tokens, actual.output_tokens
                cached = (
                    getattr(getattr(actual, "input_tokens_details", None), "cached_tokens", 0) or 0
                )
                if (
                    any(type(count) is not int for count in (input_tokens, output_tokens, cached))
                    or min(input_tokens, output_tokens, cached) < 0
                    or cached > input_tokens
                ):
                    raise ValueError("invalid usage")
                accounting.update(
                    inputTokens=input_tokens, outputTokens=output_tokens, cachedInputTokens=cached
                )
                if rate:
                    actual_cost = rate.cost(input_tokens, output_tokens, cached)
            except (AttributeError, TypeError, ValueError):
                dependency_event(
                    provider="openai",
                    operation="accounting",
                    outcome="estimated",
                    attempt=attempt,
                    reason="invalid_usage",
                )
        accounting["costUsd"] = str(actual_cost if actual_cost is not None else estimated)
        accounting["usageBasis"] = "provider-usage" if "inputTokens" in accounting else "reserved"
        async with tenant_session(str(tenant)) as session:
            call = await session.scalar(
                select(ProviderCall).where(
                    ProviderCall.tenant_id == tenant,
                    ProviderCall.reservation_id == reservation_id,
                )
            )
            if call is None:
                raise LookupError("model call missing for reservation")
            call.provider_usage = {
                **(call.provider_usage or {}),
                "accounting": accounting,
                "replay": _replay_projection(response, accounting),
            }
            call.provider_request_id = getattr(response, "id", None)
            call.response_schema_version = "responses-2026-10-13"
            call.outcome, call.completed_at = "succeeded", datetime.now(UTC)
            await session.flush()
            await BudgetReservationRepository(session, tenant).transition(
                reservation_id,
                new_state="consumed",
                actual_cost_usd=actual_cost,
            )
            usage = await session.scalar(
                select(UsageLedger).where(
                    UsageLedger.tenant_id == tenant,
                    UsageLedger.run_id == run,
                )
            )
            budget = await session.scalar(
                select(Budget).where(
                    Budget.tenant_id == tenant,
                    Budget.run_id == run,
                )
            )
            if usage is None or budget is None:
                raise LookupError("model-call budget missing")
            overspent = (
                usage.input_tokens > budget.max_input_tokens
                or usage.output_tokens > budget.max_output_tokens
                or usage.estimated_cost_usd + usage.reserved_estimated_cost_usd
                > budget.max_estimated_cost_usd
            )
        dependency_event(
            provider="openai",
            operation="model",
            outcome="consumed",
            attempt=attempt,
            started=started,
            reason=basis,
            remote_duration_ms=remote_ms,
        )
        if overspent:
            # Commit real usage first. Failing now prevents any subsequent paid dispatch.
            raise BudgetExceededError("actual model usage exceeded admission heuristic")
        return response
    raise AssertionError("unreachable retry exit")
