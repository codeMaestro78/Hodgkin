"""Persist replay identity and write-once results, with no provider I/O.

Use a short tenant_session transaction for each call and commit get_or_create
before performing paid work. A pending row is replay identity, not a worker lease;
the graph's existing provider accounting must deduplicate paid dispatch.

Manifests contain policy snapshots, bounded selected context and source metadata
(IDs, hashes, artifact references, titles and URLs), never raw source bodies.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from research_api.db.assessments import MANIFEST_MAX_BYTES, RESULT_MAX_BYTES, ResearchAssessment


class AssessmentManifestMismatch(ValueError):
    """An evidence key was replayed with different immutable input metadata."""


class AssessmentResultMismatch(ValueError):
    """An assessment already has a different authoritative result."""


def _json_object(value: dict[str, Any], limit: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("assessment payload must be a JSON object")
    try:
        # PostgreSQL's jsonb::text includes spaces; use the same separators for
        # the application guard. The CHECK remains authoritative for size.
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if "\x00" in encoded or "\\u0000" in encoded:
            raise ValueError("JSONB cannot contain NUL")
        if len(encoded.encode("utf-8")) > limit:
            raise ValueError("assessment payload exceeds byte limit")
        snapshot: dict[str, Any] = json.loads(encoded)
    except (TypeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ValueError("assessment payload must be finite JSON") from exc
    return snapshot


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Copy caller-owned JSON and reject source-body fields at any depth.

    Selected context is capped at 8,192 characters per string, additionally bounded by the
    256 KiB whole manifest limit. Store full extraction in the artifact store.
    """
    snapshot = _json_object(manifest, MANIFEST_MAX_BYTES)
    forbidden = {
        "raw_content",
        "raw_text",
        "raw_body",
        "full_body",
        "full_text",
        "body",
        "html",
        "markdown",
        "page_content",
        "text_content",
        "content",
    }

    def check(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in forbidden:
                    raise ValueError("manifest must reference artifacts, not store source bodies")
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
        elif isinstance(value, str) and len(value) > 8192:
            raise ValueError("manifest strings must be bounded to 8192 characters")

    check(snapshot)
    return snapshot


def _json_equal(left: Any, right: Any) -> bool:
    # JSONB distinguishes true from 1; Python's container equality does not.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


class AssessmentRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session, self.tenant_id = session, tenant_id

    async def get_or_create(
        self,
        run_id: uuid.UUID,
        plan_id: uuid.UUID,
        evidence_key: str,
        manifest: dict[str, Any],
    ) -> ResearchAssessment:
        """Return this plan's authoritative row; reject changed evidence on replay."""
        if not isinstance(evidence_key, str) or not 1 <= len(evidence_key) <= 64:
            raise ValueError("evidence_key must contain 1 to 64 characters")
        snapshot = validate_manifest(manifest)
        await self.session.execute(
            insert(ResearchAssessment)
            .values(
                id=uuid.uuid4(),
                tenant_id=self.tenant_id,
                run_id=run_id,
                plan_id=plan_id,
                evidence_key=evidence_key,
                manifest=snapshot,
            )
            # Both plan identity and the full evidence tuple are unique. Handle
            # either conflict, then compare the authoritative row for this plan.
            .on_conflict_do_nothing()
        )
        # A separate statement sees the committed winner after ON CONFLICT waits
        # under PostgreSQL's default READ COMMITTED isolation.
        row = await self.session.scalar(
            select(ResearchAssessment)
            .where(
                ResearchAssessment.tenant_id == self.tenant_id,
                ResearchAssessment.run_id == run_id,
                ResearchAssessment.plan_id == plan_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise LookupError("assessment missing or not visible")
        if row.evidence_key != evidence_key or not _json_equal(row.manifest, snapshot):
            raise AssessmentManifestMismatch(
                "plan already has a different evidence key or manifest"
            )
        return row

    async def complete(
        self, assessment_id: uuid.UUID, result: dict[str, Any]
    ) -> ResearchAssessment:
        """Write a result once, accepting equivalent JSON replays without replacing it."""
        snapshot = _json_object(result, RESULT_MAX_BYTES)
        # Conditional UPDATE serializes only database work. A racing loser reads
        # the authoritative winner and accepts exactly equivalent JSON replay.
        await self.session.execute(
            update(ResearchAssessment)
            .where(
                ResearchAssessment.tenant_id == self.tenant_id,
                ResearchAssessment.id == assessment_id,
                ResearchAssessment.result.is_(None),
            )
            .values(result=snapshot)
            .execution_options(synchronize_session=False)
        )
        row = await self.session.scalar(
            select(ResearchAssessment)
            .where(
                ResearchAssessment.tenant_id == self.tenant_id,
                ResearchAssessment.id == assessment_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise LookupError("assessment missing or not visible")
        if not _json_equal(row.result, snapshot):
            raise AssessmentResultMismatch("assessment already has a different result")
        return row
