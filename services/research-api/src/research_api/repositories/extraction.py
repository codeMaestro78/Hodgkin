from __future__ import annotations

import asyncio
import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import Budget, ExtractionSlot, ResearchRun, Source
from research_api.research_limits import is_run_quick, run_source_limit


class ExtractionAdmissionRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session, self.tenant_id = session, tenant_id

    async def admit(
        self, *, run_id: uuid.UUID, urls: list[str], quick_mode: bool
    ) -> tuple[list[ExtractionSlot], list[Source]]:
        # All new-slot writers take this lock. Never hold it during provider I/O.
        run = await self.session.scalar(
            select(ResearchRun)
            .where(
                ResearchRun.tenant_id == self.tenant_id,
                ResearchRun.id == run_id,
            )
            # FOR NO KEY UPDATE serializes admissions but remains compatible
            # with KEY SHARE taken by concurrent reservation foreign keys.
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise LookupError("research run missing")
        if run.cancellation_requested_at or run.status in {"cancelled", "failed", "completed"}:
            raise asyncio.CancelledError
        budget = await self.session.scalar(
            select(Budget).where(
                Budget.tenant_id == self.tenant_id,
                Budget.run_id == run_id,
            )
        )
        if budget is None:
            raise LookupError("run budget missing")
        # Lazy import of pre-migration sources makes quota safe even when a
        # non-bypass migration principal could not perform a global backfill.
        sources = list(
            await self.session.scalars(
                select(Source)
                .where(
                    Source.tenant_id == self.tenant_id,
                    Source.run_id == run_id,
                )
                .order_by(Source.retrieved_at.desc())
            )
        )
        slots = {
            slot.canonical_url: slot
            for slot in await self.session.scalars(
                select(ExtractionSlot).where(
                    ExtractionSlot.tenant_id == self.tenant_id, ExtractionSlot.run_id == run_id
                )
            )
        }
        for source in sources:
            if source.canonical_url not in slots:
                slot = ExtractionSlot(
                    tenant_id=self.tenant_id,
                    run_id=run_id,
                    canonical_url=source.canonical_url,
                    url_fingerprint=hashlib.sha256(source.canonical_url.encode()).hexdigest(),
                    state="consumed",
                )
                self.session.add(slot)
                slots[source.canonical_url] = slot
            elif slots[source.canonical_url].state == "released":
                slots[source.canonical_url].state = "consumed"
        await self.session.flush()
        remaining = max(
            0,
            run_source_limit(budget, run.mode is None and (quick_mode or is_run_quick(run)))
            - sum(slot.state != "released" for slot in slots.values()),
        )
        cached = {source.canonical_url: source for source in reversed(sources)}
        admitted: list[ExtractionSlot] = []
        reused: list[Source] = []
        for url in dict.fromkeys(urls):
            if url in cached:
                reused.append(cached[url])
                continue
            pending_slot = slots.get(url)
            if pending_slot is not None and pending_slot.state != "released":
                continue
            if remaining <= 0:
                continue
            if pending_slot is None:
                pending_slot = ExtractionSlot(
                    tenant_id=self.tenant_id,
                    run_id=run_id,
                    canonical_url=url,
                    url_fingerprint=hashlib.sha256(url.encode()).hexdigest(),
                )
                self.session.add(pending_slot)
            pending_slot.state = "reserved"
            admitted.append(pending_slot)
            remaining -= 1
        return admitted, reused
