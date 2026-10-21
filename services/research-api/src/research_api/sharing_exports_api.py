"""Revocable report capabilities and authenticated, version-pinned exports."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select, text
from sqlalchemy.dialects.postgresql import insert

from research_api.auth import Caller, authenticated_caller
from research_api.config import get_settings
from research_api.db.models import Report, ReportExport, ReportShare, ResearchRun, Source
from research_api.db.session import tenant_session
from research_api.report_integrity import report_integrity_payload

router = APIRouter(tags=["report sharing and exports"])
REPORTS_PATH = "/research/reports"
SHARES_PATH = "/s"
RENDERER_VERSION = "report-export-v1"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,100}$")
MAX_EXPORT_BYTES = 1_048_576


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    expires_in_hours: int = Field(default=168, ge=1, le=720, alias="expiresInHours")


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ShareCreated(APIModel):
    id: uuid.UUID
    share_path: str = Field(alias="sharePath")
    expires_at: datetime = Field(alias="expiresAt")


class ShareRevoked(APIModel):
    revoked: bool


class ShareSummary(APIModel):
    id: uuid.UUID
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime = Field(alias="expiresAt")
    revoked_at: datetime | None = Field(alias="revokedAt")


class ExportRequest(APIModel):
    format: Literal["markdown", "bibtex"]


class ExportCreated(APIModel):
    id: uuid.UUID
    report_id: uuid.UUID = Field(alias="reportId")
    report_version: int = Field(alias="reportVersion")
    format: Literal["markdown", "bibtex"]
    sha256: str
    size_bytes: int = Field(alias="sizeBytes")
    download_path: str = Field(alias="downloadPath")


class SharedReport(APIModel):
    title: str
    version: int
    published_at: datetime = Field(alias="publishedAt")
    markdown: str
    document: dict[str, Any] | None


async def caller_dependency(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> Caller:
    return await authenticated_caller(
        get_settings(), x_internal_service_auth, authorization=authorization
    )


CallerDep = Annotated[Caller, Depends(caller_dependency)]


async def _owner_report(
    report_id: uuid.UUID, caller: Caller, *, lock: bool = False
) -> tuple[Report, str]:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        statement = (
            select(Report, ResearchRun.original_question)
            .join(
                ResearchRun,
                and_(ResearchRun.tenant_id == Report.tenant_id, ResearchRun.id == Report.run_id),
            )
            .where(
                Report.tenant_id == caller.tenant_id,
                Report.id == report_id,
                Report.published.is_(True),
                ResearchRun.user_id == caller.user_id,
                ResearchRun.deleted_at.is_(None),
            )
        )
        if lock:
            statement = statement.with_for_update(of=Report)
        row = (await session.execute(statement)).one_or_none()
        if row is None:
            raise HTTPException(404, "published report not found")
        # Return detached immutable data only; the transaction closes before I/O.
        return row[0], row[1]


def _canonical_report_hash(report: Report) -> str:
    payload = json.dumps(
        report_integrity_payload(report),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    if report.content_hash is not None and not secrets.compare_digest(report.content_hash, digest):
        raise HTTPException(409, "published report integrity check failed")
    return digest


def _bibtex_escape(value: str) -> str:
    return value.replace("\\", r"\textbackslash{}").replace("{", r"\{").replace("}", r"\}")


async def _render_export(report: Report, export_format: str, caller: Caller) -> bytes:
    if export_format == "markdown":
        return report.markdown.encode("utf-8")
    if report.document is None:
        raise HTTPException(409, "this historical report has no structured citation records")
    ids = {
        uuid.UUID(source_id)
        for finding in report.document.get("findings", [])
        for source_id in finding.get("sourceIds", [])
    }
    if not ids:
        return b""
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        rows = list(
            await session.scalars(
                select(Source).where(
                    Source.tenant_id == caller.tenant_id,
                    Source.run_id == report.run_id,
                    Source.id.in_(ids),
                )
            )
        )
        if len(rows) != len(ids):
            raise HTTPException(409, "report citation metadata is incomplete")
    entries = []
    for index, source in enumerate(sorted(rows, key=lambda item: item.canonical_url), 1):
        key = f"source{index}_{source.id.hex[:8]}"
        fields = [f"  title = {{{_bibtex_escape(source.title)}}}"]
        if source.publisher:
            fields.append(f"  publisher = {{{_bibtex_escape(source.publisher)}}}")
        if source.published_at:
            fields.append(f"  year = {{{source.published_at.year}}}")
        fields.append(f"  url = {{{_bibtex_escape(source.canonical_url)}}}")
        fields.append(f"  note = {{Retrieved {source.retrieved_at.date().isoformat()}}}")
        entries.append("@misc{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return ("\n\n".join(entries) + "\n").encode("utf-8")


@router.post(REPORTS_PATH + "/{report_id}/shares", response_model=ShareCreated)
async def create_share(
    report_id: uuid.UUID,
    payload: ShareRequest,
    caller: CallerDep,
) -> ShareCreated:
    report, _ = await _owner_report(report_id, caller)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    now = datetime.now(UTC)
    expires = now + timedelta(hours=payload.expires_in_hours)
    share_id = uuid.uuid4()
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        session.add(
            ReportShare(
                id=share_id,
                tenant_id=caller.tenant_id,
                user_id=caller.user_id,
                report_id=report.id,
                token_hash=token_hash,
                expires_at=expires,
                created_at=now,
            )
        )
    # The bearer token is returned once and is never persisted or logged.
    # Fragment tokens are not sent in HTTP requests, referrers, or server URL logs.
    return ShareCreated(
        id=share_id,
        share_path=f"{SHARES_PATH}#share={token}",
        expires_at=expires,
    )


@router.get(REPORTS_PATH + "/{report_id}/shares", response_model=list[ShareSummary])
async def list_shares(report_id: uuid.UUID, caller: CallerDep) -> list[ShareSummary]:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        rows = await session.scalars(
            select(ReportShare)
            .join(
                Report,
                and_(Report.tenant_id == ReportShare.tenant_id, Report.id == ReportShare.report_id),
            )
            .join(
                ResearchRun,
                and_(ResearchRun.tenant_id == Report.tenant_id, ResearchRun.id == Report.run_id),
            )
            .where(
                ReportShare.tenant_id == caller.tenant_id,
                ReportShare.user_id == caller.user_id,
                ReportShare.report_id == report_id,
                Report.published.is_(True),
                ResearchRun.user_id == caller.user_id,
                ResearchRun.deleted_at.is_(None),
            )
            .order_by(ReportShare.created_at.desc())
            .limit(30)
        )
        return [
            ShareSummary(
                id=row.id,
                created_at=row.created_at,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]


@router.post(REPORTS_PATH + "/{report_id}/shares/{share_id}/revoke", response_model=ShareRevoked)
async def revoke_share(
    report_id: uuid.UUID, share_id: uuid.UUID, caller: CallerDep
) -> ShareRevoked:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        share = await session.scalar(
            select(ReportShare)
            .where(
                ReportShare.tenant_id == caller.tenant_id,
                ReportShare.user_id == caller.user_id,
                ReportShare.report_id == report_id,
                ReportShare.id == share_id,
            )
            .with_for_update()
        )
        if share is None:
            raise HTTPException(404, "share not found")
        if share.revoked_at is None:
            share.revoked_at = datetime.now(UTC)
    return ShareRevoked(revoked=True)


@router.get(SHARES_PATH, response_model=SharedReport)
async def read_shared_report(
    authorization: Annotated[str | None, Header()] = None,
) -> SharedReport:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme != "ResearchShare":
        raise HTTPException(404, "shared report not found")
    if not TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(404, "shared report not found")
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    async with tenant_session("00000000-0000-0000-0000-000000000000") as session:
        await session.execute(
            text("SELECT set_config('app.share_token_hash', :hash, true)"), {"hash": digest}
        )
        share = await session.scalar(
            select(ReportShare).where(
                ReportShare.token_hash == digest,
                ReportShare.revoked_at.is_(None),
                ReportShare.expires_at > datetime.now(UTC),
            )
        )
        if share is None:
            raise HTTPException(404, "shared report not found")
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(share.tenant_id)},
        )
        report = await session.scalar(
            select(Report).where(
                Report.tenant_id == share.tenant_id,
                Report.id == share.report_id,
                Report.published.is_(True),
            )
        )
        if report is None:
            raise HTTPException(404, "shared report not found")
        run = await session.scalar(
            select(ResearchRun).where(
                ResearchRun.tenant_id == share.tenant_id,
                ResearchRun.id == report.run_id,
                ResearchRun.deleted_at.is_(None),
            )
        )
        if run is None:
            raise HTTPException(404, "shared report not found")
        _canonical_report_hash(report)
        result = SharedReport(
            title=run.original_question,
            version=report.version,
            published_at=report.published_at or report.created_at,
            markdown=report.markdown,
            document=report.document,
        )
    return Response(
        content=result.model_dump_json(by_alias=True),
        media_type="application/json",
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )  # type: ignore[return-value]


@router.post(REPORTS_PATH + "/{report_id}/exports", response_model=ExportCreated)
async def create_export(
    report_id: uuid.UUID, payload: ExportRequest, caller: CallerDep
) -> ExportCreated:
    report, _ = await _owner_report(report_id, caller)
    report_hash = _canonical_report_hash(report)
    content = await _render_export(report, payload.format, caller)
    if len(content) > MAX_EXPORT_BYTES:
        raise HTTPException(413, "report export exceeds the one-megabyte limit")
    artifact_hash = hashlib.sha256(content).hexdigest()
    export_id = uuid.uuid4()
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        await session.execute(
            insert(ReportExport)
            .values(
                id=export_id,
                tenant_id=caller.tenant_id,
                user_id=caller.user_id,
                report_id=report.id,
                report_version=report.version,
                format=payload.format,
                renderer_version=RENDERER_VERSION,
                document_hash=report_hash,
                artifact_hash=artifact_hash,
                size_bytes=len(content),
                content=content,
            )
            .on_conflict_do_nothing(constraint="uq_report_exports_owner_report_format_renderer")
        )
        export = await session.scalar(
            select(ReportExport).where(
                ReportExport.tenant_id == caller.tenant_id,
                ReportExport.user_id == caller.user_id,
                ReportExport.report_id == report.id,
                ReportExport.format == payload.format,
                ReportExport.renderer_version == RENDERER_VERSION,
            )
        )
        if export is None:
            raise HTTPException(503, "export could not be recorded; retry safely")
    return ExportCreated(
        id=export.id,
        report_id=export.report_id,
        report_version=export.report_version,
        format=export.format,
        sha256=export.artifact_hash,
        size_bytes=export.size_bytes,
        download_path=f"{REPORTS_PATH}/{report_id}/exports/{export.id}/download",
    )


@router.get(REPORTS_PATH + "/{report_id}/exports/{export_id}/download")
async def download_export(
    report_id: uuid.UUID, export_id: uuid.UUID, caller: CallerDep
) -> Response:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        row = (
            await session.execute(
                select(ReportExport)
                .join(
                    Report,
                    and_(
                        Report.tenant_id == ReportExport.tenant_id,
                        Report.id == ReportExport.report_id,
                    ),
                )
                .join(
                    ResearchRun,
                    and_(
                        ResearchRun.tenant_id == Report.tenant_id,
                        ResearchRun.id == Report.run_id,
                    ),
                )
                .where(
                    ReportExport.tenant_id == caller.tenant_id,
                    ReportExport.user_id == caller.user_id,
                    ReportExport.report_id == report_id,
                    ReportExport.id == export_id,
                    Report.published.is_(True),
                    ResearchRun.user_id == caller.user_id,
                    ResearchRun.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(404, "export not found")
        export = row[0]
        content = export.content
        expected_hash, expected_size, export_format = (
            export.artifact_hash,
            export.size_bytes,
            export.format,
        )
    if len(content) != expected_size or not secrets.compare_digest(
        hashlib.sha256(content).hexdigest(), expected_hash
    ):
        raise HTTPException(502, "stored export failed integrity verification")
    extension = "md" if export_format == "markdown" else "bib"
    media = (
        "text/markdown; charset=utf-8"
        if extension == "md"
        else "application/x-bibtex; charset=utf-8"
    )
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": (
                f'attachment; filename="research-report-{report_id}.{extension}"'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
