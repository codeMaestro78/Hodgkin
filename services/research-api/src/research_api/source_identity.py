"""Pure, conservative identity mapping from observed evidence; no network or ORM."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID

MAX_LINK_SOURCES = 20
RelationshipKind = Literal["same_content", "same_work", "same_publisher"]


def doi_work_id(url: str) -> str | None:
    """Accept only an actually observed HTTP(S) DOI resolver URL, not page text."""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.hostname not in {"doi.org", "dx.doi.org"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            return None
    except ValueError:
        return None
    doi = unquote(parsed.path.removeprefix("/")).lower()
    if not re.fullmatch(r"10\.\d{4,9}/[^\s\x00-\x1f\x7f]+", doi):
        return None
    return f"doi:{doi}" if len(doi) <= 2044 else None


@dataclass(frozen=True)
class SourceIdentity:
    work_id: str | None
    publisher: str | None
    metadata_basis: dict[str, object]
    source_class: Literal["unknown"] = "unknown"
    independence: Literal["unknown"] = "unknown"


def map_source_identity(
    *,
    canonical_url: str,
    observed_urls: Sequence[str] = (),
    publisher: str | None = None,
    publisher_basis: Mapping[str, object] | None = None,
) -> SourceIdentity:
    """Caller supplies observed URLs and verified publisher metadata, never planner wishes.

    A resolver URL identifies a work; it does not establish source class, ownership,
    peer review, independence, or that the fetched page substantively supports it.
    Conflicting observed DOIs deliberately leave work identity unresolved.
    """
    urls = sorted(set((canonical_url, *observed_urls[:32])))
    doi_urls = [url for url in urls if doi_work_id(url) is not None]
    works = {doi_work_id(url) for url in doi_urls}
    metadata: dict[str, object] = {}
    work_id = next(iter(works)) if len(works) == 1 else None
    if doi_urls:
        metadata["work"] = {"basis": "observed_doi_url", "urls": doi_urls}
    verified_publisher = None
    if publisher and publisher.strip() and publisher_basis:
        evidence = publisher_basis.get("evidence_ref")
        if (
            publisher_basis.get("basis") in {"structured_metadata", "adapter_metadata"}
            and isinstance(evidence, str)
            and evidence.strip()
            and len(publisher.strip()) <= 250
        ):
            verified_publisher = publisher.strip()
            metadata["publisher"] = {
                "basis": publisher_basis["basis"],
                "evidence_ref": evidence,
                "value": verified_publisher,
            }
    return SourceIdentity(work_id, verified_publisher, metadata)


@dataclass(frozen=True)
class RelationshipSource:
    id: UUID
    content_hash: str
    identity: SourceIdentity


@dataclass(frozen=True)
class ObservedRelationship:
    from_source_id: UUID
    to_source_id: UUID
    kind: RelationshipKind
    basis: dict[str, object]


def _verified_identity(identity: SourceIdentity) -> SourceIdentity:
    """Revalidate evidence even if a caller constructed the dataclass directly."""
    work = identity.metadata_basis.get("work")
    urls = work.get("urls", []) if isinstance(work, Mapping) else []
    if not isinstance(urls, list) or not isinstance(work, Mapping):
        urls = []
    elif work.get("basis") != "observed_doi_url":
        urls = []
    publisher = identity.metadata_basis.get("publisher")
    if not isinstance(publisher, Mapping) or publisher.get("value") != identity.publisher:
        publisher = None
    urls = [url for url in urls if isinstance(url, str)]
    return map_source_identity(
        canonical_url=urls[0] if urls else "",
        observed_urls=urls[1:],
        publisher=identity.publisher,
        publisher_basis=publisher,
    )


def observed_relationships(sources: Sequence[RelationshipSource]) -> list[ObservedRelationship]:
    """At most 190 unordered pairs, each with up to three independent observations."""
    if len(sources) > MAX_LINK_SOURCES:
        raise ValueError("relationship linking accepts at most 20 sources")
    if len({source.id for source in sources}) != len(sources):
        raise ValueError("relationship sources must have distinct IDs")
    sources = [
        RelationshipSource(source.id, source.content_hash, _verified_identity(source.identity))
        for source in sources
    ]
    relationships = []
    for left, right in combinations(sorted(sources, key=lambda source: source.id), 2):
        observations: list[tuple[RelationshipKind, dict[str, object]]] = []
        if (
            re.fullmatch(r"[0-9a-f]{64}", left.content_hash)
            and left.content_hash == right.content_hash
        ):
            observations.append(("same_content", {"content_hash": left.content_hash}))
        if left.identity.work_id and left.identity.work_id == right.identity.work_id:
            observations.append(
                (
                    "same_work",
                    {
                        "work_id": left.identity.work_id,
                        "from": left.identity.metadata_basis.get("work"),
                        "to": right.identity.metadata_basis.get("work"),
                    },
                )
            )
        if left.identity.publisher and left.identity.publisher == right.identity.publisher:
            observations.append(
                (
                    "same_publisher",
                    {
                        "publisher": left.identity.publisher,
                        "from": left.identity.metadata_basis.get("publisher"),
                        "to": right.identity.metadata_basis.get("publisher"),
                    },
                )
            )
        for kind, evidence in observations:
            relationships.append(
                ObservedRelationship(
                    left.id, right.id, kind, {"version": "source-identity-v1", **evidence}
                )
            )
    return relationships
