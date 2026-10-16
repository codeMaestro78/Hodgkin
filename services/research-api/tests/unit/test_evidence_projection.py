import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api import api
from research_api.snapshots import SnapshotCollections


def claim():
    return SimpleNamespace(
        id=uuid.uuid4(),
        claim="An inspectable claim",
        caveats=["A limitation"],
        provenance={"private": "never exposed"},
    )


def citation(**verification):
    return SimpleNamespace(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        quote="Exact stored evidence.",
        verification=verification,
        locator={"internal": "private"},
    )


def test_projection_groups_quotes_and_exposes_only_named_fields():
    item = claim()
    first = citation(
        exactSpan={"verified": True, "evidenceArtifactHash": "private"},
        semanticSupport={"verdict": "partially_supports", "confidence": 0.7},
    )
    checks = api._public_claim_checks([(item, first), (item, citation())])
    assert len(checks) == 1
    assert len(checks[0]["citations"]) == 2
    projected = checks[0]["citations"][0]
    assert projected["exactSpanVerified"] is True
    assert projected["verdict"] == "partially_supports"
    assert "private" not in str(checks)
    assert "confidence" not in str(checks)


@pytest.mark.parametrize(
    "verification",
    [{}, {"exactSpan": {"verified": "true"}}, {"exactSpan": None, "semanticSupport": None}],
)
def test_missing_or_malformed_checks_do_not_imply_verification(verification):
    checks = api._public_claim_checks([(claim(), citation(**verification))])
    assert checks[0]["citations"][0]["exactSpanVerified"] is False
    assert checks[0]["citations"][0]["verdict"] == "not_recorded"


def test_claim_without_citations_is_preserved_without_inventing_a_check():
    assert api._public_claim_checks([(claim(), None)])[0]["citations"] == []


@pytest.mark.asyncio
async def test_run_projection_queries_evidence_for_verified_tenant_and_requested_run(monkeypatch):
    tenant, user, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    run = SimpleNamespace(
        id=run_id,
        status="completed",
        original_question="Compare evidence platforms",
        report_requirements=[],
        plan_version=1,
        error_code=None,
        created_at=now,
        updated_at=now,
        approval_required=False,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    first=lambda: (
                        run,
                        SimpleNamespace(
                            max_search_calls=6, max_estimated_cost_usd=1, max_wall_clock_ms=180_000
                        ),
                        SimpleNamespace(search_calls=2),
                        0,
                    )
                ),
                [],
            ]
        ),
        scalars=AsyncMock(return_value=[]),
    )

    @asynccontextmanager
    async def context(actual_tenant):
        assert actual_tenant == str(tenant)
        yield session

    monkeypatch.setattr(api, "tenant_session", context)
    collections = AsyncMock(return_value=SnapshotCollections([], [], [], [], [], [], [], []))
    monkeypatch.setattr(api, "load_collections", collections)
    monkeypatch.setattr(
        api, "_caller", AsyncMock(return_value=SimpleNamespace(tenant_id=tenant, user_id=user))
    )
    result = await api.get_research_run(run_id)
    assert result["claimChecks"] == []
    collections.assert_awaited_once_with(session, tenant, run_id)
    statement = session.execute.call_args.args[0]
    params = list(statement.compile().params.values())
    assert params.count(tenant) == 2
    assert params.count(run_id) == 2
    assert "LEFT OUTER JOIN citations" in str(statement)


@pytest.mark.asyncio
async def test_reports_filter_is_bounded_and_keeps_owner_predicates(monkeypatch):
    tenant, user = uuid.uuid4(), uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock(return_value=[]))

    @asynccontextmanager
    async def context(_tenant):
        yield session

    monkeypatch.setattr(api, "tenant_session", context)
    monkeypatch.setattr(
        api, "_caller", AsyncMock(return_value=SimpleNamespace(tenant_id=tenant, user_id=user))
    )
    assert await api.list_research_runs(reports_only=True) == {"runs": []}
    assert session.execute.await_count == 1
    statement = session.execute.call_args.args[0]
    params = list(statement.compile().params.values())
    assert tenant in params and user in params and "completed" in params and 100 in params
    assert "report_id IS NOT NULL" in str(statement)
