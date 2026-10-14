"""Privileged server-side tool; no browser endpoint, receipt upload or age-based refunds."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from research_api.db.models import ProviderCall, ProviderCallReservation
from research_api.db.session import engine, tenant_session
from research_api.repositories.budgets import (
    BudgetReservationRepository,
    InvalidReservationTransitionError,
    nonexecution_proof,
)


class ReservationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    provider: str
    operation: str
    state: str
    reserved_cost_usd: Decimal
    reserved_search_calls: int
    receipt_available: bool
    nonexecution_proof_available: bool


async def unresolved(
    tenant: uuid.UUID, run: uuid.UUID, after: uuid.UUID | None = None
) -> list[ReservationSummary]:
    async with tenant_session(str(tenant)) as session:
        statement = (
            select(ProviderCallReservation, ProviderCall)
            .outerjoin(
                ProviderCall,
                (ProviderCall.reservation_id == ProviderCallReservation.id)
                & (ProviderCall.tenant_id == tenant),
            )
            .where(
                ProviderCallReservation.tenant_id == tenant,
                ProviderCallReservation.run_id == run,
                ProviderCallReservation.state.in_(["reserved", "uncertain"]),
            )
        )
        if after is not None:
            statement = statement.where(ProviderCallReservation.id > after)
        rows = (
            await session.execute(statement.order_by(ProviderCallReservation.id).limit(100))
        ).all()
        return [
            ReservationSummary(
                id=reservation.id,
                provider=reservation.provider,
                operation=reservation.operation,
                state=reservation.state,
                reserved_cost_usd=reservation.reserved_estimated_cost_usd,
                reserved_search_calls=reservation.reserved_search_calls,
                receipt_available=bool(call and call.outcome == "succeeded" and call.completed_at),
                nonexecution_proof_available=bool(
                    call and nonexecution_proof(call, reservation) is not None
                ),
            )
            for reservation, call in rows
        ]


async def reconcile(
    tenant: uuid.UUID, run: uuid.UUID, reservation: uuid.UUID, *, release: bool = False
) -> str:
    async with tenant_session(str(tenant)) as session:
        row = await session.scalar(
            select(ProviderCallReservation)
            .where(
                ProviderCallReservation.tenant_id == tenant,
                ProviderCallReservation.run_id == run,
                ProviderCallReservation.id == reservation,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise LookupError("reservation not found in requested tenant/run")
        repository = BudgetReservationRepository(session, tenant)
        result = (
            await repository.release_from_nonexecution_proof(reservation)
            if release
            else await repository.reconcile_from_receipt(reservation)
        )
        return result.state


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("action", choices=["list", "reconcile", "release"])
    command.add_argument("--tenant-id", type=uuid.UUID, required=True)
    command.add_argument("--run-id", type=uuid.UUID, required=True)
    command.add_argument("--reservation-id", type=uuid.UUID)
    command.add_argument(
        "--after-id", type=uuid.UUID, help="List cursor; pages contain at most 100 entries"
    )
    return command


async def main(args: argparse.Namespace) -> None:
    try:
        if args.action == "list":
            for row in await unresolved(args.tenant_id, args.run_id, args.after_id):
                print(row.model_dump_json())
        else:
            if args.reservation_id is None:
                raise ValueError("reconcile/release requires --reservation-id")
            state = await reconcile(
                args.tenant_id, args.run_id, args.reservation_id, release=args.action == "release"
            )
            print(state)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main(parser().parse_args()))
    except (LookupError, ValueError, InvalidReservationTransitionError) as error:
        raise SystemExit(str(error)) from None
