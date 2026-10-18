"""Small public projection of evidence-checked draft findings."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select

from research_api.db.models import RunEvent
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.lifecycle import ensure_active, lock_run


async def record_verified_preview(
    *, tenant_id: UUID, run_id: UUID, assessment_id: UUID, findings: list[dict[str, Any]]
) -> None:
    """Commit one bounded preview before optional coverage and narrative model calls.

    The run lock serializes competing resumed workers; the fixed event ID makes
    replay safe after a commit with a lost acknowledgement.
    """
    if not findings:
        return
    event_id = uuid5(assessment_id, "verified-findings-preview:v1")
    async with tenant_session(str(tenant_id)) as session:
        ensure_active(await lock_run(session, tenant_id, run_id))
        existing = await session.scalar(
            select(RunEvent.id).where(
                RunEvent.tenant_id == tenant_id,
                RunEvent.event_id == event_id,
            )
        )
        if existing is not None:
            return
        await EventOutbox(session, tenant_id).append(
            run_id=run_id,
            event_type="assessment.findings_verified",
            event_id=event_id,
            payload={
                "label": "Evidence-checked findings available while the report finishes",
                "assessmentId": str(assessment_id),
                "findings": [
                    {
                        "text": finding["text"],
                        "sourceIds": list(
                            dict.fromkeys(citation["sourceId"] for citation in finding["citations"])
                        )[:4],
                    }
                    for finding in findings[:3]
                ],
                "verifiedClaimCount": len(findings),
            },
        )


def verified_preview(event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if event_type != "assessment.findings_verified":
        return None
    rows = payload.get("findings")
    count = payload.get("verifiedClaimCount")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 3:
        return None
    if type(count) is not int or count < len(rows) or count > 40:
        return None
    findings: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        text = row.get("text")
        sources = row.get("sourceIds")
        if not isinstance(text, str) or not 1 <= len(text) <= 1200:
            return None
        if not isinstance(sources, list) or not 1 <= len(sources) <= 4:
            return None
        try:
            identities = [str(UUID(source)) for source in sources]
        except (TypeError, ValueError, AttributeError):
            return None
        if len(set(identities)) != len(identities):
            return None
        findings.append({"text": text, "sourceIds": identities})
    return {"verifiedFindings": findings, "verifiedClaimCount": count}
