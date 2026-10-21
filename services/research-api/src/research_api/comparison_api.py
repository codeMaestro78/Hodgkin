"""Read projections over two owner-authorized immutable report versions."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from research_api.auth import authenticated_caller
from research_api.config import get_settings
from research_api.db.models import Report, ResearchRun, Source
from research_api.db.session import tenant_session
from research_api.report_comparison import ComparisonInput, compare_reports
from research_api.report_document import validate_report_document
from research_api.schemas.generated.compared_report_list import ComparedReportList
from research_api.schemas.generated.report_comparison import ReportComparison
from research_api.schemas.generated.report_comparison_request import ReportComparisonRequest

router = APIRouter(prefix="/research/reports", tags=["reports"])


def report_metadata(report: Report, title: str, document: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": str(report.id),
        "runId": str(report.run_id),
        "version": report.version,
        "title": title,
        "publishedAt": (report.published_at or report.created_at).isoformat(),
        "quality": document["quality"]["status"] if document else "not_assessed",
        "structured": document is not None,
    }


@router.get("")
async def list_reports(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
    after: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> ComparedReportList:
    caller = await authenticated_caller(
        get_settings(), x_internal_service_auth, authorization=authorization
    )
    async with tenant_session(str(caller.tenant_id)) as session:
        query = (
            select(
                Report.id,
                Report.run_id,
                Report.version,
                func.coalesce(Report.published_at, Report.created_at).label("published_at"),
                ResearchRun.original_question,
                Report.document.is_not(None).label("structured"),
                Report.document["quality"]["status"].astext.label("quality"),
            )
            .join(
                ResearchRun,
                (ResearchRun.tenant_id == Report.tenant_id) & (ResearchRun.id == Report.run_id),
            )
            .where(
                Report.tenant_id == caller.tenant_id,
                Report.published.is_(True),
                ResearchRun.user_id == caller.user_id,
                ResearchRun.deleted_at.is_(None),
            )
            .order_by(Report.id.desc())
            .limit(limit + 1)
        )
        if after is not None:
            query = query.where(Report.id < after)
        rows = list(await session.execute(query))
        result = []
        for row in rows[:limit]:
            result.append(
                {
                    "id": str(row.id),
                    "runId": str(row.run_id),
                    "version": row.version,
                    "publishedAt": row.published_at.isoformat(),
                    "title": row.original_question,
                    "structured": row.structured,
                    "quality": row.quality if row.structured else "not_assessed",
                }
            )
        return ComparedReportList.model_validate(
            {
                "reports": result,
                "nextCursor": str(rows[limit - 1].id) if len(rows) > limit else None,
            }
        )


@router.post("/compare")
async def compare(
    payload: ReportComparisonRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> ReportComparison:
    if payload.left_report_id == payload.right_report_id:
        raise HTTPException(422, "choose two different report versions")
    caller = await authenticated_caller(
        get_settings(), x_internal_service_auth, authorization=authorization
    )
    ids = {payload.left_report_id, payload.right_report_id}
    inputs: dict[uuid.UUID, ComparisonInput] = {}
    async with tenant_session(str(caller.tenant_id)) as session:
        rows = list(
            await session.execute(
                select(Report, ResearchRun.original_question)
                .join(
                    ResearchRun,
                    (ResearchRun.tenant_id == Report.tenant_id) & (ResearchRun.id == Report.run_id),
                )
                .where(
                    Report.tenant_id == caller.tenant_id,
                    Report.id.in_(ids),
                    Report.published.is_(True),
                    ResearchRun.user_id == caller.user_id,
                    ResearchRun.deleted_at.is_(None),
                )
            )
        )
        if len(rows) != len(ids):
            raise HTTPException(404, "Published report not found")
        documents: dict[uuid.UUID, dict[str, Any] | None] = {}
        for report, _ in rows:
            try:
                documents[report.id] = (
                    validate_report_document(report.document)
                    if report.document is not None
                    else None
                )
            except ValueError as exc:
                raise HTTPException(409, "A report assessment could not be read") from exc
        source_ids = {
            uuid.UUID(source_id)
            for doc in documents.values()
            if doc is not None
            for finding in doc["findings"]
            for source_id in finding["sourceIds"]
        }
        sources = (
            list(
                await session.scalars(
                    select(Source).where(
                        Source.tenant_id == caller.tenant_id,
                        Source.run_id.in_({report.run_id for report, _ in rows}),
                        Source.id.in_(source_ids),
                    )
                )
            )
            if source_ids
            else []
        )
        for report, title in rows:
            document = documents[report.id]
            selected = {
                source_id
                for finding in (document["findings"] if document else [])
                for source_id in finding["sourceIds"]
            }
            known = {
                str(source.id): (source.canonical_url, source.content_hash)
                for source in sources
                if source.run_id == report.run_id and str(source.id) in selected
            }
            if set(known) != selected:
                raise HTTPException(409, "Report evidence is incomplete for comparison")
            inputs[report.id] = ComparisonInput(
                metadata=report_metadata(report, title, document),
                markdown=report.markdown,
                document=document,
                sources=known,
            )
    # Release the database transaction before bounded CPU work.
    return await run_in_threadpool(
        compare_reports, inputs[payload.left_report_id], inputs[payload.right_report_id]
    )
