"""Non-enforcing, tenant-scoped snapshots of provisional mode-unit policy."""

from __future__ import annotations

import uuid
from time import monotonic
from typing import TypeGuard

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.billing.catalog import BILLING_CATALOG
from research_api.db.models import BillingShadowObservation
from research_api.mode_policy import ResearchMode
from research_api.telemetry import operation_event

SHADOW_POLICY_VERSION = "approved-mode-weights-1-2-4-v1"
PROVISIONAL_MODE_UNITS = BILLING_CATALOG.mode_unit_prices


def _is_research_mode(mode: str) -> TypeGuard[ResearchMode]:
    return mode in PROVISIONAL_MODE_UNITS


def build_shadow_observation(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    mode: str | None,
) -> BillingShadowObservation:
    """Create an immutable policy observation; it is never a quota decision."""
    if mode is None:
        return BillingShadowObservation(
            tenant_id=tenant_id,
            user_id=user_id,
            run_id=run_id,
            mode=None,
            decision_status="unpriced_legacy_mode",
            proposed_units=None,
            policy_version=None,
            catalog_version=None,
        )
    if not _is_research_mode(mode):
        raise ValueError("unsupported explicit mode")
    proposed_units = PROVISIONAL_MODE_UNITS[mode]
    return BillingShadowObservation(
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=run_id,
        mode=mode,
        decision_status="provisional",
        proposed_units=proposed_units,
        policy_version=SHADOW_POLICY_VERSION,
        catalog_version=BILLING_CATALOG.version,
    )


async def persist_shadow_observation(
    session: AsyncSession, observation: BillingShadowObservation
) -> bool:
    """Best-effort savepoint write; shadow-storage failures never reject a run."""
    started = monotonic()
    try:
        async with session.begin_nested():
            session.add(observation)
            await session.flush([observation])
    except SQLAlchemyError as error:
        operation_event(
            "billing.shadow_observation",
            started=started,
            outcome="failed",
            error=error,
            decisionStatus=observation.decision_status,
        )
        return False
    return True
