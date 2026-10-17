"""Private project folders and saved report versions/sources; no model or provider calls.

Register ``router`` on the application. Saves are insert-on-conflict no-ops:
organizing is explicit, so retries cannot reset a user's existing annotations.
Lists use ascending immutable UUIDs; after is an exclusive UUID cursor, not a timestamp.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import field_validator, model_validator
from sqlalchemy import RowMapping, Select, and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from research_api.auth import Caller
from research_api.auth import authenticated_caller as _caller
from research_api.config import get_settings
from research_api.db.models import LibraryItem, Project, Report, ResearchRun, Source
from research_api.db.session import tenant_session
from research_api.schemas.generated.create_project_request import CreateProjectRequest
from research_api.schemas.generated.library_item import LibraryItem as LibraryItemResponse
from research_api.schemas.generated.library_items_response import LibraryItemsResponse
from research_api.schemas.generated.organize_library_item_request import OrganizeLibraryItemRequest
from research_api.schemas.generated.project import Project as ProjectResponse
from research_api.schemas.generated.projects_response import ProjectsResponse
from research_api.schemas.generated.remove_library_item_response import RemoveLibraryItemResponse
from research_api.schemas.generated.save_library_item_request import (
    SaveLibraryItemRequest as GeneratedSaveLibraryItemRequest,
)

router = APIRouter(prefix="/research", tags=["library"])


class ProjectRequest(CreateProjectRequest):
    # Zod trim is a transform and JSON Schema cannot express it. Normalize before
    # the generated bounds run, including the all-whitespace rejection.
    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SaveLibraryItemRequest(GeneratedSaveLibraryItemRequest):
    @model_validator(mode="before")
    @classmethod
    def reject_null_folder(cls, value: Any) -> Any:
        # Generated optional fields also accept null; the Zod save boundary
        # allows omission, while only organize permits an explicit null folder.
        if isinstance(value, dict) and any(
            key in value and value[key] is None for key in ("projectId", "project_id")
        ):
            raise ValueError("omit projectId to save without a folder")
        return value


async def caller_dependency(
    authorization: Annotated[str | None, Header()] = None,
    x_internal_service_auth: Annotated[str | None, Header()] = None,
) -> Caller:
    return await _caller(get_settings(), x_internal_service_auth, authorization=authorization)


CallerDep = Annotated[Caller, Depends(caller_dependency)]


@asynccontextmanager
async def owner_session(caller: Caller) -> AsyncIterator[AsyncSession]:
    async with tenant_session(str(caller.tenant_id)) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :id, true)"), {"id": str(caller.user_id)}
        )
        yield session


def owned(
    model: type[Project] | type[LibraryItem] | type[ResearchRun], caller: Caller
) -> ColumnElement[bool]:
    return and_(model.tenant_id == caller.tenant_id, model.user_id == caller.user_id)


async def check_project(
    session: AsyncSession, caller: Caller, project_id: uuid.UUID | None
) -> None:
    if (
        project_id is not None
        and await session.scalar(
            select(Project.id).where(owned(Project, caller), Project.id == project_id)
        )
        is None
    ):
        raise HTTPException(404, "project not found")


def item_query(caller: Caller) -> Select[*tuple[Any, ...]]:
    # One joined projection for both target types, always through the owning run.
    return (
        select(
            LibraryItem.id,
            LibraryItem.report_id.label("reportId"),
            LibraryItem.source_id.label("sourceId"),
            LibraryItem.project_id.label("projectId"),
            LibraryItem.tags,
            LibraryItem.notes,
            LibraryItem.created_at.label("createdAt"),
            ResearchRun.id.label("runId"),
            Report.version.label("reportVersion"),
            Source.canonical_url.label("url"),
            func.coalesce(Source.title, ResearchRun.original_question).label("title"),
        )
        .outerjoin(
            Report,
            and_(Report.tenant_id == LibraryItem.tenant_id, Report.id == LibraryItem.report_id),
        )
        .outerjoin(
            Source,
            and_(Source.tenant_id == LibraryItem.tenant_id, Source.id == LibraryItem.source_id),
        )
        .join(
            ResearchRun,
            and_(
                ResearchRun.tenant_id == LibraryItem.tenant_id,
                ResearchRun.id == func.coalesce(Report.run_id, Source.run_id),
            ),
        )
        .where(
            owned(LibraryItem, caller),
            owned(ResearchRun, caller),
            or_(LibraryItem.report_id.is_(None), Report.published.is_(True)),
        )
    )


def item_payload(row: RowMapping) -> dict[str, Any]:
    result = dict(row)
    result["kind"] = "report" if result["reportId"] is not None else "source"
    return result


async def read_item(
    session: AsyncSession, caller: Caller, item_id: uuid.UUID
) -> LibraryItemResponse:
    row = (
        (await session.execute(item_query(caller).where(LibraryItem.id == item_id)))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "library item not found")
    return LibraryItemResponse.model_validate(item_payload(row))


@router.get("/projects", response_model=ProjectsResponse)
async def list_projects(caller: CallerDep) -> ProjectsResponse:
    async with owner_session(caller) as session:
        rows = (
            await session.execute(
                select(Project.id, Project.name, Project.created_at.label("createdAt"))
                .where(owned(Project, caller))
                .order_by(Project.id)
            )
        ).mappings()
        return ProjectsResponse.model_validate({"projects": list(rows)})


@router.post("/projects", response_model=ProjectResponse)
async def create_project(payload: ProjectRequest, caller: CallerDep) -> ProjectResponse:
    async with owner_session(caller) as session:
        project = Project(tenant_id=caller.tenant_id, user_id=caller.user_id, name=payload.name)
        session.add(project)
        await session.flush()
        return ProjectResponse(id=project.id, name=project.name, created_at=project.created_at)


@router.post("/library/items", response_model=LibraryItemResponse)
async def save_item(payload: SaveLibraryItemRequest, caller: CallerDep) -> LibraryItemResponse:
    data = payload.model_dump(by_alias=True)
    async with owner_session(caller) as session:
        await check_project(session, caller, data.get("projectId"))
        report_id, source_id = data.get("reportId"), data.get("sourceId")
        target = Report if report_id is not None else Source
        target_id = report_id if report_id is not None else source_id
        statement = (
            select(target.id)
            .join(
                ResearchRun,
                and_(ResearchRun.tenant_id == target.tenant_id, ResearchRun.id == target.run_id),
            )
            .where(
                target.tenant_id == caller.tenant_id,
                target.id == target_id,
                owned(ResearchRun, caller),
            )
        )
        if target is Report:
            statement = statement.where(Report.published.is_(True))
        if await session.scalar(statement) is None:
            raise HTTPException(404, "published report or source not found")
        constraint = "uq_library_report" if report_id is not None else "uq_library_source"
        inserted = await session.scalar(
            insert(LibraryItem)
            .values(
                tenant_id=caller.tenant_id,
                user_id=caller.user_id,
                report_id=report_id,
                source_id=source_id,
                project_id=data.get("projectId"),
                tags=data["tags"],
                notes=data["notes"],
            )
            .on_conflict_do_nothing(constraint=constraint)
            .returning(LibraryItem.id)
        )
        if inserted is None:
            column = LibraryItem.report_id if report_id is not None else LibraryItem.source_id
            inserted = await session.scalar(
                select(LibraryItem.id).where(owned(LibraryItem, caller), column == target_id)
            )
        if inserted is None:
            # Concurrent removal after a conflicting insert; a retry is safe.
            raise HTTPException(409, "library item changed; retry save")
        return await read_item(session, caller, inserted)


@router.get("/library/items", response_model=LibraryItemsResponse)
async def list_items(
    caller: CallerDep,
    query: Annotated[str, Query(max_length=200)] = "",
    projectId: uuid.UUID | None = None,
    kind: Literal["report", "source"] | None = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
    after: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LibraryItemsResponse:
    async with owner_session(caller) as session:
        await check_project(session, caller, projectId)
        statement = item_query(caller)
        if projectId is not None:
            statement = statement.where(LibraryItem.project_id == projectId)
        if kind is not None:
            column = LibraryItem.report_id if kind == "report" else LibraryItem.source_id
            statement = statement.where(column.is_not(None))
        if tag is not None:
            statement = statement.where(LibraryItem.tags.contains([tag]))
        if after is not None:
            statement = statement.where(LibraryItem.id > after)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            title = func.coalesce(Source.title, ResearchRun.original_question)
            statement = statement.where(
                or_(
                    title.ilike(pattern, escape="\\"), LibraryItem.notes.ilike(pattern, escape="\\")
                )
            )
        rows = (
            (await session.execute(statement.order_by(LibraryItem.id).limit(limit + 1)))
            .mappings()
            .all()
        )
        return LibraryItemsResponse.model_validate(
            {
                "items": [item_payload(row) for row in rows[:limit]],
                "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None,
            }
        )


@router.post("/library/items/{item_id}/remove", response_model=RemoveLibraryItemResponse)
async def remove_item(item_id: uuid.UUID, caller: CallerDep) -> RemoveLibraryItemResponse:
    async with owner_session(caller) as session:
        item = await session.scalar(
            select(LibraryItem)
            .where(owned(LibraryItem, caller), LibraryItem.id == item_id)
            .with_for_update()
        )
        if item is None:
            raise HTTPException(404, "library item not found")
        await session.delete(item)
        return RemoveLibraryItemResponse(id=item_id)


@router.post("/library/items/{item_id}/organize", response_model=LibraryItemResponse)
async def organize_item(
    item_id: uuid.UUID, payload: OrganizeLibraryItemRequest, caller: CallerDep
) -> LibraryItemResponse:
    async with owner_session(caller) as session:
        item = await session.scalar(
            select(LibraryItem)
            .where(owned(LibraryItem, caller), LibraryItem.id == item_id)
            .with_for_update()
        )
        if item is None:
            raise HTTPException(404, "library item not found")
        await check_project(session, caller, payload.project_id)
        item.project_id = payload.project_id
        item.tags = payload.model_dump()["tags"]
        item.notes = payload.notes
        await session.flush()
        return await read_item(session, caller, item_id)
