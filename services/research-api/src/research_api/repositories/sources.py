from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import Source


class _Lookup(Enum):
    REQUIRED = "required"


class SourceRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def find_existing(
        self, *, run_id: uuid.UUID, identities: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], Source]:
        """Read a bounded batch under the caller's metadata run lock."""
        if not identities:
            return {}
        sources = await self._session.scalars(
            select(Source).where(
                Source.tenant_id == self._tenant_id,
                Source.run_id == run_id,
                tuple_(Source.canonical_url, Source.content_hash).in_(identities),
            )
        )
        return {(source.canonical_url, source.content_hash): source for source in sources}

    async def upsert(
        self,
        *,
        run_id: uuid.UUID,
        sub_question_id: uuid.UUID | None,
        canonical_url: str,
        title: str,
        provider: str,
        source_class: str,
        retrieved_at: datetime,
        content_hash: str,
        artifact_ref: str,
        quality_score: Decimal = Decimal("0"),
        original_url: str | None = None,
        original_urls: list[str] | None = None,
        content_signature: list[str] | None = None,
        published_at: datetime | None = None,
        existing_source: Source | None | _Lookup = _Lookup.REQUIRED,
    ) -> Source:
        # Explicit None is a known miss from find_existing under the run lock.
        # The default retains standalone callers' lookup/uniqueness behavior.
        discoveries = [
            {
                "subQuestionId": str(sub_question_id) if sub_question_id else "",
                "provider": provider,
                "url": url,
            }
            for url in (original_urls or [original_url or canonical_url])
        ][:32]
        existing = existing_source
        if existing is _Lookup.REQUIRED:
            existing = await self._session.scalar(
                select(Source).where(
                    Source.tenant_id == self._tenant_id,
                    Source.run_id == run_id,
                    Source.canonical_url == canonical_url,
                    Source.content_hash == content_hash,
                )
            )
        if isinstance(existing, _Lookup):
            raise ValueError("unknown source lookup mode")
        if existing is not None:
            if (
                existing.tenant_id != self._tenant_id
                or existing.run_id != run_id
                or existing.canonical_url != canonical_url
                or existing.content_hash != content_hash
            ):
                raise ValueError("existing source does not match tenant/run/content identity")
            paths = existing.discovery_paths or []
            existing.discovery_paths = [
                *paths,
                *(path for path in discoveries if path not in paths),
            ][:32]
            return existing
        source = Source(
            tenant_id=self._tenant_id,
            run_id=run_id,
            sub_question_id=sub_question_id,
            canonical_url=canonical_url,
            title=title[:500],
            publisher=None,
            provider=provider,
            source_class=source_class,
            published_at=published_at,
            retrieved_at=retrieved_at,
            content_hash=content_hash,
            artifact_ref=artifact_ref,
            quality_score=quality_score,
            discovery_paths=discoveries,
            content_signature=content_signature or [],
        )
        self._session.add(source)
        await self._session.flush()
        return source
