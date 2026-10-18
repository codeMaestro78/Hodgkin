from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.artifacts.normalization import (
    canonicalize_url,
    normalize_text,
    search_result_identity_url,
)
from research_api.artifacts.store import ArtifactStore
from research_api.db.models import (
    Budget,
    ExtractionSlot,
    ProviderCall,
    ProviderCallReservation,
    ResearchRun,
    Source,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.pricing import SERPER_SEARCH_POLICY_COST
from research_api.providers.candidate_screening import screen_openalex_candidates
from research_api.providers.openalex import (
    MAX_PAGE_SIZE as OPENALEX_MAX_PAGE_SIZE,
)
from research_api.providers.openalex import (
    OPENALEX_REQUEST_SCHEMA_VERSION,
    OPENALEX_RESPONSE_SCHEMA_VERSION,
    OpenAlexAdapter,
    OpenAlexCancelledAfterDispatch,
    OpenAlexCancelledBeforeDispatch,
    OpenAlexRequestError,
)
from research_api.providers.serper import (
    SERPER_RESPONSE_SCHEMA_VERSION,
    SerperAdapter,
    SerperCancelled,
    SerperRequestError,
)
from research_api.providers.tavily import (
    TAVILY_RESPONSE_SCHEMA_VERSION,
    ExtractResponse,
    ProviderRequest,
    SearchResponse,
    TavilyAdapter,
    TavilyCancelledBeforeDispatch,
    TavilyRequestError,
)
from research_api.reliability import content_signature
from research_api.repositories.budgets import BudgetReservationRepository, ReservationReplayError
from research_api.repositories.extraction import ExtractionAdmissionRepository
from research_api.repositories.source_relationships import persist_source_relationships
from research_api.repositories.sources import SourceRepository
from research_api.research_limits import run_source_limit
from research_api.retrieval_accounting import search_provider_usage
from research_api.source_identity import SourceIdentity, map_source_identity
from research_api.telemetry import dependency_event, operation_event

_METADATA_BATCH_SIZE = 8
_ARTIFACT_WRITE_CONCURRENCY = 3


class ProviderRecoveryNeededError(ReservationReplayError):
    """A durable provider attempt cannot safely be replayed or dispatched again."""


@dataclass(frozen=True)
class _PreparedSource:
    canonical_url: str
    original_url: str
    content_hash: str
    artifact_ref: str
    signature: list[str]
    provider: str = "tavily"
    source_class: str = "unknown"


class TavilyEvidenceIngestor:
    """One-worker discovery/Tavily Extract ingestion boundary.

    Reservations are committed before network dispatch. Raw extracted content is written to object
    storage and only compact source metadata enters PostgreSQL.
    """

    def __init__(
        self,
        *,
        adapter: TavilyAdapter,
        artifact_store: ArtifactStore,
        discovery_adapter: SerperAdapter | None = None,
        academic_adapter: OpenAlexAdapter | None = None,
    ) -> None:
        self._adapter = adapter
        self._artifact_store = artifact_store
        self._discovery_adapter = discovery_adapter
        self._academic_adapter = academic_adapter

    def _request_provider(self, request: ProviderRequest) -> str:
        if (
            request.operation == "search"
            and getattr(request, "request_schema_version", None) == OPENALEX_REQUEST_SCHEMA_VERSION
        ):
            return "openalex"
        return "serper" if request.operation == "search" and self._discovery_adapter else "tavily"

    def _response_version(self, request: ProviderRequest) -> str:
        return {
            "openalex": OPENALEX_RESPONSE_SCHEMA_VERSION,
            "serper": SERPER_RESPONSE_SCHEMA_VERSION,
            "tavily": TAVILY_RESPONSE_SCHEMA_VERSION,
        }[self._request_provider(request)]

    async def ingest(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        sub_question_id: uuid.UUID | None,
        query: str,
        source_classes: list[str] | None = None,
        allowed_domains: list[str] | None = None,
        max_results: int = 6,
        quick_mode: bool = False,
    ) -> list[uuid.UUID]:
        if max_results <= 0:
            return []
        await self._check_cancelled(tenant_id, run_id)
        if self._academic_adapter is not None and "academic" in (source_classes or []):
            search_request = self._academic_adapter.search_request(
                query=query,
                per_page=OPENALEX_MAX_PAGE_SIZE,
                selection_limit=min(max_results, OPENALEX_MAX_PAGE_SIZE),
            )
        else:
            search_adapter = self._discovery_adapter or self._adapter
            search_request = search_adapter.search_request(
                query=query, max_results=max_results, allowed_domains=allowed_domains
            )
        replayed_search = await self._replay_response(
            tenant_id=tenant_id, run_id=run_id, request=search_request
        )
        if replayed_search is not None:
            if not isinstance(replayed_search, SearchResponse):
                raise ProviderRecoveryNeededError("recovery-needed: search receipt type mismatch")
            search_response = replayed_search
        else:
            search_response = await self._search_fresh(
                tenant_id=tenant_id, run_id=run_id, request=search_request
            )

        if not search_response.results:
            return []
        return await self._ingest_search_results(
            tenant_id=tenant_id,
            run_id=run_id,
            sub_question_id=sub_question_id,
            query=query,
            search_response=search_response,
            max_results=max_results,
            quick_mode=quick_mode,
            recovery=replayed_search is not None,
        )

    async def _search_fresh(
        self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, request: ProviderRequest
    ) -> SearchResponse:
        try:
            search_reservation = await self._reserve(
                tenant_id=tenant_id,
                run_id=run_id,
                request=request,
                estimated_cost=(
                    SERPER_SEARCH_POLICY_COST
                    if self._request_provider(request) == "serper"
                    else Decimal("0.001")
                    if self._request_provider(request) == "openalex"
                    else Decimal("0.008")
                ),
            )
        except ReservationReplayError:
            # A concurrent owner may have committed between the replay lookup
            # and reservation. Its attempt is never permission to redispatch.
            replay = await self._replay_response(
                tenant_id=tenant_id, run_id=run_id, request=request
            )
            if isinstance(replay, SearchResponse):
                return replay
            raise ProviderRecoveryNeededError(
                "recovery-needed: concurrent search receipt missing"
            ) from None
        try:
            if self._request_provider(request) == "openalex":
                if self._academic_adapter is None:
                    raise ProviderRecoveryNeededError("pinned OpenAlex adapter is unavailable")
                openalex_result = await self._academic_adapter.search(
                    request,
                    before_attempt=lambda: self._check_cancelled(tenant_id, run_id),
                )
                search_response = screen_openalex_candidates(
                    openalex_result.candidates,
                    query=request.payload["search"],
                    max_results=request.payload["selection_limit"],
                    reported_cost_usd=openalex_result.reported_cost_usd,
                    index_total_count=openalex_result.total_count,
                )
                search_response = search_response.model_copy(
                    update={
                        "usage": {
                            **(search_response.usage or {}),
                            "provider_attempt_count": openalex_result.attempt_count,
                        }
                    }
                )
            else:
                search_response = await (self._discovery_adapter or self._adapter).search(
                    request,
                    before_attempt=lambda: self._check_cancelled(tenant_id, run_id),
                )
        except BaseException as error:
            await self._finalize(
                tenant_id=tenant_id,
                reservation_id=search_reservation,
                state=error.outcome
                if isinstance(
                    error,
                    (
                        TavilyRequestError,
                        TavilyCancelledBeforeDispatch,
                        SerperRequestError,
                        SerperCancelled,
                        OpenAlexCancelledAfterDispatch,
                        OpenAlexRequestError,
                        OpenAlexCancelledBeforeDispatch,
                    ),
                )
                else "uncertain",
                response_schema_version=None,
                provider_request_id=None,
                provider_usage=(
                    {"provider_attempt_count": error.attempt_count}
                    if isinstance(
                        error,
                        (
                            OpenAlexRequestError,
                            OpenAlexCancelledBeforeDispatch,
                            OpenAlexCancelledAfterDispatch,
                        ),
                    )
                    else None
                ),
            )
            raise
        await self._finalize(
            tenant_id=tenant_id,
            run_id=run_id,
            reservation_id=search_reservation,
            state="consumed",
            response_schema_version=self._response_version(request),
            provider_request_id=search_response.request_id,
            provider_usage=search_provider_usage(
                provider=self._request_provider(request),
                response=search_response.model_dump(mode="json"),
            ),
            response_body=search_response.model_dump(mode="json"),
            actual_cost_usd=(
                Decimal(str(search_response.usage["reported_cost_usd"]))
                if self._request_provider(request) == "openalex"
                and isinstance(search_response.usage, dict)
                and isinstance(search_response.usage.get("reported_cost_usd"), (int, float))
                else None
            ),
        )

        if self._request_provider(request) in {"serper", "openalex"}:
            # Do not pay for extraction until the exact candidate catalogue and
            # shortlist have a durable, hash-checked receipt. Storage failures
            # retain the consumed call; recovery never guesses or re-searches.
            replay = await self._replay_response(
                tenant_id=tenant_id, run_id=run_id, request=request
            )
            if not isinstance(replay, SearchResponse):
                raise ProviderRecoveryNeededError("recovery-needed: shortlist receipt missing")
            return replay
        return search_response

    async def _ingest_search_results(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        sub_question_id: uuid.UUID | None,
        query: str,
        search_response: SearchResponse,
        max_results: int,
        quick_mode: bool,
        recovery: bool = False,
    ) -> list[uuid.UUID]:
        titles: dict[str, str] = {}
        original_urls: dict[str, list[str]] = {}
        source_details: dict[str, dict[str, str]] = {}
        publication_dates = {}
        selected_url_by_identity: dict[str, str] = {}
        for result in search_response.results:
            try:
                canonical_url = canonicalize_url(result.url)
            except (ValueError, UnicodeError):
                dependency_event(
                    provider="tavily", operation="source", outcome="rejected", reason="invalid_url"
                )
                continue
            try:
                identity_url = search_result_identity_url(result.url)
            except (ValueError, UnicodeError):
                continue
            selected_url = selected_url_by_identity.get(identity_url)
            if selected_url is not None:
                urls = original_urls.setdefault(selected_url, [])
                if result.url not in urls:
                    urls.append(result.url)
                continue
            if canonical_url not in titles and len(titles) >= max_results:
                continue
            selected_url_by_identity[identity_url] = canonical_url
            titles[canonical_url] = result.title
            result_extra = getattr(result, "model_extra", None) or {}
            if result_extra.get("provider") == "openalex":
                source_details[canonical_url] = {
                    "provider": "openalex",
                    "source_class": "academic",
                }
            urls = original_urls.setdefault(canonical_url, [])
            if result.url not in urls:
                urls.append(result.url)
            if result.published_date:
                try:
                    parsed = datetime.fromisoformat(result.published_date.replace("Z", "+00:00"))
                    publication_dates[canonical_url] = (
                        parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                    )
                except ValueError:
                    pass
        if not titles:
            return []
        await self._check_cancelled(tenant_id, run_id)
        admission_started = monotonic()
        (
            extract_request,
            extract_reservation,
            cached_ids,
            replay_extract,
        ) = await self._admit_extraction(
            tenant_id=tenant_id,
            run_id=run_id,
            sub_question_id=sub_question_id,
            query=query,
            titles=titles,
            original_urls=original_urls,
            quick_mode=quick_mode,
            recovery=recovery,
        )
        operation_event(
            "research.extract.admission",
            started=admission_started,
            candidateCount=len(titles),
            admitted=extract_request is not None,
        )
        if extract_request is None or extract_reservation is None:
            dependency_event(
                provider="tavily",
                operation="admission",
                outcome="not_dispatched",
                reason="cached_pending_or_quota_full",
            )
            return cached_ids
        admitted_urls = set(extract_request.payload["urls"])
        if replay_extract:
            replay = await self._replay_response(
                tenant_id=tenant_id, run_id=run_id, request=extract_request
            )
            if not isinstance(replay, ExtractResponse):
                raise ProviderRecoveryNeededError("recovery-needed: extraction receipt missing")
            extract_response = replay
        else:
            extract_response = await self._extract_fresh(
                tenant_id=tenant_id,
                run_id=run_id,
                request=extract_request,
                reservation_id=extract_reservation,
            )

        return await self._ingest_extract_results(
            tenant_id=tenant_id,
            run_id=run_id,
            sub_question_id=sub_question_id,
            extract_response=extract_response,
            admitted_urls=admitted_urls,
            cached_ids=cached_ids,
            titles=titles,
            original_urls=original_urls,
            publication_dates=publication_dates,
            source_details=source_details,
            max_results=max_results,
            quick_mode=quick_mode,
        )

    async def _extract_fresh(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        request: ProviderRequest,
        reservation_id: uuid.UUID,
    ) -> ExtractResponse:
        try:
            extract_response = await self._adapter.extract(
                request,
                before_attempt=lambda: self._check_cancelled(tenant_id, run_id),
            )
        except BaseException as error:
            await self._finalize(
                tenant_id=tenant_id,
                reservation_id=reservation_id,
                state=error.outcome
                if isinstance(error, (TavilyRequestError, TavilyCancelledBeforeDispatch))
                else "uncertain",
                response_schema_version=None,
                provider_request_id=None,
            )
            raise
        await self._finalize(
            tenant_id=tenant_id,
            run_id=run_id,
            reservation_id=reservation_id,
            state="consumed",
            response_schema_version=TAVILY_RESPONSE_SCHEMA_VERSION,
            provider_request_id=extract_response.request_id,
            provider_usage=extract_response.usage,
            response_body=extract_response.model_dump(mode="json"),
        )
        return extract_response

    async def _ingest_extract_results(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        sub_question_id: uuid.UUID | None,
        extract_response: ExtractResponse,
        admitted_urls: set[str],
        cached_ids: list[uuid.UUID],
        titles: dict[str, str],
        original_urls: dict[str, list[str]],
        publication_dates: dict[str, datetime],
        source_details: dict[str, dict[str, str]],
        max_results: int,
        quick_mode: bool,
    ) -> list[uuid.UUID]:
        source_ids: list[uuid.UUID] = cached_ids
        accepted_urls: set[str] = set()
        prepared: list[_PreparedSource] = []
        pending: list[tuple[str, str, bytes]] = []
        pending_urls: set[str] = set()

        async def persist_batch() -> None:
            started = monotonic()
            source_ids.extend(
                await self._persist_sources(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    sub_question_id=sub_question_id,
                    prepared=prepared,
                    titles=titles,
                    original_urls=original_urls,
                    publication_dates=publication_dates,
                    quick_mode=quick_mode,
                )
            )
            prepared.clear()
            operation_event(
                "research.source.persistence", started=started, sourceCount=len(source_ids)
            )

        async def flush_artifacts() -> None:
            if not pending:
                return
            started = monotonic()

            async def store_one(
                url: str, original_url: str, content: bytes
            ) -> _PreparedSource | None:
                try:
                    artifact = await self._artifact_store.put(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        content=content,
                        media_type="text/markdown; charset=utf-8",
                    )
                except Exception:
                    dependency_event(
                        provider="tavily",
                        operation="source",
                        outcome="failed",
                        reason="artifact_storage_failed",
                    )
                    return None
                return _PreparedSource(
                    canonical_url=url,
                    original_url=original_url,
                    content_hash=artifact.content_hash,
                    artifact_ref=artifact.artifact_ref,
                    signature=content_signature(content.decode("utf-8")),
                    provider=source_details.get(url, {}).get("provider", "tavily"),
                    source_class=source_details.get(url, {}).get("source_class", "unknown"),
                )

            writes = [
                asyncio.create_task(store_one(url, original_url, content))
                for url, original_url, content in pending
            ]
            try:
                stored = await asyncio.gather(*writes)
            except BaseException:
                for write in writes:
                    write.cancel()
                await asyncio.gather(*writes, return_exceptions=True)
                raise
            operation_event(
                "research.source.artifacts",
                started=started,
                attempted=len(pending),
                stored=sum(item is not None for item in stored),
            )
            pending.clear()
            pending_urls.clear()
            for item in stored:
                if item is None:
                    continue
                prepared.append(item)
                accepted_urls.add(item.canonical_url)
                if len(prepared) == _METADATA_BATCH_SIZE:
                    await persist_batch()

        for _failure in getattr(extract_response, "failed_results", []):
            dependency_event(
                provider="tavily", operation="source", outcome="failed", reason="extraction_failed"
            )
        for extracted in extract_response.results:
            try:
                canonical_url = canonicalize_url(extracted.url)
            except (ValueError, UnicodeError):
                dependency_event(
                    provider="tavily", operation="source", outcome="rejected", reason="invalid_url"
                )
                continue
            if (
                canonical_url not in admitted_urls
                or canonical_url in accepted_urls
                or canonical_url in pending_urls
            ):
                dependency_event(
                    provider="tavily",
                    operation="source",
                    outcome="rejected",
                    reason="unsolicited_or_duplicate",
                )
                continue
            if len(source_ids) + len(prepared) + len(pending) >= max_results:
                await flush_artifacts()
                if len(source_ids) + len(prepared) >= max_results:
                    break
            normalized = normalize_text(extracted.raw_content).encode("utf-8")
            if not normalized:
                dependency_event(
                    provider="tavily",
                    operation="source",
                    outcome="rejected",
                    reason="empty_content",
                )
                continue
            await self._check_cancelled(tenant_id, run_id)
            pending.append((canonical_url, extracted.url, normalized))
            pending_urls.add(canonical_url)
            # Complete each committed metadata batch before scheduling writes
            # for the next one. Cancellation in a later batch must not erase
            # eight already accepted sources from the durable run.
            if len(pending) >= min(
                _ARTIFACT_WRITE_CONCURRENCY, _METADATA_BATCH_SIZE - len(prepared)
            ):
                await flush_artifacts()
        await flush_artifacts()
        if prepared:
            await persist_batch()
        return source_ids

    async def _persist_sources(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        sub_question_id: uuid.UUID | None,
        prepared: list[_PreparedSource],
        titles: dict[str, str],
        original_urls: dict[str, list[str]],
        publication_dates: dict[str, datetime],
        quick_mode: bool,
    ) -> list[uuid.UUID]:
        """Commit at most eight sources; isolate integrity failures with their events.

        Artifacts are already written. Paid settlement and extraction slots are
        independent of metadata success, and are never refunded here.
        """
        if len(prepared) > _METADATA_BATCH_SIZE:
            raise ValueError("metadata batch exceeds transaction bound")
        ids: list[uuid.UUID] = []
        async with tenant_session(str(tenant_id)) as session:
            # NO KEY UPDATE still serializes metadata/admission writers, while
            # allowing concurrent FK KEY SHARE locks from accounting writes.
            run = await session.scalar(
                select(ResearchRun)
                .where(ResearchRun.tenant_id == tenant_id, ResearchRun.id == run_id)
                .with_for_update(key_share=True)
            )
            if run is None:
                raise LookupError("research run missing")
            if run.status in {"cancelled", "failed", "completed"} or run.cancellation_requested_at:
                raise asyncio.CancelledError
            budget = await session.scalar(
                select(Budget).where(Budget.tenant_id == tenant_id, Budget.run_id == run_id)
            )
            if budget is None:
                raise LookupError("run budget missing")
            ceiling = run_source_limit(budget, quick_mode)
            count = (
                await session.scalar(
                    select(func.count())
                    .select_from(Source)
                    .where(Source.tenant_id == tenant_id, Source.run_id == run_id)
                )
                or 0
            )
            repository = SourceRepository(session, tenant_id)
            existing = await repository.find_existing(
                run_id=run_id,
                identities=[(item.canonical_url, item.content_hash) for item in prepared],
            )
            observed_identities: dict[uuid.UUID, SourceIdentity] = {}
            for item in prepared:
                key = (item.canonical_url, item.content_hash)
                previous = existing.get(key)
                if count >= ceiling and previous is None:
                    dependency_event(
                        provider="tavily",
                        operation="source",
                        outcome="rejected",
                        reason="source_ceiling",
                    )
                    continue
                try:
                    async with session.begin_nested():
                        source = await repository.upsert(
                            run_id=run_id,
                            sub_question_id=sub_question_id,
                            canonical_url=item.canonical_url,
                            title=titles.get(item.canonical_url, "Untitled source"),
                            provider=item.provider,
                            source_class=item.source_class,
                            retrieved_at=datetime.now(UTC),
                            content_hash=item.content_hash,
                            artifact_ref=item.artifact_ref,
                            original_url=item.original_url,
                            original_urls=original_urls.get(item.canonical_url),
                            content_signature=item.signature,
                            published_at=publication_dates.get(item.canonical_url),
                            existing_source=previous,
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
                except IntegrityError:
                    dependency_event(
                        provider="tavily",
                        operation="source",
                        outcome="failed",
                        reason="metadata_integrity_failed",
                    )
                    continue
                ids.append(source.id)
                existing[key] = source
                if previous is None:
                    count += 1
                    if run.mode is not None:
                        # These are observed discovery/extraction URLs for this
                        # newly persisted source. Tavily supplies no verified
                        # publisher/owner metadata here; never infer it from host,
                        # title, page references, or the planner's desired class.
                        observed_identities[source.id] = map_source_identity(
                            canonical_url=item.canonical_url,
                            observed_urls=[
                                item.original_url,
                                *original_urls.get(item.canonical_url, []),
                            ],
                        )
            if run.mode is not None and ids:
                # Same outer transaction and run lock as source/event persistence.
                # Failure rolls back this batch; paid provider settlement remains
                # in its existing, separate transaction. Reused rows are not
                # identity-backfilled, and null-mode runs take the legacy path.
                await persist_source_relationships(
                    session, tenant_id, run_id, observed_identities=observed_identities
                )
        # IDs escape only after the outer commit succeeds. Cancellation and
        # infrastructure/commit failures propagate, rolling back this batch.
        return ids

    async def _admit_extraction(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        sub_question_id: uuid.UUID | None,
        query: str,
        titles: dict[str, str],
        original_urls: dict[str, list[str]],
        quick_mode: bool,
        recovery: bool = False,
    ) -> tuple[ProviderRequest | None, uuid.UUID | None, list[uuid.UUID], bool]:
        async with tenant_session(str(tenant_id)) as session:
            slots, cached = await ExtractionAdmissionRepository(session, tenant_id).admit(
                run_id=run_id,
                urls=list(titles),
                quick_mode=quick_mode,
            )
            ids: list[uuid.UUID] = []
            cached_urls = {source.canonical_url for source in cached}
            for source in cached:
                try:
                    async with session.begin_nested():
                        reused = await SourceRepository(session, tenant_id).upsert(
                            run_id=run_id,
                            sub_question_id=sub_question_id,
                            canonical_url=source.canonical_url,
                            title=source.title,
                            provider=source.provider,
                            source_class=source.source_class,
                            retrieved_at=source.retrieved_at,
                            content_hash=source.content_hash,
                            artifact_ref=source.artifact_ref,
                            original_urls=original_urls.get(source.canonical_url),
                            existing_source=source,
                        )
                        await session.flush()
                except IntegrityError:
                    dependency_event(
                        provider="tavily",
                        operation="source",
                        outcome="failed",
                        reason="metadata_integrity_failed",
                    )
                    continue
                ids.append(reused.id)
            missing = set(titles) - cached_urls - {slot.canonical_url for slot in slots}
            blocked = (
                list(
                    await session.scalars(
                        select(ExtractionSlot).where(
                            ExtractionSlot.tenant_id == tenant_id,
                            ExtractionSlot.run_id == run_id,
                            ExtractionSlot.canonical_url.in_(missing),
                            ExtractionSlot.state != "released",
                        )
                    )
                )
                if missing
                else []
            )
            if blocked and recovery:
                reservations = {slot.reservation_id for slot in blocked}
                if slots or len(reservations) != 1 or None in reservations:
                    raise ProviderRecoveryNeededError(
                        "recovery-needed: extraction spans multiple or unbound attempts"
                    )
                reservation_id = blocked[0].reservation_id
                urls = list(
                    await session.scalars(
                        select(ExtractionSlot.canonical_url).where(
                            ExtractionSlot.tenant_id == tenant_id,
                            ExtractionSlot.run_id == run_id,
                            ExtractionSlot.reservation_id == reservation_id,
                        )
                    )
                )
                if not urls or not set(urls).issubset(titles):
                    raise ProviderRecoveryNeededError(
                        "recovery-needed: extraction request cannot be reconstructed exactly"
                    )
                request = self._adapter.extract_request(urls=urls, query=query)
                reservation = await session.scalar(
                    select(ProviderCallReservation).where(
                        ProviderCallReservation.tenant_id == tenant_id,
                        ProviderCallReservation.run_id == run_id,
                        ProviderCallReservation.id == reservation_id,
                    )
                )
                if (
                    reservation is None
                    or reservation.provider != "tavily"
                    or reservation.operation != "extract"
                    or reservation.request_fingerprint != request.fingerprint
                ):
                    raise ProviderRecoveryNeededError(
                        "recovery-needed: reconstructed extraction fingerprint mismatch"
                    )
                # Replay the whole receipt; the source repository safely reuses
                # already persisted siblings without double-counting ceilings.
                # Preserve cached discoveries outside this original paid batch.
                # Cached siblings inside it are returned by receipt ingestion,
                # not counted twice against max_results while replaying.
                outside_batch = {source.id for source in cached if source.canonical_url not in urls}
                return request, reservation_id, [id_ for id_ in ids if id_ in outside_batch], True
            if not slots:
                return None, None, ids, False
            request = self._adapter.extract_request(
                urls=[slot.canonical_url for slot in slots], query=query
            )
            reservation_id = await self._reserve_in_session(
                session,
                tenant_id=tenant_id,
                run_id=run_id,
                request=request,
                estimated_cost=Decimal("0.008"),
            )
            for slot in slots:
                slot.reservation_id = reservation_id
            return request, reservation_id, ids, False

    async def _replay_response(
        self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, request: ProviderRequest
    ) -> SearchResponse | ExtractResponse | None:
        """Replay only a tenant/run/request-bound successful, validated receipt.

        Receipt reads are outside transactions. Unresolved/missing/corrupt
        receipts fail closed without dispatch or speculative refunds.
        """
        async with tenant_session(str(tenant_id)) as session:
            row = (
                await session.execute(
                    select(ProviderCallReservation, ProviderCall)
                    .outerjoin(
                        ProviderCall,
                        (
                            (ProviderCall.tenant_id == ProviderCallReservation.tenant_id)
                            & (ProviderCall.reservation_id == ProviderCallReservation.id)
                        ),
                    )
                    .where(
                        ProviderCallReservation.tenant_id == tenant_id,
                        ProviderCallReservation.run_id == run_id,
                        ProviderCallReservation.request_fingerprint == request.fingerprint,
                        ProviderCallReservation.attempt == 1,
                    )
                )
            ).first()
            if row is None:
                return None
            reservation, call = row
            if (
                call is None
                or reservation.provider != self._request_provider(request)
                or reservation.operation != request.operation
                or reservation.state not in {"consumed", "reserved", "uncertain"}
                or call.run_id != run_id
                or call.provider != self._request_provider(request)
                or call.operation != request.operation
                or call.request_fingerprint != request.fingerprint
                or call.request_schema_version != request.request_schema_version
                or call.response_schema_version != self._response_version(request)
                or call.outcome != "succeeded"
                or call.completed_at is None
                or not call.response_artifact_ref
            ):
                raise ProviderRecoveryNeededError(
                    "recovery-needed: trusted provider receipt missing"
                )
            reference = call.response_artifact_ref
            reservation_id, state = reservation.id, reservation.state
        prefix = f"tenants/{tenant_id}/runs/{run_id}/sha256/"
        if not reference.startswith(prefix):
            raise ProviderRecoveryNeededError("recovery-needed: provider receipt scope mismatch")
        try:
            raw = await self._artifact_store.get_for_verification(artifact_ref=reference)
            if reference != prefix + hashlib.sha256(raw).hexdigest():
                raise ValueError("provider receipt digest mismatch")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or "results" not in payload:
                raise ValueError("provider receipt results missing")
            response: SearchResponse | ExtractResponse
            if request.operation == "search":
                response = SearchResponse.model_validate(payload)
            elif request.operation == "extract":
                response = ExtractResponse.model_validate(payload)
            else:
                raise ValueError("unsupported provider receipt operation")
        except Exception as error:
            raise ProviderRecoveryNeededError(
                "recovery-needed: provider receipt unreadable"
            ) from error
        if state != "consumed":
            async with tenant_session(str(tenant_id)) as session:
                await BudgetReservationRepository(session, tenant_id).reconcile_from_receipt(
                    reservation_id
                )
                await session.execute(
                    update(ExtractionSlot)
                    .where(
                        ExtractionSlot.tenant_id == tenant_id,
                        ExtractionSlot.run_id == run_id,
                        ExtractionSlot.reservation_id == reservation_id,
                        ExtractionSlot.state.in_(["reserved", "uncertain"]),
                    )
                    .values(state="consumed")
                )
        return response

    @staticmethod
    async def _check_cancelled(tenant_id: uuid.UUID, run_id: uuid.UUID) -> None:
        async with tenant_session(str(tenant_id)) as session:
            run = await session.scalar(
                select(ResearchRun).where(
                    ResearchRun.tenant_id == tenant_id,
                    ResearchRun.id == run_id,
                )
            )
            if run is None:
                raise LookupError("research run missing")
            if (
                run.status in {"cancelled", "completed", "failed"}
                or run.cancellation_requested_at is not None
            ):
                raise asyncio.CancelledError

    async def _reserve(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        request: ProviderRequest,
        estimated_cost: Decimal,
    ) -> uuid.UUID:
        async with tenant_session(str(tenant_id)) as session:
            return await self._reserve_in_session(
                session,
                tenant_id=tenant_id,
                run_id=run_id,
                request=request,
                estimated_cost=estimated_cost,
                provider=self._request_provider(request),
            )

    @staticmethod
    async def _reserve_in_session(
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        request: ProviderRequest,
        estimated_cost: Decimal,
        provider: str = "tavily",
    ) -> uuid.UUID:
        reservation = await BudgetReservationRepository(session, tenant_id).reserve(
            run_id=run_id,
            provider=provider,
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
        if existing_call is not None or reservation.state != "reserved":
            raise ReservationReplayError("existing provider attempt cannot be re-dispatched")
        provider_call = ProviderCall(
            tenant_id=tenant_id,
            run_id=run_id,
            reservation_id=reservation.id,
            provider=provider,
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
        actual_cost_usd: Decimal | None = None,
    ) -> None:
        if response_body is not None and run_id is None:
            raise ValueError("run_id is required when persisting a provider response")
        async with tenant_session(str(tenant_id)) as session:
            await BudgetReservationRepository(session, tenant_id).transition(
                reservation_id, new_state=state, actual_cost_usd=actual_cost_usd
            )
            await session.execute(
                update(ExtractionSlot)
                .where(
                    ExtractionSlot.tenant_id == tenant_id,
                    ExtractionSlot.reservation_id == reservation_id,
                    ExtractionSlot.state == "reserved",
                )
                .values(state=state)
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
            provider_call.outcome = (
                "succeeded"
                if state == "consumed" and response_schema_version
                else "uncertain"
                if state == "uncertain"
                else "failed"
            )
            provider_call.completed_at = datetime.now(UTC)
            settled_provider = provider_call.provider
        # Settlement commits before artifact I/O. A paid successful call stays
        # consumed even when object storage is unavailable or the await is cancelled.
        if response_body is not None:
            if run_id is None:
                raise ValueError("run_id is required when persisting a provider response")
            raw_response = json.dumps(
                response_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            try:
                artifact = await self._artifact_store.put(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    content=raw_response,
                    media_type="application/json",
                )
            except Exception:
                dependency_event(
                    provider=settled_provider,
                    operation="response_artifact",
                    outcome="failed",
                    reason="artifact_storage_failed",
                )
                return
            async with tenant_session(str(tenant_id)) as session:
                call = await session.scalar(
                    select(ProviderCall).where(
                        ProviderCall.tenant_id == tenant_id,
                        ProviderCall.reservation_id == reservation_id,
                    )
                )
                if call is None:
                    raise LookupError("provider call missing for reservation")
                call.response_artifact_ref = artifact.artifact_ref
