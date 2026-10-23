"""Authenticated, append-only scholarly review workflow."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.auth import Caller, authenticated_caller
from research_api.config import get_settings
from research_api.db.models import (
    ScholarlyAuditEvent,
    ScholarlyDuplicateMark,
    ScholarlyEvidenceRow,
    ScholarlyRetrievalReceipt,
    ScholarlyReview,
    ScholarlyScreeningDecision,
    ScholarlySearchExecution,
    ScholarlySearchRecord,
    ScholarlyStudyArtifact,
)
from research_api.db.session import tenant_session
from research_api.scholarly.prisma import build_prisma_flow
from research_api.scholarly.screening import (
    FullTextReceipt,
    ScreeningDecision,
    SearchExecution,
    SearchRecord,
)

router = APIRouter(prefix="/research/reviews", tags=["scholarly reviews"])


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class APIModel(BaseModel):
    model_config = ConfigDict(alias_generator=camel, populate_by_name=True, extra="forbid")


class CreateReview(APIModel):
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=10000)


class SearchBody(APIModel):
    search_id: str
    query: str
    executed_at: str
    database: str
    filters: list[dict[str, str]] = Field(default_factory=list)
    result_record_ids: list[str] = Field(default_factory=list)
    reported_result_count: int | None = None


class RecordBody(APIModel):
    record_id: str
    search_id: str
    provider: str
    provider_record_id: str
    title: str
    abstract: str | None = None
    doi: str | None = None
    locator_url: str | None = None


class DecisionBody(APIModel):
    stage: str
    outcome: str
    exclusion_reason: str | None = None
    source_id: str | None = None


class ReceiptBody(APIModel):
    status: str
    source_id: str | None = None


class DuplicateBody(APIModel):
    canonical_record_id: str


class EvidenceBody(APIModel):
    artifact_id: uuid.UUID
    source_id: str
    claim: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=600)
    page_number: int = Field(ge=1, le=100)
    start: int = Field(ge=0, le=1_000_000)
    end: int = Field(gt=0, le=1_000_000)


async def caller_dependency(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> Caller:
    return await authenticated_caller(
        get_settings(), x_internal_service_auth, authorization=authorization
    )


CallerDep = Annotated[Caller, Depends(caller_dependency)]


@asynccontextmanager
async def owner_session(caller: Caller) -> AsyncIterator[AsyncSession]:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        yield session


def scope(model: Any, caller: Caller, review_id: uuid.UUID) -> Any:
    return and_(model.tenant_id == caller.tenant_id,
                model.owner_user_id == caller.user_id, model.review_id == review_id)


async def require_review(
    session: AsyncSession, caller: Caller, review_id: uuid.UUID, *, lock: bool = False
) -> None:
    query = select(ScholarlyReview.id).where(
        ScholarlyReview.id == review_id,
        ScholarlyReview.tenant_id == caller.tenant_id,
        ScholarlyReview.owner_user_id == caller.user_id,
    )
    found = await session.scalar(query.with_for_update() if lock else query)
    if found is None:
        raise HTTPException(404, "review not found")


async def require_record(session: AsyncSession, caller: Caller,
                         review_id: uuid.UUID, record_id: str) -> ScholarlySearchRecord:
    record = await session.scalar(select(ScholarlySearchRecord).where(
        scope(ScholarlySearchRecord, caller, review_id),
        ScholarlySearchRecord.record_id == record_id,
    ))
    if record is None:
        raise HTTPException(404, "record not found")
    return record


def audit(session: AsyncSession, caller: Caller, review_id: uuid.UUID,
          event_type: str, entity_id: str, payload: dict[str, Any]) -> None:
    session.add(ScholarlyAuditEvent(
        tenant_id=caller.tenant_id, owner_user_id=caller.user_id,
        review_id=review_id, actor_user_id=caller.user_id,
        event_type=event_type, entity_id=entity_id, payload=payload,
    ))


async def flush_or_conflict(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "review item already exists or violates review scope") from exc


def review_json(row: ScholarlyReview) -> dict[str, str]:
    return {"id": str(row.id), "title": row.title, "question": row.question,
            "createdAt": row.created_at.isoformat()}


@router.post("", status_code=201)
async def create_review(body: CreateReview, caller: CallerDep) -> dict[str, str]:
    if not body.title.strip() or not body.question.strip():
        raise HTTPException(422, "title and question cannot be blank")
    async with owner_session(caller) as session:
        row = ScholarlyReview(tenant_id=caller.tenant_id, owner_user_id=caller.user_id,
                              title=body.title.strip(), question=body.question.strip())
        session.add(row)
        await session.flush()
        await session.refresh(row)
        audit(session, caller, row.id, "review_created", str(row.id), {})
        return review_json(row)


@router.get("")
async def list_reviews(caller: CallerDep) -> list[dict[str, str]]:
    async with owner_session(caller) as session:
        rows = (await session.scalars(select(ScholarlyReview).where(
            ScholarlyReview.tenant_id == caller.tenant_id,
            ScholarlyReview.owner_user_id == caller.user_id,
        ).order_by(ScholarlyReview.created_at.desc(), ScholarlyReview.id.desc()).limit(100))).all()
        return [review_json(row) for row in rows]


@router.get("/{review_id}")
async def get_review(review_id: uuid.UUID, caller: CallerDep) -> dict[str, str]:
    async with owner_session(caller) as session:
        row = await session.scalar(select(ScholarlyReview).where(
            ScholarlyReview.id == review_id, ScholarlyReview.tenant_id == caller.tenant_id,
            ScholarlyReview.owner_user_id == caller.user_id,
        ))
        if row is None:
            raise HTTPException(404, "review not found")
        return review_json(row)


@router.get("/{review_id}/records")
async def list_records(review_id: uuid.UUID, caller: CallerDep) -> list[dict[str, Any]]:
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)
        rows = (await session.scalars(select(ScholarlySearchRecord).where(
            scope(ScholarlySearchRecord, caller, review_id)
        ).order_by(ScholarlySearchRecord.created_at, ScholarlySearchRecord.id).limit(1000))).all()
        return [{key: getattr(row, key) for key in (
            "record_id", "search_id", "provider", "provider_record_id", "title",
            "abstract", "doi", "locator_url",
        )} for row in rows]


@router.get("/{review_id}/decisions")
async def list_decisions(review_id: uuid.UUID, caller: CallerDep) -> list[dict[str, Any]]:
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)
        query = select(ScholarlyScreeningDecision).where(
            scope(ScholarlyScreeningDecision, caller, review_id)
        ).order_by(ScholarlyScreeningDecision.created_at, ScholarlyScreeningDecision.id).limit(1000)
        rows = (await session.scalars(query)).all()
        return [{key: getattr(row, key) for key in (
            "record_id", "stage", "outcome", "exclusion_reason", "source_id",
        )} for row in rows]


@router.get("/{review_id}/retrievals")
async def list_retrievals(review_id: uuid.UUID, caller: CallerDep) -> list[dict[str, Any]]:
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)
        query = select(ScholarlyRetrievalReceipt).where(
            scope(ScholarlyRetrievalReceipt, caller, review_id)
        ).order_by(ScholarlyRetrievalReceipt.created_at, ScholarlyRetrievalReceipt.id).limit(1000)
        rows = (await session.scalars(query)).all()
        return [{key: getattr(row, key) for key in ("record_id", "status", "source_id")}
                for row in rows]


@router.post("/{review_id}/searches", status_code=201)
async def add_search(review_id: uuid.UUID, body: SearchBody, caller: CallerDep) -> dict[str, str]:
    receipt = SearchExecution.model_validate(body.model_dump())
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id, lock=True)
        row = ScholarlySearchExecution(
            tenant_id=caller.tenant_id, owner_user_id=caller.user_id, review_id=review_id,
            **receipt.model_dump(),
        )
        session.add(row)
        audit(session, caller, review_id, "search_added", receipt.search_id,
              receipt.model_dump(mode="json"))
        await flush_or_conflict(session)
        return {"id": str(row.id), "searchId": row.search_id}


@router.post("/{review_id}/records", status_code=201)
async def add_record(review_id: uuid.UUID, body: RecordBody, caller: CallerDep) -> dict[str, str]:
    record = SearchRecord.model_validate(body.model_dump())
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id, lock=True)
        search = await session.scalar(select(ScholarlySearchExecution).where(
            scope(ScholarlySearchExecution, caller, review_id),
            ScholarlySearchExecution.search_id == record.search_id,
        ))
        if search is None:
            raise HTTPException(404, "search not found")
        if record.record_id not in search.result_record_ids:
            raise HTTPException(422, "record was not observed in search result IDs")
        row = ScholarlySearchRecord(
            tenant_id=caller.tenant_id, owner_user_id=caller.user_id, review_id=review_id,
            **record.model_dump(),
        )
        session.add(row)
        audit(session, caller, review_id, "record_added", record.record_id, record.model_dump())
        await flush_or_conflict(session)
        return {"id": str(row.id), "recordId": row.record_id}


@router.post("/{review_id}/records/{record_id}/decisions", status_code=201)
async def add_decision(review_id: uuid.UUID, record_id: str, body: DecisionBody,
                       caller: CallerDep) -> dict[str, str]:
    decision = ScreeningDecision.model_validate({"record_id": record_id, **body.model_dump()})
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id, lock=True)
        await require_record(session, caller, review_id, record_id)
        duplicate = await session.scalar(select(ScholarlyDuplicateMark.id).where(
            scope(ScholarlyDuplicateMark, caller, review_id),
            ScholarlyDuplicateMark.record_id == record_id,
        ))
        if duplicate is not None:
            raise HTTPException(409, "duplicate record cannot be screened")
        if decision.stage.value == "full_text":
            title = await session.scalar(select(ScholarlyScreeningDecision).where(
                scope(ScholarlyScreeningDecision, caller, review_id),
                ScholarlyScreeningDecision.record_id == record_id,
                ScholarlyScreeningDecision.stage == "title_abstract",
            ))
            receipt = await session.scalar(select(ScholarlyRetrievalReceipt).where(
                scope(ScholarlyRetrievalReceipt, caller, review_id),
                ScholarlyRetrievalReceipt.record_id == record_id,
            ))
            if title is None or title.outcome != "include" or receipt is None or (
                receipt.status != "retrieved" or receipt.source_id != decision.source_id
            ):
                raise HTTPException(
                    409, "full-text decision requires title inclusion and matching retrieval"
                )
        row = ScholarlyScreeningDecision(
            tenant_id=caller.tenant_id, owner_user_id=caller.user_id, review_id=review_id,
            actor_user_id=caller.user_id, **decision.model_dump(mode="json"),
        )
        session.add(row)
        audit(session, caller, review_id, "screening_decided", record_id,
              decision.model_dump(mode="json"))
        await flush_or_conflict(session)
        return {"id": str(row.id), "recordId": record_id, "stage": row.stage}


@router.post("/{review_id}/records/{record_id}/retrievals", status_code=201)
async def add_retrieval(review_id: uuid.UUID, record_id: str, body: ReceiptBody,
                        caller: CallerDep) -> dict[str, str]:
    receipt = FullTextReceipt.model_validate({"record_id": record_id, **body.model_dump()})
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id, lock=True)
        await require_record(session, caller, review_id, record_id)
        duplicate = await session.scalar(select(ScholarlyDuplicateMark.id).where(
            scope(ScholarlyDuplicateMark, caller, review_id),
            ScholarlyDuplicateMark.record_id == record_id,
        ))
        if duplicate is not None:
            raise HTTPException(409, "duplicate record cannot be retrieved")
        title = await session.scalar(select(ScholarlyScreeningDecision).where(
            scope(ScholarlyScreeningDecision, caller, review_id),
            ScholarlyScreeningDecision.record_id == record_id,
            ScholarlyScreeningDecision.stage == "title_abstract",
        ))
        if title is None or title.outcome != "include":
            raise HTTPException(409, "retrieval requires title inclusion")
        if receipt.source_id is not None:
            artifact = await session.scalar(select(ScholarlyStudyArtifact.id).where(
                scope(ScholarlyStudyArtifact, caller, review_id),
                ScholarlyStudyArtifact.record_id == record_id,
                ScholarlyStudyArtifact.id == uuid.UUID(receipt.source_id),
            )) if _is_uuid(receipt.source_id) else None
            if artifact is None:
                raise HTTPException(409, "retrieved source must be a stored full-text artifact")
        row = ScholarlyRetrievalReceipt(
            tenant_id=caller.tenant_id, owner_user_id=caller.user_id, review_id=review_id,
            actor_user_id=caller.user_id, **receipt.model_dump(mode="json"),
        )
        session.add(row)
        audit(session, caller, review_id, "retrieval_recorded", record_id,
              receipt.model_dump(mode="json"))
        await flush_or_conflict(session)
        return {"id": str(row.id), "recordId": record_id, "status": row.status}


@router.post("/{review_id}/records/{record_id}/duplicate", status_code=201)
async def mark_duplicate(review_id: uuid.UUID, record_id: str, body: DuplicateBody,
                         caller: CallerDep) -> dict[str, str]:
    if record_id == body.canonical_record_id:
        raise HTTPException(422, "record cannot duplicate itself")
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id, lock=True)
        await require_record(session, caller, review_id, record_id)
        await require_record(session, caller, review_id, body.canonical_record_id)
        activity = await session.scalar(select(ScholarlyScreeningDecision.id).where(
            scope(ScholarlyScreeningDecision, caller, review_id),
            ScholarlyScreeningDecision.record_id == record_id,
        ))
        if activity is not None:
            raise HTTPException(409, "screened record cannot be marked duplicate")
        canonical_duplicate = await session.scalar(select(ScholarlyDuplicateMark.id).where(
            scope(ScholarlyDuplicateMark, caller, review_id),
            ScholarlyDuplicateMark.record_id == body.canonical_record_id,
        ))
        receipt = await session.scalar(select(ScholarlyRetrievalReceipt.id).where(
            scope(ScholarlyRetrievalReceipt, caller, review_id),
            ScholarlyRetrievalReceipt.record_id == record_id,
        ))
        artifact = await session.scalar(select(ScholarlyStudyArtifact.id).where(
            scope(ScholarlyStudyArtifact, caller, review_id),
            ScholarlyStudyArtifact.record_id == record_id,
        ))
        if canonical_duplicate is not None or receipt is not None or artifact is not None:
            raise HTTPException(409, "duplicate marking conflicts with review history")
        row = ScholarlyDuplicateMark(
            tenant_id=caller.tenant_id, owner_user_id=caller.user_id, review_id=review_id,
            record_id=record_id, canonical_record_id=body.canonical_record_id,
            actor_user_id=caller.user_id,
        )
        session.add(row)
        audit(session, caller, review_id, "duplicate_marked", record_id,
              {"canonicalRecordId": body.canonical_record_id})
        await flush_or_conflict(session)
        return {"id": str(row.id), "recordId": record_id,
                "canonicalRecordId": body.canonical_record_id}


@router.post("/{review_id}/records/{record_id}/evidence", status_code=201)
async def add_evidence(review_id: uuid.UUID, record_id: str, body: EvidenceBody,
                       caller: CallerDep) -> dict[str, str]:
    if not body.claim.strip() or not body.quote.strip():
        raise HTTPException(422, "claim and quote cannot be blank")
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id, lock=True)
        await require_record(session, caller, review_id, record_id)
        decision = await session.scalar(select(ScholarlyScreeningDecision).where(
            scope(ScholarlyScreeningDecision, caller, review_id),
            ScholarlyScreeningDecision.record_id == record_id,
            ScholarlyScreeningDecision.stage == "full_text",
        ))
        receipt = await session.scalar(select(ScholarlyRetrievalReceipt).where(
            scope(ScholarlyRetrievalReceipt, caller, review_id),
            ScholarlyRetrievalReceipt.record_id == record_id,
        ))
        artifact = await session.scalar(select(ScholarlyStudyArtifact).where(
            scope(ScholarlyStudyArtifact, caller, review_id),
            ScholarlyStudyArtifact.record_id == record_id,
            ScholarlyStudyArtifact.id == body.artifact_id,
        ))
        if (decision is None or decision.outcome != "include"
                or decision.source_id != body.source_id
                or receipt is None or receipt.status != "retrieved"
                or receipt.source_id != body.source_id):
            raise HTTPException(409, "evidence requires matching retrieved source")
        if artifact is None or str(artifact.id) != body.source_id:
            raise HTTPException(422, "source must be the imported artifact")
        # The import verifier reads the object back, checks its hash, re-extracts
        # the PDF, and verifies the exact quote span within the selected page.
        from research_api.scholarly.import_api import AnchorCheckRequest, verify_anchor

        await verify_anchor(review_id, body.artifact_id, AnchorCheckRequest(
            page_number=body.page_number, start=body.start,
            end=body.end, quote=body.quote,
        ), caller)
        row = ScholarlyEvidenceRow(
            tenant_id=caller.tenant_id, owner_user_id=caller.user_id, review_id=review_id,
            record_id=record_id, actor_user_id=caller.user_id,
            artifact_id=body.artifact_id, source_id=body.source_id,
            claim=body.claim, quote=body.quote, page_anchor=f"page:{body.page_number}",
        )
        session.add(row)
        audit(session, caller, review_id, "evidence_added", record_id,
              {"artifactId": str(body.artifact_id), "sourceId": body.source_id})
        await flush_or_conflict(session)
        return {"id": str(row.id), "recordId": record_id}


@router.get("/{review_id}/evidence")
async def list_evidence(review_id: uuid.UUID, caller: CallerDep) -> list[dict[str, Any]]:
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)
        rows = (await session.scalars(select(ScholarlyEvidenceRow).where(
            scope(ScholarlyEvidenceRow, caller, review_id)
        ).order_by(ScholarlyEvidenceRow.created_at, ScholarlyEvidenceRow.id).limit(1000))).all()
        return [{"id": str(row.id), "recordId": row.record_id,
                 "artifactId": str(row.artifact_id), "sourceId": row.source_id,
                 "claim": row.claim, "quote": row.quote, "pageAnchor": row.page_anchor}
                for row in rows]


@router.get("/{review_id}/prisma")
async def prisma_counts(review_id: uuid.UUID, caller: CallerDep) -> dict[str, Any]:
    async with owner_session(caller) as session:
        await require_review(session, caller, review_id)
        records = (await session.scalars(select(ScholarlySearchRecord).where(
            scope(ScholarlySearchRecord, caller, review_id)))).all()
        decisions = (await session.scalars(select(ScholarlyScreeningDecision).where(
            scope(ScholarlyScreeningDecision, caller, review_id)))).all()
        receipts = (await session.scalars(select(ScholarlyRetrievalReceipt).where(
            scope(ScholarlyRetrievalReceipt, caller, review_id)))).all()
        duplicates = (await session.scalars(select(ScholarlyDuplicateMark.record_id).where(
            scope(ScholarlyDuplicateMark, caller, review_id)))).all()
        try:
            flow = build_prisma_flow(
                [SearchRecord.model_validate({key: getattr(row, key) for key in
                    ("record_id", "search_id", "provider", "provider_record_id",
                     "title", "abstract", "doi", "locator_url")}) for row in records],
                [ScreeningDecision.model_validate({key: getattr(row, key) for key in
                    ("record_id", "stage", "outcome", "exclusion_reason", "source_id")})
                 for row in decisions],
                [FullTextReceipt.model_validate({key: getattr(row, key) for key in
                    ("record_id", "status", "source_id")}) for row in receipts],
                duplicate_record_ids=duplicates,
            )
        except ValueError as exc:
            raise HTTPException(409, f"review workflow is inconsistent: {exc}") from exc
        from dataclasses import asdict
        return asdict(flow)
