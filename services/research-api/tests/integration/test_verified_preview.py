"""Preview event is durable and emitted only once under concurrent resume."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from test_durable_runtime import seed

from research_api.db.models import RunEvent
from research_api.db.session import tenant_session
from research_api.verified_preview import record_verified_preview, verified_preview

pytestmark = pytest.mark.integration


async def test_concurrent_resume_emits_one_checked_preview(monkeypatch):
    tenant, _, run_id, _ = await seed(monkeypatch)
    assessment_id, source_id = uuid.uuid4(), uuid.uuid4()
    findings = [
        {
            "text": "The source supports this finding.",
            "citations": [
                {"sourceId": str(source_id)},
                {"sourceId": str(source_id)},
            ],
        }
    ]
    await asyncio.gather(
        *(
            record_verified_preview(
                tenant_id=tenant,
                run_id=run_id,
                assessment_id=assessment_id,
                findings=findings,
            )
            for _ in range(3)
        )
    )
    await record_verified_preview(
        tenant_id=tenant,
        run_id=run_id,
        assessment_id=assessment_id,
        findings=findings,
    )
    async with tenant_session(str(tenant)) as session:
        events = list(
            await session.scalars(
                select(RunEvent).where(
                    RunEvent.tenant_id == tenant,
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "assessment.findings_verified",
                )
            )
        )
    assert len(events) == 1
    assert verified_preview(events[0].event_type, events[0].payload) == {
        "verifiedFindings": [
            {"text": "The source supports this finding.", "sourceIds": [str(source_id)]}
        ],
        "verifiedClaimCount": 1,
    }
