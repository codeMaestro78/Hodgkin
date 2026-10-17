"""Bounded identity and relationship persistence in the caller's tenant transaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.models import Source
from research_api.db.source_relationships import SourceIdentityRecord, SourceRelationship
from research_api.source_identity import (
    MAX_LINK_SOURCES,
    RelationshipSource,
    SourceIdentity,
    doi_work_id,
    map_source_identity,
    observed_relationships,
)


def _identity(
    source: Source, supplied: SourceIdentity | SourceIdentityRecord | None
) -> SourceIdentity:
    metadata = supplied.metadata_basis if supplied else {}
    work = metadata.get("work", {})
    stored_urls = work.get("urls", []) if isinstance(work, Mapping) else []
    urls = stored_urls if isinstance(stored_urls, list) else []
    # Discovery paths are persisted observations of this source, not arbitrary
    # DOI references in its body. They do not establish source class or ownership.
    discovered = [
        path["url"]
        for path in (source.discovery_paths or [])[:32]
        if isinstance(path, dict) and isinstance(path.get("url"), str)
    ]
    publisher_basis = metadata.get("publisher")
    publisher = supplied.publisher if supplied else None
    if not isinstance(publisher_basis, Mapping) or publisher_basis.get("value") != publisher:
        publisher_basis = None
    return map_source_identity(
        canonical_url=source.canonical_url,
        observed_urls=[url for url in urls if isinstance(url, str)][:32] + discovered,
        publisher=publisher,
        publisher_basis=publisher_basis,
    )


class SourceRelationshipRepository:
    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def link_sources(
        self,
        *,
        run_id: UUID,
        source_ids: Sequence[UUID],
        observed_identities: Mapping[UUID, SourceIdentity] | None = None,
    ) -> int:
        """Link <=20 distinct persisted sources. Never commit or modify Source rows.

        Supply observations only for newly extracted sources. Identity records
        are insert-only; replay preserves their first basis. Existing Source rows
        are never updated. Missing or out-of-scope IDs reject the whole batch.
        """
        if len(source_ids) > MAX_LINK_SOURCES or len(set(source_ids)) != len(source_ids):
            raise ValueError("provide at most 20 distinct source IDs")
        if observed_identities and not set(observed_identities).issubset(source_ids):
            raise ValueError("observed identities must belong to the source batch")
        if not source_ids:
            return 0
        sources = list(
            await self._session.scalars(
                select(Source).where(
                    Source.tenant_id == self._tenant_id,
                    Source.run_id == run_id,
                    Source.id.in_(source_ids),
                )
            )
        )
        if len(sources) != len(source_ids):
            raise ValueError("source IDs must all belong to the caller's tenant and run")
        return await self._persist(run_id, sources, observed_identities or {})

    async def report_projection(
        self, *, run_id: UUID, source_ids: Sequence[UUID]
    ) -> list[dict[str, object]]:
        """Read only persisted relationships whose two endpoints are cited in this report."""
        selected = set(source_ids)
        if len(selected) != len(source_ids) or len(selected) > MAX_LINK_SOURCES:
            raise ValueError("report provenance requires at most 20 distinct sources")
        if not selected:
            return []
        rows = list(
            await self._session.scalars(
                select(SourceRelationship)
                .where(
                    SourceRelationship.tenant_id == self._tenant_id,
                    SourceRelationship.run_id == run_id,
                    SourceRelationship.from_source_id.in_(selected),
                    SourceRelationship.to_source_id.in_(selected),
                )
                .order_by(
                    SourceRelationship.from_source_id,
                    SourceRelationship.to_source_id,
                    SourceRelationship.kind,
                )
            )
        )
        return [project_relationship_for_report(row) for row in rows]

    async def _persist(
        self,
        run_id: UUID,
        sources: Sequence[Source],
        observed_identities: Mapping[UUID, SourceIdentity],
    ) -> int:
        if not sources:
            return 0
        # Record only explicitly supplied new-extraction metadata. No old-row
        # identity backfill; ordinary linking can derive DOI from existing URLs.
        values = []
        for source in sources:
            if source.id in observed_identities:
                identity = _identity(source, observed_identities[source.id])
                values.append(
                    {
                        "tenant_id": self._tenant_id,
                        "run_id": run_id,
                        "source_id": source.id,
                        "work_id": identity.work_id,
                        "publisher": identity.publisher,
                        "metadata_basis": identity.metadata_basis,
                    }
                )
        if values:
            await self._session.execute(
                insert(SourceIdentityRecord)
                .values(values)
                .on_conflict_do_nothing(index_elements=["tenant_id", "run_id", "source_id"])
            )
        # Re-read first-writer observations so replay cannot use new conflicting
        # metadata to add a relationship that the identity record does not support.
        records = {
            row.source_id: row
            for row in await self._session.scalars(
                select(SourceIdentityRecord).where(
                    SourceIdentityRecord.tenant_id == self._tenant_id,
                    SourceIdentityRecord.run_id == run_id,
                    SourceIdentityRecord.source_id.in_([source.id for source in sources]),
                )
            )
        }
        relationships = observed_relationships(
            [
                RelationshipSource(
                    source.id, source.content_hash, _identity(source, records.get(source.id))
                )
                for source in sources
            ]
        )
        if not relationships:
            return 0
        result = await self._session.scalars(
            insert(SourceRelationship)
            .values(
                [
                    {
                        "tenant_id": self._tenant_id,
                        "run_id": run_id,
                        "from_source_id": row.from_source_id,
                        "to_source_id": row.to_source_id,
                        "kind": row.kind,
                        "basis": row.basis,
                        "confidence": "observed",
                    }
                    for row in relationships
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "tenant_id",
                    "run_id",
                    "from_source_id",
                    "to_source_id",
                    "kind",
                ]
            )
            .returning(SourceRelationship.kind)
        )
        return len(result.all())


def project_relationship_for_report(row: SourceRelationship) -> dict[str, object]:
    """Drop private content hashes and internal metadata refs from public provenance."""
    result: dict[str, object] = {
        "fromSourceId": str(row.from_source_id),
        "toSourceId": str(row.to_source_id),
        "kind": row.kind,
        "confidence": row.confidence,
    }
    if row.kind == "same_content":
        result["basis"] = "observed_content_hash_match"
    elif row.kind == "same_work":
        identifier = row.basis.get("work_id")
        observed_doi_url = (
            "https://doi.org/" + identifier.removeprefix("doi:")
            if isinstance(identifier, str)
            else ""
        )
        if doi_work_id(observed_doi_url) is None:
            raise ValueError("Persisted work relationship has no valid observed DOI")
        result.update(basis="observed_doi_match", identifier=identifier)
    elif row.kind == "same_publisher":
        identifier = row.basis.get("publisher")
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 250:
            raise ValueError("Persisted publisher relationship has no valid observed publisher")
        result.update(basis="verified_publisher_metadata_match", identifier=identifier)
    else:
        raise ValueError("Unknown persisted source relationship kind")
    return result


async def persist_source_relationships(
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    *,
    observed_identities: Mapping[UUID, SourceIdentity] | None = None,
) -> int:
    """Link the current admitted run batch, rejecting >20 rather than truncating.

    Main calls this after successful source admission/flush in the same tenant
    transaction. This imports/registers both models; it does not apply schema.
    """
    sources = list(
        await session.scalars(
            select(Source)
            .where(
                Source.tenant_id == tenant_id,
                Source.run_id == run_id,
            )
            .order_by(Source.id)
            .limit(MAX_LINK_SOURCES + 1)
        )
    )
    if len(sources) > MAX_LINK_SOURCES:
        raise ValueError("relationship linking accepts at most 20 sources")
    identities = observed_identities or {}
    if not set(identities).issubset(source.id for source in sources):
        raise ValueError("observed identities must belong to the source batch")
    return await SourceRelationshipRepository(session, tenant_id)._persist(
        run_id, sources, identities
    )
