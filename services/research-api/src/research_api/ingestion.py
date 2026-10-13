from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from research_api.artifacts.normalization import canonicalize_url, normalize_text
from research_api.artifacts.store import ArtifactStore
from research_api.db.models import ProviderCall, ResearchRun
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.providers.tavily import (
    TAVILY_RESPONSE_SCHEMA_VERSION,
    ProviderRequest,
    TavilyAdapter,
    TavilyRequestError,
)
from research_api.reliability import content_signature
from research_api.repositories.budgets import BudgetReservationRepository
from research_api.repositories.sources import SourceRepository


class TavilyEvidenceIngestor:
    """One-worker Tavily Search/Extract ingestion boundary.

    Reservations are committed before network dispatch. Raw extracted content is written to object
    storage and only compact source metadata enters PostgreSQL.
    """

    def __init__(self, *, adapter: TavilyAdapter, artifact_store: ArtifactStore) -> None:
        self._adapter = adapter
        self._artifact_store = artifact_store

    async def ingest(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        sub_question_id: uuid.UUID | None,
        query: str,
        allowed_domains: list[str] | None = None,
        max_results: int = 6,
    ) -> list[uuid.UUID]:
        if max_results <= 0:
            return []
        search_request = self._adapter.search_request(
            query=query, max_results=max_results, allowed_domains=allowed_domains
        )
        search_reservation = await self._reserve(
            tenant_id=tenant_id,
            run_id=run_id,
            request=search_request,
            estimated_cost=Decimal("0.008"),
        )
        try:
            search_response = await self._adapter.search(search_request)
        except TavilyRequestError:
            await self._finalize(
                tenant_id=tenant_id,
                reservation_id=search_reservation,
                state="uncertain",
                response_schema_version=None,
                provider_request_id=None,
            )
            raise
        await self._finalize(
            tenant_id=tenant_id,
            run_id=run_id,
            reservation_id=search_reservation,
            state="consumed",
            response_schema_version=TAVILY_RESPONSE_SCHEMA_VERSION,
            provider_request_id=search_response.request_id,
            provider_usage=search_response.usage,
            response_body=search_response.model_dump(mode="json"),
        )

        if not search_response.results:
            return []
        extract_request = self._adapter.extract_request(
            urls=list(
                dict.fromkeys(canonicalize_url(result.url) for result in search_response.results)
            )[:max_results],
            query=query,
        )
        extract_reservation = await self._reserve(
            tenant_id=tenant_id,
            run_id=run_id,
            request=extract_request,
            estimated_cost=Decimal("0.008"),
        )
        try:
            extract_response = await self._adapter.extract(extract_request)
        except TavilyRequestError:
            await self._finalize(
                tenant_id=tenant_id,
                reservation_id=extract_reservation,
                state="uncertain",
                response_schema_version=None,
                provider_request_id=None,
            )
            raise
        await self._finalize(
            tenant_id=tenant_id,
            run_id=run_id,
            reservation_id=extract_reservation,
            state="consumed",
            response_schema_version=TAVILY_RESPONSE_SCHEMA_VERSION,
            provider_request_id=extract_response.request_id,
            provider_usage=extract_response.usage,
            response_body=extract_response.model_dump(mode="json"),
        )

        titles = {canonicalize_url(result.url): result.title for result in search_response.results}
        original_urls: dict[str, list[str]] = {}
        for result in search_response.results:
            urls = original_urls.setdefault(canonicalize_url(result.url), [])
            if result.url not in urls:
                urls.append(result.url)
        publication_dates = {}
        for result in search_response.results:
            if result.published_date:
                try:
                    parsed = datetime.fromisoformat(result.published_date.replace("Z", "+00:00"))
                    publication_dates[canonicalize_url(result.url)] = (
                        parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                    )
                except ValueError:
                    # Invalid dates remain unknown, never inferred from retrieval time.
                    pass
        source_ids: list[uuid.UUID] = []
        accepted_urls: set[str] = set()
        for extracted in extract_response.results:
            canonical_url = canonicalize_url(extracted.url)
            if canonical_url not in titles or canonical_url in accepted_urls:
                continue
            if len(source_ids) >= max_results:
                break
            normalized = normalize_text(extracted.raw_content).encode("utf-8")
            if not normalized:
                continue
            artifact = await self._artifact_store.put(
                tenant_id=tenant_id,
                run_id=run_id,
                content=normalized,
                media_type="text/markdown; charset=utf-8",
            )
            async with tenant_session(str(tenant_id)) as session:
                # Serialize only metadata persistence. Independent network work remains parallel;
                # identical URL/content results must not race the unique source constraint.
                await session.scalar(
                    select(ResearchRun)
                    .where(ResearchRun.tenant_id == tenant_id, ResearchRun.id == run_id)
                    .with_for_update()
                )
                source = await SourceRepository(session, tenant_id).upsert(
                    run_id=run_id,
                    sub_question_id=sub_question_id,
                    canonical_url=canonical_url,
                    title=titles.get(canonical_url, "Untitled source"),
                    provider="tavily",
                    source_class="unknown",
                    retrieved_at=datetime.now(UTC),
                    content_hash=artifact.content_hash,
                    artifact_ref=artifact.artifact_ref,
                    original_url=extracted.url,
                    original_urls=original_urls.get(canonical_url),
                    content_signature=content_signature(normalized.decode("utf-8")),
                    published_at=publication_dates.get(canonical_url),
                )
                await EventOutbox(session, tenant_id).append(
                    run_id=run_id,
                    event_type="source.discovered",
                    payload={
                        "source": {
                            "id": str(source.id),
                            "canonicalUrl": source.canonical_url,
                            "title": source.title,
                            "sourceClass": source.source_class,
                        }
                    },
                )
                source_ids.append(source.id)
                accepted_urls.add(canonical_url)
        return source_ids

    async def _reserve(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        request: ProviderRequest,
        estimated_cost: Decimal,
    ) -> uuid.UUID:
        async with tenant_session(str(tenant_id)) as session:
            reservation = await BudgetReservationRepository(session, tenant_id).reserve(
                run_id=run_id,
                provider="tavily",
                operation=request.operation,
                request_fingerprint=request.fingerprint,
                estimated_cost_usd=estimated_cost,
            )
            existing_call = await session.scalar(
                select(ProviderCall).where(
                    ProviderCall.tenant_id == tenant_id,
                    ProviderCall.reservation_id == reservation.id,
                )
            )
            if existing_call is not None:
                return reservation.id
            provider_call = ProviderCall(
                tenant_id=tenant_id,
                run_id=run_id,
                reservation_id=reservation.id,
                provider="tavily",
                operation=request.operation,
                request_fingerprint=request.fingerprint,
                request_schema_version=request.request_schema_version,
                outcome="pending",
                started_at=datetime.now(UTC),
            )
            session.add(provider_call)
            await session.flush()
            return reservation.id

    async def _finalize(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID | None = None,
        reservation_id: uuid.UUID,
        state: str,
        response_schema_version: str | None,
        provider_request_id: str | None,
        provider_usage: dict[str, object] | None = None,
        response_body: dict[str, object] | None = None,
    ) -> None:
        response_artifact_ref: str | None = None
        if response_body is not None:
            if run_id is None:
                raise ValueError("run_id is required when persisting a provider response")
            raw_response = json.dumps(
                response_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            artifact = await self._artifact_store.put(
                tenant_id=tenant_id,
                run_id=run_id,
                content=raw_response,
                media_type="application/json",
            )
            response_artifact_ref = artifact.artifact_ref
        async with tenant_session(str(tenant_id)) as session:
            await BudgetReservationRepository(session, tenant_id).transition(
                reservation_id, new_state=state
            )
            provider_call = await session.scalar(
                select(ProviderCall).where(
                    ProviderCall.tenant_id == tenant_id,
                    ProviderCall.reservation_id == reservation_id,
                )
            )
            if provider_call is None:
                raise LookupError("provider call missing for reservation")
            provider_call.response_schema_version = response_schema_version
            provider_call.provider_request_id = provider_request_id
            provider_call.provider_usage = provider_usage
            provider_call.response_artifact_ref = response_artifact_ref
            provider_call.outcome = "succeeded" if state == "consumed" else state
            provider_call.completed_at = datetime.now(UTC)
