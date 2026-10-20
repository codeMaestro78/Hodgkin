"""Local PostgreSQL, real model receipts/checkpoints, fake SDK/artifact/provider IO.

Run only on the loopback database enforced by conftest, migrated through 0019.
No hosted/provider calls or migrations are performed by this suite.
"""

import asyncio
import copy
import hashlib
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from research_api import jobs
from research_api.config import Settings
from research_api.coverage import CoverageResult
from research_api.db.assessments import ResearchAssessment
from research_api.db.models import (
    Citation,
    EvidenceClaim,
    ProviderCall,
    ProviderCallReservation,
    Report,
    ResearchGap,
    ResearchRun,
    RunEvent,
    RuntimeJob,
    Source,
    SubQuestion,
    UsageLedger,
)
from research_api.db.session import tenant_session
from research_api.graph import builder
from research_api.mode_policy import MODE_POLICY_VERSION, resolve_mode_budget
from research_api.repositories.budgets import BudgetExceededError
from research_api.repositories.runs import RunRepository
from research_api.runtime_context import LeaseLostError
from research_api.schemas.generated.agent_event import AgentEvent
from tests.integration.test_reliability_runtime import seed

pytestmark = pytest.mark.integration
QUOTE = "The service preserves workflow state in durable storage."
CLAIM = "The service preserves workflow state."
NARRATIVE_CLAIM = "Workflow state is kept in durable storage by the service."


class Checkpointer(InMemorySaver):
    def __init__(self, thread_id):
        super().__init__()
        self.thread_id = thread_id

    def config(self):
        return {"configurable": {"thread_id": self.thread_id}}


@pytest.fixture
async def harness(monkeypatch):
    tenant, user, _ = await seed()
    async with tenant_session(str(tenant)) as session:
        run = await RunRepository(session, tenant).create(
            user_id=user,
            question="Explain workflow state preservation",
            mode="focused",
            mode_policy_version=MODE_POLICY_VERSION,
            budget=resolve_mode_budget("focused"),
        )
        run_id = run.id
    settings = Settings(
        _env_file=None, OPENAI_API_KEY="fixture", TAVILY_API_KEY="fixture", PROVIDER_MAX_ATTEMPTS=1
    )
    planner = AsyncMock(
        return_value=builder.PlannerOutput(
            sub_questions=[
                builder.PlannedQuestion(
                    question="Find original evidence for workflow state preservation",
                    rationale="Inspect preserved evidence",
                    success_criteria=["Establish state preservation"],
                    source_classes=["primary", "secondary"],
                )
            ]
        )
    )
    monkeypatch.setattr(builder, "_plan_with_openai", planner)
    bodies = {"fixture": QUOTE.encode()}

    class Store:
        def __init__(self, **kwargs):
            pass

        async def get_for_verification(self, *, artifact_ref):
            return bodies[artifact_ref]

    monkeypatch.setattr(builder, "S3ArtifactStore", Store)
    ingestion_queries = []

    class Ingestor:
        def __init__(self, **kwargs):
            pass

        async def ingest(self, **kwargs):
            ingestion_queries.append(kwargs["query"])
            async with tenant_session(str(tenant)) as session:
                source = Source(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    run_id=run_id,
                    sub_question_id=kwargs["sub_question_id"],
                    canonical_url="https://example.test/evidence",
                    title="Preserved evidence",
                    provider="tavily",
                    source_class="unknown",
                    retrieved_at=datetime.now(UTC),
                    content_hash=hashlib.sha256(QUOTE.encode()).hexdigest(),
                    artifact_ref="fixture",
                    discovery_paths=[],
                    content_signature=[],
                )
                session.add(source)
                await session.flush()
                return [source.id]

    monkeypatch.setattr(builder, "TavilyEvidenceIngestor", Ingestor)
    dispatches = []
    criterion_failure = []
    controls = {
        "citation": {"source_number": 1, "passage_id": "s1_p1"},
        "verdict": "supports",
        "narrative": None,
        "narrative_verdict": None,
    }

    def narrative(inputs):
        passage = inputs["literal_passages"][0]
        return {
            "blocks": [
                {
                    "role": "answer",
                    "dimension": "none",
                    "sentences": [
                        {
                            "finding": inputs["verified_findings"][0]["key"],
                            "claim": "",
                            "citations": [],
                        },
                        {
                            "finding": "new",
                            "claim": NARRATIVE_CLAIM,
                            "citations": [
                                {
                                    "source_number": passage["source_number"],
                                    "passage_id": passage["passages"][0]["passage_id"],
                                }
                            ],
                        },
                    ],
                }
            ]
        }

    async def create(**request):
        name = request["text"]["format"]["name"]
        dispatches.append(name)
        if name.endswith("_claim_draft_passages_v2"):
            result = {
                "claims": [
                    {
                        "claim": CLAIM,
                        "section": "mechanisms",
                        "figures": [],
                        "caveats": [],
                        "citations": [controls["citation"]],
                    }
                ]
            }
            if "technical_results" in request["text"]["format"]["schema"]["properties"]:
                result["technical_results"] = [{
                    "kind": "method",
                    "title": "workflow state",
                    "claim_index": 0,
                    "citation_index": 0,
                    "assumptions": [],
                    "notation": [],
                    "source_expression": None,
                    "representation": None,
                    "source_location": None,
                }]
        elif name in {
            "citation_semantic_reviews_batched_v1",
            "citation_semantic_reviews_scoped_v2",
        }:
            inputs = json.loads(request["input"])
            result = {
                "reviews": [
                    {
                        "claim_index": item["claimIndex"],
                        "citation_index": citation["citationIndex"],
                        "verdict": controls["narrative_verdict"]
                        if item["claim"] == NARRATIVE_CLAIM and controls.get("narrative_verdict")
                        else controls["verdict"],
                        "confidence": 0.9,
                    }
                    for item in inputs
                    for citation in item["citations"]
                ]
            }
        elif name in {"criterion_review_v1", "criterion_review_v2"}:
            if criterion_failure:
                raise criterion_failure[0]
            inputs = json.loads(request["input"])
            result = {
                "assessments": [
                    {
                        "dimension_id": dim["dimension_id"],
                        "criterion_id": criterion["id"],
                        "outcome": "met",
                        "claim_ids": [inputs["verified_claims"][0]["id"]],
                    }
                    for dim in inputs["dimensions"]
                    for criterion in dim["criteria"]
                ],
                "comparisons": [],
            }
            if name == "criterion_review_v2":
                result["conflicts"] = []
        elif name == "focused_evidence_narrative_v1":
            result = (controls["narrative"] or narrative)(json.loads(request["input"]))
        else:
            raise AssertionError(f"Unexpected model dispatch {name}")
        return SimpleNamespace(
            output_text=json.dumps(result),
            id="fixture-model-response",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=10,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
        )

    sdk = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(side_effect=create)), close=AsyncMock()
    )
    monkeypatch.setattr(builder, "AsyncOpenAI", Mock(return_value=sdk))
    checkpointer = Checkpointer(f"{tenant}:{run_id}")

    async def execute():
        await builder.run_graph(
            settings,
            tenant_id=tenant,
            user_id=user,
            run_id=run_id,
            question="Explain workflow state preservation",
            checkpointer=checkpointer,
        )

    async def snapshot():
        async with tenant_session(str(tenant)) as session:
            run = await session.get(ResearchRun, run_id)
            report = await session.scalar(select(Report).where(Report.run_id == run_id))
            assessment = await session.scalar(
                select(ResearchAssessment).where(
                    ResearchAssessment.tenant_id == tenant, ResearchAssessment.run_id == run_id
                )
            )
            usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run_id))
            calls = list(
                await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run_id))
            )
        return run, report, assessment, usage, calls

    return SimpleNamespace(
        tenant=tenant,
        user=user,
        run_id=run_id,
        settings=settings,
        execute=execute,
        snapshot=snapshot,
        planner=planner,
        dispatches=dispatches,
        bodies=bodies,
        criterion_failure=criterion_failure,
        ingestion_queries=ingestion_queries,
        checkpointer=checkpointer,
        controls=controls,
    )


async def test_opt_in_technical_ledger_publishes_v5_without_changing_v4_runs(harness):
    harness.settings.TECHNICAL_RESULTS_ENABLED = True
    await harness.execute()
    run, report, assessment, _usage, _calls = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["version"] == 5
    assert len(report.document["technicalResults"]) == 1
    assert report.document["technicalResults"][0]["claimId"] == report.document["findings"][0]["id"]
    assert assessment.result["technical_results"][0]["status"] == "supported"
    assert "citation_semantic_reviews_scoped_v2" in harness.dispatches


async def test_technical_writer_receipt_replays_without_paid_redispatch(harness, monkeypatch):
    harness.settings.TECHNICAL_RESULTS_ENABLED = True
    original = builder.exact_reviews
    crashed = False

    async def interrupt_once(*args, **kwargs):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise asyncio.CancelledError
        return await original(*args, **kwargs)

    monkeypatch.setattr(builder, "exact_reviews", interrupt_once)
    with pytest.raises(asyncio.CancelledError):
        await harness.execute()
    before = list(harness.dispatches)
    await harness.execute()
    run, report, assessment, _usage, _calls = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["version"] == 5
    assert assessment.result["technical_results"][0]["status"] == "supported"
    assert harness.dispatches.count("focused_claim_draft_passages_v2") == 1
    assert len(harness.dispatches) > len(before)


async def test_completed_technical_receipt_is_write_once_and_replays(harness, monkeypatch):
    harness.settings.TECHNICAL_RESULTS_ENABLED = True
    original_event = builder.operation_event
    interrupted = False

    def interrupt_after_assessment(name, **kwargs):
        nonlocal interrupted
        if name == "node.assess_evidence" and not interrupted:
            interrupted = True
            raise asyncio.CancelledError
        return original_event(name, **kwargs)

    monkeypatch.setattr(builder, "operation_event", interrupt_after_assessment)
    with pytest.raises(asyncio.CancelledError):
        await harness.execute()
    with pytest.raises(IntegrityError, match="write-once"):
        async with tenant_session(str(harness.tenant)) as session:
            assessment = await session.scalar(select(ResearchAssessment).where(
                ResearchAssessment.run_id == harness.run_id
            ))
            changed = copy.deepcopy(assessment.result)
            changed["technical_results"][0]["result"]["title"] = "Fabricated title"
            assessment.result = changed
    await harness.execute()
    run, report, _assessment, _usage, _calls = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["technicalResults"][0]["title"] == "workflow state"


async def test_complete_assessment_publishes_matching_ids_without_another_writer(harness):
    await harness.execute()
    run, report, assessment, usage, calls = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["version"] == 4
    assert report.document["sourceIndependence"]["status"] == "unknown"
    assert report.document["conflicts"] == []
    assert CLAIM in report.markdown
    assert NARRATIVE_CLAIM + " [1]" in report.markdown
    assert len(harness.dispatches) == len(calls) == 5
    assert harness.dispatches.count("focused_claim_draft_passages_v2") == 1
    assert harness.dispatches.count("focused_evidence_narrative_v1") == 1
    assert harness.dispatches.count("citation_semantic_reviews_batched_v1") == 2
    assert assessment.result["repair_status"] == builder.EXPLICIT_REPAIR_STATUS
    assert assessment.manifest["coverage_plan"]["repair_operations_reserved"] == 0
    assert assessment.manifest["coverage_plan"]["repair_sources_reserved"] == 0
    assert assessment.result["repair_decision"]["proposals"] == []
    claim_id = uuid.uuid5(assessment.id, "claim:0")
    citation_id = uuid.uuid5(claim_id, "citation:0")
    assert report.document["findings"][0]["id"] == str(claim_id)
    assert report.document["findings"][0]["citationIds"] == [str(citation_id)]
    narrative_id = uuid.uuid5(assessment.id, "narrative-claim:0")
    narrative_citation = uuid.uuid5(narrative_id, "citation:0")
    assert report.document["findings"][1]["id"] == str(narrative_id)
    assert report.document["findings"][1]["text"] == NARRATIVE_CLAIM
    assert report.document["narrative"] == {
        "basis": "narrative-composition-v1",
        "status": "composed",
        "reason": None,
        "blocks": [
            {
                "id": "narrative-1",
                "role": "answer",
                "dimensionId": None,
                "sentences": [
                    {
                        "claimId": str(claim_id),
                        "citationIds": [str(citation_id)],
                        "origin": "ledger",
                    },
                    {
                        "claimId": str(narrative_id),
                        "citationIds": [str(narrative_citation)],
                        "origin": "narrative",
                    },
                ],
            }
        ],
        "narrativeClaimIds": [str(narrative_id)],
        "proposedSentenceCount": 2,
        "publishedSentenceCount": 2,
        "rejectedSentenceCount": 0,
    }
    assert "## Direct answer" in report.markdown
    async with tenant_session(str(harness.tenant)) as session:
        assert (await session.get(EvidenceClaim, claim_id)).support == "supported"
        assert (await session.get(Citation, citation_id)).quote == QUOTE
        narrative_claim = await session.get(EvidenceClaim, narrative_id)
        assert narrative_claim.support == "supported"
        assert narrative_claim.provenance["createdBy"] == "narrative-composer"
        assert narrative_claim.provenance["publishedInReport"] == "true"
        assert (await session.get(Citation, narrative_citation)).quote == QUOTE
        question = await session.scalar(
            select(SubQuestion).where(SubQuestion.run_id == harness.run_id)
        )
        source = await session.scalar(select(Source).where(Source.run_id == harness.run_id))
    assert question.payload["dispatchQuery"] == harness.ingestion_queries[0]
    assert "primary documentation" in question.payload["dispatchQuery"]
    assert "secondary analysis" in question.payload["dispatchQuery"]
    assert source.source_class == "unknown"
    assert usage.input_tokens == usage.output_tokens == 50
    with pytest.raises(asyncio.CancelledError):
        await harness.execute()
    assert len(harness.dispatches) == 5


@pytest.mark.parametrize(
    "crash_after", ["writer_receipt", "narrative_receipt", "assessment_commit"]
)
async def test_crash_replays_receipts_or_committed_assessment_without_added_dispatch(
    harness, monkeypatch, crash_after
):
    crashed = False
    if crash_after in {"writer_receipt", "narrative_receipt"}:
        original = builder.exact_reviews
        # The narrative's claims are reviewed in the second exact-review call.
        crash_on = 1 if crash_after == "writer_receipt" else 2
        review_calls = 0

        async def reviews(*args, **kwargs):
            nonlocal crashed, review_calls
            review_calls += 1
            if not crashed and review_calls == crash_on:
                crashed = True
                raise asyncio.CancelledError
            return await original(*args, **kwargs)

        monkeypatch.setattr(builder, "exact_reviews", reviews)
    else:
        original_event = builder.operation_event

        def event(name, **kwargs):
            nonlocal crashed
            if name == "node.assess_evidence" and not crashed:
                crashed = True
                raise asyncio.CancelledError
            return original_event(name, **kwargs)

        monkeypatch.setattr(builder, "operation_event", event)
    with pytest.raises(asyncio.CancelledError):
        await harness.execute()
    _, _, before, _, _ = await harness.snapshot()
    assert before is not None
    before_key, before_manifest = before.evidence_key, copy.deepcopy(before.manifest)
    # A fresh graph invocation uses the same saved checkpoint and receipt ledger.
    await harness.execute()
    run, report, after, usage, calls = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["version"] == 4
    assert report.document["narrative"]["status"] == "composed"
    assert NARRATIVE_CLAIM in report.markdown
    assert after.evidence_key == before_key and after.manifest == before_manifest
    assert harness.planner.await_count == 1 and len(harness.ingestion_queries) == 1
    assert len(harness.dispatches) == len(calls) == 5
    assert len({call.request_fingerprint for call in calls}) == 5
    assert usage.input_tokens == usage.output_tokens == 50


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("private upstream detail"),
        BudgetExceededError("private budget detail"),
        TimeoutError("private provider timeout"),
    ],
)
async def test_optional_criterion_failure_keeps_exact_findings_and_unknown_coverage(
    harness, failure
):
    harness.criterion_failure.append(failure)
    await harness.execute()
    run, report, assessment, _, calls = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert CLAIM in report.markdown
    assert [finding["text"] for finding in report.document["findings"]] == [
        CLAIM,
        NARRATIVE_CLAIM,
    ]
    assert assessment.result["criterion_review_failure"] == type(failure).__name__
    assert "private" not in json.dumps(assessment.result)
    coverage = CoverageResult.model_validate(assessment.result["coverage"])
    assert all(row.state != "verified_covered" for row in coverage.dimensions)
    assert all(
        criterion.outcome == "unknown" for row in coverage.dimensions for criterion in row.criteria
    )
    assert assessment.result["repair_decision"]["proposals"] == []
    # Narrative composition still orders the verified ledger without coverage claims.
    assert len(harness.dispatches) == len(calls) == 5
    assert any(call.outcome == "uncertain" for call in calls)
    async with tenant_session(str(harness.tenant)) as session:
        reservations = list(
            await session.scalars(
                select(ProviderCallReservation).where(
                    ProviderCallReservation.run_id == harness.run_id
                )
            )
        )
    assert sum(row.state == "uncertain" for row in reservations) == 1


async def test_near_deadline_publishes_verified_report_without_optional_criterion_call(harness):
    await builder.run_graph(
        harness.settings,
        tenant_id=harness.tenant,
        user_id=harness.user,
        run_id=harness.run_id,
        question="Explain workflow state preservation",
        checkpointer=harness.checkpointer,
        remaining_ms=60_000,
    )
    run, report, assessment, _, calls = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report is not None and CLAIM in report.markdown
    assert assessment.result["criterion_review_failure"] == "insufficient_time"
    assert "criterion_review_v2" not in harness.dispatches
    assert all(call.outcome != "uncertain" for call in calls)
    coverage = CoverageResult.model_validate(assessment.result["coverage"])
    assert all(
        criterion.outcome == "unknown" for row in coverage.dimensions for criterion in row.criteria
    )


@pytest.mark.parametrize("failure", [asyncio.CancelledError(), LeaseLostError("stale owner")])
async def test_criterion_cancellation_and_lease_loss_propagate(harness, failure):
    harness.criterion_failure.append(failure)
    with pytest.raises(type(failure)):
        await harness.execute()
    run, report, assessment, _, _ = await harness.snapshot()
    assert run.status != "completed" and report is None and assessment.result is None


async def test_uncertain_criterion_receipt_is_not_redispatched_after_interruption(
    harness, monkeypatch
):
    harness.criterion_failure.append(RuntimeError("uncertain remote dispatch"))
    original = builder._assessment_repair_decision
    interrupted = False

    async def decision(*args, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise asyncio.CancelledError
        return await original(*args, **kwargs)

    monkeypatch.setattr(builder, "_assessment_repair_decision", decision)
    with pytest.raises(asyncio.CancelledError):
        await harness.execute()
    await harness.execute()
    run, report, assessment, _, _ = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert CLAIM in report.markdown
    assert len(harness.dispatches) == 5
    assert harness.dispatches.count("criterion_review_v2") == 1
    assert assessment.result["criterion_review_failure"] == "ReservationReplayError"


async def test_changed_pinned_artifact_fails_recovery_before_any_new_paid_dispatch(
    harness, monkeypatch
):
    original = builder.exact_reviews
    interrupted = False

    async def reviews(*args, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise asyncio.CancelledError
        return await original(*args, **kwargs)

    monkeypatch.setattr(builder, "exact_reviews", reviews)
    with pytest.raises(asyncio.CancelledError):
        await harness.execute()
    harness.bodies["fixture"] = b"Changed source artifact."
    await harness.execute()
    run, report, _, _, _ = await harness.snapshot()
    assert run.status == "failed" and report is None
    assert len(harness.dispatches) == 1


async def test_source_exhaustion_skips_explicit_task_without_dispatch(harness):
    graph = builder.build_graph(harness.settings)
    state = dict(
        tenant_id=str(harness.tenant),
        run_id=str(harness.run_id),
        user_id=str(harness.user),
        question="Explain workflow state preservation",
        quick_mode=False,
        mode="focused",
        mode_policy_version=MODE_POLICY_VERSION,
        sub_question_ids=[],
        source_ids=[],
    )
    state.update(await graph.nodes["planner"].bound.afunc(state))
    task_id = uuid.UUID(state["sub_question_ids"][0])
    async with tenant_session(str(harness.tenant)) as session:
        for index in range(6):
            session.add(
                Source(
                    id=uuid.uuid4(),
                    tenant_id=harness.tenant,
                    run_id=harness.run_id,
                    sub_question_id=task_id,
                    canonical_url=f"https://example.test/filled/{index}",
                    title="Existing evidence",
                    provider="tavily",
                    source_class="unknown",
                    retrieved_at=datetime.now(UTC),
                    content_hash=hashlib.sha256(QUOTE.encode()).hexdigest(),
                    artifact_ref="fixture",
                    discovery_paths=[],
                    content_signature=[],
                )
            )
    await graph.nodes["research_worker"].bound.afunc(state)
    async with tenant_session(str(harness.tenant)) as session:
        task = await session.get(SubQuestion, task_id)
        event = await session.scalar(
            select(RunEvent).where(
                RunEvent.tenant_id == harness.tenant,
                RunEvent.run_id == harness.run_id,
                RunEvent.event_type == "node.progress",
                RunEvent.payload["nodeId"].astext == "research_task",
            )
        )
    assert task.status == "skipped" and task.attempts == 0
    assert task.payload["skipReason"] == "source_capacity_exhausted"
    assert event is not None
    AgentEvent.model_validate(
        {
            "schemaVersion": "1.3",
            "eventId": str(event.event_id),
            "eventSequence": event.event_sequence,
            "tenantId": str(harness.tenant),
            "runId": str(harness.run_id),
            "timestamp": event.occurred_at,
            "type": event.event_type,
            **event.payload,
        }
    )
    assert "source capacity was exhausted" in event.payload["message"]
    assert harness.ingestion_queries == [] and harness.dispatches == []


@pytest.mark.parametrize("gate", ["nonexact", "partial", "contradicted", "missing_review"])
async def test_explicit_publication_retains_exact_and_fully_supported_gate(
    harness, gate, monkeypatch
):
    if gate == "nonexact":
        harness.controls["citation"] = {"source_number": 1, "quote": "Invented evidence passage."}
    elif gate == "missing_review":
        monkeypatch.setattr(builder, "exact_reviews", AsyncMock(return_value=[]))
    else:
        harness.controls["verdict"] = "partially_supports" if gate == "partial" else "contradicts"
    await harness.execute()
    run, report, assessment, _, _ = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["findings"] == []
    assert CLAIM not in report.markdown
    assert report.document["quality"]["status"] == "insufficient_evidence"
    assert "criterion_review_v1" not in harness.dispatches
    assert "focused_evidence_narrative_v1" not in harness.dispatches
    assert report.document["narrative"]["reason"] == "no_verified_findings"
    assert all(
        row["state"] != "verified_covered" for row in assessment.result["coverage"]["dimensions"]
    )


async def test_unsupported_narrative_claim_is_kept_unpublished_without_gap(harness):
    harness.controls["narrative_verdict"] = "partially_supports"
    await harness.execute()
    run, report, assessment, _, _ = await harness.snapshot()
    assert run.status == "completed", run.error_code
    narrative = report.document["narrative"]
    assert narrative["status"] == "composed"
    assert narrative["narrativeClaimIds"] == []
    assert narrative["proposedSentenceCount"] == 2
    assert narrative["publishedSentenceCount"] == 1
    assert narrative["rejectedSentenceCount"] == 1
    assert [finding["text"] for finding in report.document["findings"]] == [CLAIM]
    assert NARRATIVE_CLAIM not in report.markdown
    narrative_id = uuid.uuid5(assessment.id, "narrative-claim:0")
    async with tenant_session(str(harness.tenant)) as session:
        claim = await session.get(EvidenceClaim, narrative_id)
        gaps = list(
            await session.scalars(select(ResearchGap).where(ResearchGap.run_id == harness.run_id))
        )
    assert claim.support == "mixed"
    assert claim.provenance["publishedInReport"] == "false"
    assert str(narrative_id) not in json.dumps([gap.details for gap in gaps], default=str)
    assert all(NARRATIVE_CLAIM not in gap.description for gap in gaps)


@pytest.mark.parametrize(
    ("behaviour", "reason", "dispatched"),
    [
        ("raises", "composition_failed", True),
        ("invalid", "composition_failed", True),
        ("empty", "no_supported_sentences", True),
        ("no_time", "insufficient_time", False),
    ],
)
async def test_narrative_failure_falls_back_to_verified_ledger(
    harness, monkeypatch, behaviour, reason, dispatched
):
    if behaviour == "raises":

        def failing(_):
            raise RuntimeError("private upstream detail")

        harness.controls["narrative"] = failing
    elif behaviour == "invalid":
        harness.controls["narrative"] = lambda _: {"blocks": [{"role": "invented"}]}
    elif behaviour == "empty":
        harness.controls["narrative"] = lambda _: {"blocks": []}
    else:
        monkeypatch.setattr(builder, "NARRATIVE_PUBLICATION_MARGIN_SECONDS", 1_000_000)
    await harness.execute()
    run, report, assessment, _, _ = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["version"] == 4
    narrative = report.document["narrative"]
    assert narrative["status"] == "not_composed" and narrative["reason"] == reason
    assert narrative["blocks"] == [] and narrative["narrativeClaimIds"] == []
    assert [finding["text"] for finding in report.document["findings"]] == [CLAIM]
    assert CLAIM in report.markdown and "## Direct answer" not in report.markdown
    assert ("focused_evidence_narrative_v1" in harness.dispatches) is dispatched
    assert "private" not in json.dumps(assessment.result)


async def test_v8_provenance_runs_keep_report_v3_without_narrative_dispatch(harness):
    async with tenant_session(str(harness.tenant)) as session:
        run = await session.get(ResearchRun, harness.run_id)
        await jobs.enqueue(session, run, harness.settings)
        job = await session.get(RuntimeJob, harness.run_id)
        job.graph_version = jobs.PROVENANCE_MODE_GRAPH_VERSION
    await harness.execute()
    run, report, assessment, _, _ = await harness.snapshot()
    assert run.status == "completed", run.error_code
    assert report.document["version"] == 3
    assert "narrative" not in report.document
    assert "narrative" not in assessment.result
    assert "focused_evidence_narrative_v1" not in harness.dispatches
    assert len(harness.dispatches) == 3


@pytest.mark.parametrize("version", ["research-v6-modes", "research-v6-modes-serper"])
async def test_v6_jobs_fail_closed_without_model_reservations(harness, version):
    async with tenant_session(str(harness.tenant)) as session:
        run = await session.get(ResearchRun, harness.run_id)
        await jobs.enqueue(session, run, harness.settings)
        await session.flush()
        job = await session.get(RuntimeJob, harness.run_id)
        job.graph_version = version
    assert await jobs.claim(harness.tenant, uuid.uuid4(), harness.settings) is None
    async with tenant_session(str(harness.tenant)) as session:
        run = await session.get(ResearchRun, harness.run_id)
        job = await session.get(RuntimeJob, harness.run_id)
        reservations = list(
            await session.scalars(
                select(ProviderCallReservation).where(
                    ProviderCallReservation.run_id == harness.run_id
                )
            )
        )
    assert run.error_code == "graph_version_incompatible"
    assert job.graph_version == version and reservations == []
    assert harness.dispatches == []


@pytest.mark.parametrize("forgery", ["claim", "status", "span"])
def test_cached_audit_cannot_change_claim_support_or_quote_span(forgery):
    assertions = builder.FocusedAssertions(
        claims=[
            builder.SectionedAssertion(
                claim=CLAIM,
                section="mechanisms",
                citations=[builder.CitationDraft(source_number=1, quote=QUOTE)],
                caveats=[],
            )
        ]
    )
    material = builder.SourceMaterial(source=SimpleNamespace(), content=QUOTE)
    reviews = [
        builder.SemanticReview(claim_index=0, citation_index=0, verdict="supports", confidence=0.9)
    ]
    saved = builder._pack_audits(builder._audit_assertions(assertions, reviews, [material]))
    assert builder._restore_audits(assertions, saved, [material])[0][1] == "supported"
    if forgery == "claim":
        assertions.claims[0].claim = "An invented new factual claim."
    elif forgery == "status":
        saved[0]["status"] = "contradicted"
    else:
        saved[0]["details"][0]["start"] = 1
        saved[0]["details"][0]["end"] = 1 + len(QUOTE)
    with pytest.raises(ValueError):
        builder._restore_audits(assertions, saved, [material])
