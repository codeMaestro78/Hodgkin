from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import Source


class SourceRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

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
    ) -> Source:
        discoveries = [
            {
                "subQuestionId": str(sub_question_id) if sub_question_id else "",
                "provider": provider,
                "url": url,
            }
            for url in (original_urls or [original_url or canonical_url])
        ][:32]
        existing = await self._session.scalar(
            select(Source).where(
                Source.tenant_id == self._tenant_id,
                Source.run_id == run_id,
                Source.canonical_url == canonical_url,
                Source.content_hash == content_hash,
            )
        )
        if existing is not None:
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
