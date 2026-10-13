"""Run-scoped model-call reservations. Token bounds are conservative, not estimates."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextvars import ContextVar
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from research_api.db.models import Budget, UsageLedger
from research_api.db.session import tenant_session
from research_api.repositories.budgets import BudgetExceededError, BudgetReservationRepository

model_run: ContextVar[tuple[uuid.UUID, uuid.UUID] | None] = ContextVar("model_run", default=None)


async def model_response(client: Any, **request: Any) -> Any:
    identity = model_run.get()
    if identity is None:
        return await client.responses.create(**request)
    tenant, run = identity
    # Byte length upper-bounds byte-level tokenizer input, including the schema.
    input_bound = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    output_bound = 4096
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    async with tenant_session(str(tenant)) as session:
        repository = BudgetReservationRepository(session, tenant)
        reservation = await repository.reserve(
            run_id=run,
            provider="internal",
            operation="model",
            request_fingerprint=fingerprint,
            estimated_cost_usd=Decimal("0.10"),
            search_calls=0,
        )
        if reservation.state != "reserved":
            raise BudgetExceededError("a terminal model reservation cannot be re-dispatched")
        budget = await session.scalar(
            select(Budget).where(Budget.tenant_id == tenant, Budget.run_id == run)
        )
        usage = await session.scalar(
            select(UsageLedger)
            .where(UsageLedger.tenant_id == tenant, UsageLedger.run_id == run)
            .with_for_update()
        )
        if not budget or not usage:
            raise LookupError("model-call budget missing")
        if (
            usage.input_tokens + input_bound > budget.max_input_tokens
            or usage.output_tokens + output_bound > budget.max_output_tokens
        ):
            raise BudgetExceededError("model token budget exhausted")
        usage.input_tokens += input_bound
        usage.output_tokens += output_bound
        reservation_id = reservation.id
    try:
        response = await client.responses.create(**request, max_output_tokens=output_bound)
    except BaseException:
        async with tenant_session(str(tenant)) as session:
            await BudgetReservationRepository(session, tenant).transition(
                reservation_id, new_state="uncertain"
            )
        raise
    async with tenant_session(str(tenant)) as session:
        await BudgetReservationRepository(session, tenant).transition(
            reservation_id, new_state="consumed"
        )
        usage = await session.scalar(
            select(UsageLedger)
            .where(UsageLedger.tenant_id == tenant, UsageLedger.run_id == run)
            .with_for_update()
        )
        actual = getattr(response, "usage", None)
        if usage and actual:
            usage.input_tokens -= max(0, input_bound - int(actual.input_tokens))
            usage.output_tokens -= max(0, output_bound - int(actual.output_tokens))
    return response
