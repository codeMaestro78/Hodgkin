"""Authenticated DOI discovery and inspected PDF text imports for scholarly reviews."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.artifacts.store import ArtifactRecord, ArtifactStore, artifact_identity
from research_api.auth import Caller
from research_api.db.models import (
    ScholarlySearchExecution,
    ScholarlySearchRecord,
    ScholarlyStudyArtifact,
)
from research_api.providers.crossref import CrossrefAdapter, CrossrefRequestError
from research_api.providers.doi import normalize_doi
from research_api.scholarly.pdf_extract import (
    MAX_PDF_BYTES,
    PDFExtractionError,
    PDFQuoteMismatch,
    PDFSourceMismatch,
    PDFSourceUnavailable,
    assemble_pages,
    extract_pdf_text,
    review_artifact_store,
    verify_stored_pdf_quote,
)
from research_api.scholarly.review_api import APIModel, CallerDep, owner_session, require_review

router = APIRouter(prefix="/research/reviews", tags=["scholarly imports"])


class DoiImportRequest(APIModel):
    doi: str = Field(min_length=1, max_length=2048)


class ImportResponse(APIModel):
    review_id: uuid.UUID
    record_id: str
    doi: str | None
    title: str
    evidence_status: Literal["discovery_only", "page_text_locator"]
    source_artifact_id: uuid.UUID | None = None
    page_numbers: list[int] = Field(default_factory=list)
    already_imported: bool = False


class AnchorCheckRequest(APIModel):
    page_number: int = Field(ge=1, le=100)
    start: int | None = Field(default=None, ge=0, le=1_000_000)
    end: int | None = Field(default=None, gt=0, le=1_000_000)
    quote: str = Field(min_length=1, max_length=600)


class AnchorCheckResponse(APIModel):
    artifact_id: uuid.UUID
    page_number: int
    locator_verified: Literal[True] = True
    claim_support_verified: Literal[False] = False


async def _existing_pdf_import(
    session: AsyncSession, caller: Caller, review_id: uuid.UUID, content_hash: str,
) -> ImportResponse | None:
    existing = await session.scalar(select(ScholarlyStudyArtifact).where(
        ScholarlyStudyArtifact.tenant_id == caller.tenant_id,
        ScholarlyStudyArtifact.owner_user_id == caller.user_id,
        ScholarlyStudyArtifact.review_id == review_id,
        ScholarlyStudyArtifact.content_hash == content_hash,
    ).order_by(ScholarlyStudyArtifact.created_at, ScholarlyStudyArtifact.id).limit(1))
    if existing is None:
        return None
    record = await session.scalar(select(ScholarlySearchRecord).where(
        ScholarlySearchRecord.tenant_id == caller.tenant_id,
        ScholarlySearchRecord.owner_user_id == caller.user_id,
        ScholarlySearchRecord.review_id == review_id,
        ScholarlySearchRecord.record_id == existing.record_id,
    ))
    if record is None:
        raise HTTPException(409, "imported PDF has no review record")
    return ImportResponse(
        review_id=review_id, record_id=existing.record_id, doi=record.doi,
        title=record.title, evidence_status="page_text_locator",
        source_artifact_id=existing.id,
        page_numbers=[
            anchor["page_number"] for anchor in existing.page_anchors
            if isinstance(anchor, dict)
            and isinstance(anchor.get("page_number"), int)
            and not isinstance(anchor["page_number"], bool)
        ],
        already_imported=True,
    )


async def _require_review(review_id: uuid.UUID, caller: Caller) -> None:
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)


async def _verified_put(
    store: ArtifactStore,
    *,
    caller: Caller,
    review_id: uuid.UUID,
    content: bytes,
    media_type: str,
) -> ArtifactRecord:
    # The store's run namespace is used for review-owned imports. No ResearchRun is implied.
    record = await store.put(
        tenant_id=caller.tenant_id,
        run_id=review_id,
        content=content,
        media_type=media_type,
    )
    expected = artifact_identity(
        tenant_id=caller.tenant_id,
        run_id=review_id,
        content=content,
        media_type=media_type,
    )
    if record != expected:
        raise HTTPException(503, "stored artifact identity failed verification")
    try:
        stored = await store.get_for_verification(artifact_ref=record.artifact_ref)
    except (KeyError, OSError, BotoCoreError, ClientError) as exc:
        raise HTTPException(503, "stored artifact could not be verified") from exc
    if (
        record.size_bytes != len(content)
        or record.content_hash != hashlib.sha256(content).hexdigest()
        or len(stored) != record.size_bytes
        or hashlib.sha256(stored).hexdigest() != record.content_hash
        or stored != content
    ):
        raise HTTPException(503, "stored artifact failed verification")
    return record


async def _bounded_pdf(request: Request) -> bytes:
    media_type = request.headers.get("content-type", "").lower().strip()
    if media_type != "application/pdf":
        raise HTTPException(415, "content type must be application/pdf")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError as exc:
            raise HTTPException(400, "invalid content length") from exc
        if declared < 1 or declared > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF exceeds 10 MiB limit")
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF exceeds 10 MiB limit")
        buffer.extend(chunk)
    if not buffer:
        raise HTTPException(400, "PDF is empty")
    return bytes(buffer)


@router.post("/{review_id}/imports/doi", response_model=ImportResponse, status_code=201)
async def import_doi(
    review_id: uuid.UUID, payload: DoiImportRequest, caller: CallerDep
) -> ImportResponse:
    doi = normalize_doi(payload.doi)
    if doi is None or len(doi) > 500:
        raise HTTPException(422, "invalid DOI")
    await _require_review(review_id, caller)
    adapter = CrossrefAdapter()
    try:
        result = await adapter.lookup(adapter.lookup_request(doi=doi))
    except CrossrefRequestError as exc:
        raise HTTPException(502, "DOI metadata lookup failed") from exc
    finally:
        await adapter.aclose()
    metadata = result.metadata
    record_id = str(uuid.uuid4())
    search_id = f"user-doi-import:{record_id}"
    async with owner_session(caller) as session:
        # Recheck ownership at persistence time, after the external request.
        await require_review(session, caller, review_id)
        session.add(
            ScholarlySearchExecution(
                tenant_id=caller.tenant_id,
                owner_user_id=caller.user_id,
                review_id=review_id,
                search_id=search_id,
                query=doi,
                executed_at=datetime.now(UTC),
                database="user_doi_import",
                filters=[],
                result_record_ids=[record_id],
                reported_result_count=1,
            )
        )
        session.add(
            ScholarlySearchRecord(
                tenant_id=caller.tenant_id,
                owner_user_id=caller.user_id,
                review_id=review_id,
                record_id=record_id,
                search_id=search_id,
                provider="crossref_metadata",
                provider_record_id=doi,
                title=metadata.title or doi,
                abstract=metadata.abstract,
                doi=doi,
                locator_url=metadata.landing_page_url,
            )
        )
    return ImportResponse(
        review_id=review_id,
        record_id=record_id,
        doi=doi,
        title=metadata.title or doi,
        evidence_status="discovery_only",
    )


@router.post("/{review_id}/imports/pdf", response_model=ImportResponse, status_code=201)
async def import_pdf(
    review_id: uuid.UUID,
    request: Request,
    response: Response,
    caller: CallerDep,
    title: Annotated[str, Query(min_length=1, max_length=500)],
) -> ImportResponse:
    await _require_review(review_id, caller)
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(422, "title must contain text")
    raw = await _bounded_pdf(request)
    content_hash = hashlib.sha256(raw).hexdigest()
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)
        duplicate = await _existing_pdf_import(session, caller, review_id, content_hash)
    if duplicate is not None:
        response.status_code = 200
        return duplicate
    try:
        pages = await asyncio.to_thread(extract_pdf_text, raw)
    except PDFExtractionError as exc:
        raise HTTPException(422, str(exc)) from exc
    store = review_artifact_store()
    original = await _verified_put(
        store, caller=caller, review_id=review_id, content=raw, media_type="application/pdf"
    )
    parsed_text, page_anchors = assemble_pages(pages)
    record_id = str(uuid.uuid4())
    search_id = f"user-pdf-import:{record_id}"
    original_id = uuid.uuid4()
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id, lock=True)
        # A concurrent upload may have committed while this one was parsed/stored.
        duplicate = await _existing_pdf_import(session, caller, review_id, content_hash)
        if duplicate is not None:
            response.status_code = 200
            return duplicate
        session.add(
            ScholarlySearchExecution(
                tenant_id=caller.tenant_id,
                owner_user_id=caller.user_id,
                review_id=review_id,
                search_id=search_id,
                query="user supplied PDF",
                executed_at=datetime.now(UTC),
                database="user_pdf_import",
                filters=[],
                result_record_ids=[record_id],
                reported_result_count=1,
            )
        )
        session.add(
            ScholarlySearchRecord(
                tenant_id=caller.tenant_id,
                owner_user_id=caller.user_id,
                review_id=review_id,
                record_id=record_id,
                search_id=search_id,
                provider="user_pdf_upload",
                provider_record_id=original.content_hash,
                title=clean_title,
                abstract=None,
                doi=None,
                locator_url=None,
            )
        )
        session.add(
            ScholarlyStudyArtifact(
                id=original_id,
                tenant_id=caller.tenant_id,
                owner_user_id=caller.user_id,
                review_id=review_id,
                record_id=record_id,
                artifact_ref=original.artifact_ref,
                content_hash=original.content_hash,
                parsed_text=parsed_text,
                page_anchors=page_anchors,
            )
        )
    return ImportResponse(
        review_id=review_id,
        record_id=record_id,
        doi=None,
        title=clean_title,
        evidence_status="page_text_locator",
        source_artifact_id=original_id,
        page_numbers=[page.page_number for page in pages],
    )


@router.post(
    "/{review_id}/imports/artifacts/{artifact_id}/verify-anchor",
    response_model=AnchorCheckResponse,
)
async def verify_anchor(
    review_id: uuid.UUID,
    artifact_id: uuid.UUID,
    payload: AnchorCheckRequest,
    caller: CallerDep,
) -> AnchorCheckResponse:
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)
        artifact = await session.scalar(
            select(ScholarlyStudyArtifact).where(
                ScholarlyStudyArtifact.id == artifact_id,
                ScholarlyStudyArtifact.tenant_id == caller.tenant_id,
                ScholarlyStudyArtifact.owner_user_id == caller.user_id,
                ScholarlyStudyArtifact.review_id == review_id,
            )
        )
        if artifact is None:
            raise HTTPException(404, "artifact not found")
    try:
        await verify_stored_pdf_quote(
            review_artifact_store(),
            caller=caller,
            review_id=review_id,
            artifact=artifact,
            page_anchor=f"page:{payload.page_number}",
            start=payload.start,
            end=payload.end,
            quote=payload.quote,
        )
    except PDFSourceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except PDFSourceMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except PDFQuoteMismatch as exc:
        raise HTTPException(422, str(exc)) from exc
    return AnchorCheckResponse(artifact_id=artifact_id, page_number=payload.page_number)
