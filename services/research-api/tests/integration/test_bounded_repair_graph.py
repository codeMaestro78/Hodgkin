"""Opt-in graph v14 bounded gap repair on local PostgreSQL with fake provider IO.

Run only on the loopback database enforced by conftest, migrated through 0019.
No hosted/provider calls or migrations are performed by this suite.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from test_reliability_runtime import seed

from research_api import api, jobs
from research_api.config import Settings
from research_api.db.assessments import ResearchAssessment
from research_api.db.models import (
    ProviderCall,
    Report,
    ResearchPlan,
    ResearchRun,
    Source,
    SubQuestion,
)
from research_api.db.session import tenant_session
from research_api.events.outbox import EventOutbox
from research_api.graph import builder
from research_api.lifecycle import lock_run
from research_api.mode_policy import MODE_POLICY_VERSION, resolve_mode_budget
from research_api.repositories.runs import RunRepository

pytestmark = pytest.mark.integration
QUESTION = "Explain workflow state preservation"
QUOTE = "The service preserves workflow state in durable storage."
CLAIM = "The service preserves workflow state."
REPAIR_QUOTE = "Preserved workflow state is retained for thirty days by default."
REPAIR_CLAIM = "Preserved workflow state is retained for thirty days by default."
GAP_TASK = "Find evidence about the retention period of preserved workflow state"
REPAIR_FORMAT = "balanced_gap_repair_draft_passages_v2"


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
            question=QUESTION,
            mode="balanced",
            mode_policy_version=MODE_POLICY_VERSION,
            budget=resolve_mode_budget("balanced"),
        )
        run_id = run.id
    settings = Settings(
        _env_file=None,
        OPENAI_API_KEY="fixture",
        TAVILY_API_KEY="fixture",
        PROVIDER_MAX_ATTEMPTS=1,
        BOUNDED_GAP_REPAIR_ENABLED=True,
    )
    planner = AsyncMock(
        return_value=builder.PlannerOutput(
            sub_questions=[
                builder.PlannedQuestion(
                    question="Find original evidence for workflow state preservation",
                    rationale="Inspect preserved evidence",
                    success_criteria=["Establish state preservation"],
                    source_classes=["primary"],
                ),
                builder.PlannedQuestion(
                    question=GAP_TASK,
                    rationale="Retention is part of preservation",
                    success_criteria=["Establish the retention period"],
                    source_classes=["official"],
                ),
            ]
        )
    )
    monkeypatch.setattr(builder, "_plan_with_openai", planner)
    bodies = {"fixture": QUOTE.encode(), "repair": REPAIR_QUOTE.encode()}

    class Store:
        def __init__(self, **kwargs):
            pass

        async def get_for_verification(self, *, artifact_ref):
            return bodies[artifact_ref]

    monkeypatch.setattr(builder, "S3ArtifactStore", Store)
    controls = {
        "repair_body": "repair",
        "repair_writer_error": None,
        "repair_claims": None,
        "repair_entered": None,
        "repair_release": None,
    }
    ingestion = []

    class Ingestor:
        def __init__(self, **kwargs):
            pass

        async def ingest(self, **kwargs):
            async with tenant_session(str(tenant)) as session:
                question = await session.get(SubQuestion, kwargs["sub_question_id"])
                repair = "repairCandidateId" in question.payload
            ingestion.append((kwargs["query"], kwargs["max_results"], repair))
            call_number = len(ingestion)
            ref = controls["repair_body"] if repair else "fixture"
            async with tenant_session(str(tenant)) as session:
                source = Source(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    run_id=run_id,
                    sub_question_id=kwargs["sub_question_id"],
                    canonical_url=f"https://example.test/{ref}/{call_number}",
                    title=f"Evidence {ref}",
                    provider="tavily",
                    source_class="unknown",
                    retrieved_at=datetime.now(UTC),
                    content_hash=hashlib.sha256(bodies[ref]).hexdigest(),
                    artifact_ref=ref,
                    discovery_paths=[],
                    content_signature=[],
                )
                session.add(source)
                await session.flush()
                source_id = source.id
            entered = controls["repair_entered"]
            release = controls["repair_release"]
            if repair and entered is not None and release is not None:
                entered.set()
                await release.wait()
            return [source_id]

    monkeypatch.setattr(builder, "TavilyEvidenceIngestor", Ingestor)
    dispatches = []
    criterion_inputs = []

    def draft(text):
        return {
            "claim": text,
            "section": "mechanisms",
            "figures": [],
            "caveats": [],
            "citations": [{"source_number": 1, "passage_id": "s1_p1"}],
        }

    async def create(**request):
        name = request["text"]["format"]["name"]
        dispatches.append(name)
        if name == "balanced_claim_draft_passages_v2":
            result = {"claims": [draft(CLAIM)]}
        elif name == REPAIR_FORMAT:
            if controls["repair_writer_error"]:
                raise controls["repair_writer_error"]
            claims = controls["repair_claims"]
            result = {"claims": [draft(REPAIR_CLAIM)] if claims is None else claims}
        elif name == "citation_semantic_reviews_batched_v1":
            inputs = json.loads(request["input"])
            result = {
                "reviews": [
                    {
                        "claim_index": item["claimIndex"],
                        "citation_index": citation["citationIndex"],
                        "verdict": "supports",
                        "confidence": 0.9,
                    }
                    for item in inputs
                    for citation in item["citations"]
                ]
            }
        elif name in {"criterion_review_v1", "criterion_review_v2"}:
            inputs = json.loads(request["input"])
            criterion_inputs.append(inputs)
            claims = {claim["text"]: claim["id"] for claim in inputs["verified_claims"]}
            assessments = []
            for dim in inputs["dimensions"]:
                gap = dim["label"] == GAP_TASK
                for criterion in dim["criteria"]:
                    if gap and REPAIR_CLAIM not in claims:
                        assessments.append(
                            {
                                "dimension_id": dim["dimension_id"],
                                "criterion_id": criterion["id"],
                                "outcome": "not_met",
                                "claim_ids": [],
                            }
                        )
                    else:
                        assessments.append(
                            {
                                "dimension_id": dim["dimension_id"],
                                "criterion_id": criterion["id"],
                                "outcome": "met",
                                "claim_ids": [claims[REPAIR_CLAIM if gap else CLAIM]],
                            }
                        )
            result = {"assessments": assessments, "comparisons": []}
            if name == "criterion_review_v2":
                result["conflicts"] = []
        elif name == "balanced_evidence_narrative_v1":
            result = {"blocks": []}
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
            question=QUESTION,
            checkpointer=checkpointer,
        )

    async def snapshot():
        async with tenant_session(str(tenant)) as session:
            run = await session.get(ResearchRun, run_id)
            report = await session.scalar(select(Report).where(Report.run_id == run_id))
            assessments = list(
                await session.scalars(
                    select(ResearchAssessment)
                    .where(
                        ResearchAssessment.tenant_id == tenant,
                        ResearchAssessment.run_id == run_id,
                    )
                    .order_by(ResearchAssessment.created_at)
                )
            )
            plans = list(
                await session.scalars(
                    select(ResearchPlan)
                    .where(ResearchPlan.run_id == run_id)
                    .order_by(ResearchPlan.plan_version)
                )
            )
            questions = list(
                await session.scalars(
                    select(SubQuestion)
                    .where(SubQuestion.tenant_id == tenant, SubQuestion.run_id == run_id)
                    .order_by(SubQuestion.created_at, SubQuestion.id)
                )
            )
            sources = list(
                await session.scalars(
                    select(Source)
                    .where(Source.tenant_id == tenant, Source.run_id == run_id)
                    .order_by(Source.retrieved_at, Source.id)
                )
            )
            calls = list(
                await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run_id))
            )
        return SimpleNamespace(
            run=run,
            report=report,
            assessments=assessments,
            plans=plans,
            questions=questions,
            sources=sources,
            calls=calls,
        )

    return SimpleNamespace(
        tenant=tenant,
        user=user,
        run_id=run_id,
        execute=execute,
        snapshot=snapshot,
        dispatches=dispatches,
        ingestion=ingestion,
        controls=controls,
        criterion_inputs=criterion_inputs,
    )


def _finding_texts(report):
    return [finding["text"] for finding in report.document["findings"]]


async def test_balanced_repair_collects_one_gap_and_publishes_verified_union(harness):
    await harness.execute()
    state = await harness.snapshot()
    assert state.run.status == "completed", state.run.error_code
    base, delta = state.assessments
    assert base.manifest["coverage_plan"]["repair_sources_reserved"] == 2
    assert base.result["repair_status"] == builder.BOUNDED_REPAIR_STATUS
    proposals = base.result["repair_decision"]["proposals"]
    assert len(proposals) == 1 and base.result["repair_decision"]["outcome"] == "propose"
    # One deterministic query per gap dimension, one source, never model-authored.
    repairs = [item for item in harness.ingestion if item[2]]
    assert repairs == [(proposals[0]["query"], 1, True)]
    assert proposals[0]["query"] == GAP_TASK + " ; Establish the retention period"
    assert [plan.plan_version for plan in state.plans] == [1, 2]
    child = state.plans[1]
    assert child.parent_plan_version == 1 and state.run.active_plan_id == child.id
    assert child.plan["repair"]["base_assessment_id"] == str(base.id)
    assert child.plan["coverage"] == state.plans[0].plan["coverage"]
    assert delta.plan_id == child.id
    assert delta.manifest["delta_source_offset"] == len(base.manifest["sources"])
    assert delta.manifest["sources"][: len(base.manifest["sources"])] == base.manifest["sources"]
    assert delta.result["repair"]["status"] == "repaired"
    assert delta.result["repair"]["delta_claim_count"] == 1
    assert delta.result["repair_decision"]["outcome"] == "stop"
    # Base claims and reviews are reused verbatim; only the delta was drafted.
    claims = delta.result["assertions"]["claims"]
    assert claims[: len(base.result["assertions"]["claims"])] == base.result["assertions"]["claims"]
    assert harness.dispatches.count("balanced_claim_draft_passages_v2") == 1
    assert harness.dispatches.count(REPAIR_FORMAT) == 1
    assert len(harness.dispatches) == len(state.calls)
    assert state.report.document["assessmentId"] == str(delta.id)
    assert _finding_texts(state.report) == [CLAIM, REPAIR_CLAIM]
    assert REPAIR_CLAIM in state.report.markdown
    dims = {dim["label"]: dim for dim in state.report.document["dimensions"]}
    assert dims[GAP_TASK]["status"] == "verified_covered"


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ({"repair_body": "fixture"}, "no_new_evidence"),
        ({"repair_writer_error": RuntimeError("private upstream detail")}, "failed"),
        ({"repair_claims": []}, "no_delta_claims"),
    ],
)
async def test_unproductive_repair_publishes_the_verified_base(harness, setup, reason, monkeypatch):
    harness.controls.update(setup)
    await harness.execute()
    state = await harness.snapshot()
    assert state.run.status == "completed", state.run.error_code
    base, delta = state.assessments
    assert delta.result["publication"] == "base"
    assert delta.result["repair"]["status"] == "stopped"
    assert delta.result["repair"]["reason"] == reason
    assert "private" not in json.dumps(delta.result)
    assert state.report.document["assessmentId"] == str(base.id)
    assert _finding_texts(state.report) == [CLAIM]
    assert harness.dispatches.count(REPAIR_FORMAT) == (reason != "no_new_evidence")
    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(return_value=SimpleNamespace(tenant_id=harness.tenant, user_id=harness.user)),
    )
    projection = await api.get_research_run(harness.run_id)
    assert projection["report"]["repairOutcome"] == {"status": "stopped", "reason": reason}


async def test_repair_without_publication_time_falls_back_before_writer(harness, monkeypatch):
    monkeypatch.setattr(builder, "REPAIR_PUBLICATION_MARGIN_SECONDS", 10**6)
    await harness.execute()
    state = await harness.snapshot()
    assert state.run.status == "completed", state.run.error_code
    _, delta = state.assessments
    assert delta.result["repair"]["reason"] == "insufficient_time"
    assert REPAIR_FORMAT not in harness.dispatches
    assert _finding_texts(state.report) == [CLAIM]


async def test_admission_recheck_stops_without_collection_or_child_plan(harness, monkeypatch):
    calls = 0
    original = builder._repair_tail_ms

    def tail(settings):
        nonlocal calls
        calls += 1
        # The decision sees time; the admission recheck under lock does not.
        return original(settings) if calls == 1 else 10**9

    monkeypatch.setattr(builder, "_repair_tail_ms", tail)
    await harness.execute()
    state = await harness.snapshot()
    assert state.run.status == "completed", state.run.error_code
    (base,) = state.assessments
    assert base.result["repair_decision"]["proposals"]
    assert [plan.plan_version for plan in state.plans] == [1]
    assert not any(item[2] for item in harness.ingestion)
    assert _finding_texts(state.report) == [CLAIM]


async def test_concurrent_repair_admission_reuses_one_persisted_child_plan(harness, monkeypatch):
    """Concurrent graph-node retries serialize on the run row and replay the winner."""
    original_build_graph = builder.build_graph
    admission_ready = asyncio.Event()
    resume_graph = asyncio.Event()
    captured = {}

    def build_graph_with_admission_barrier(settings, checkpointer=None):
        graph = original_build_graph(settings, checkpointer=checkpointer)
        node = graph.nodes["planner_delta"].bound
        tracked_admission = node.afunc

        async def pause_before_admission(state):
            if state.get("mode") and "state" not in captured:
                captured["state"] = state
                captured["tracked_admission"] = tracked_admission
                admission_ready.set()
                await resume_graph.wait()
            return await tracked_admission(state)

        node.afunc = pause_before_admission
        return graph

    monkeypatch.setattr(builder, "build_graph", build_graph_with_admission_barrier)
    graph_task = asyncio.create_task(harness.execute())
    await asyncio.wait_for(admission_ready.wait(), timeout=30)
    tracked_admission = captured["tracked_admission"]
    state = captured["state"]

    # Both dispatches contend through the real tracked node and database lock.
    deadline_token = builder.assessment_deadline.set(asyncio.get_running_loop().time() + 600)
    try:
        first, second = await asyncio.gather(tracked_admission(state), tracked_admission(state))
    finally:
        builder.assessment_deadline.reset(deadline_token)
        resume_graph.set()
    await asyncio.wait_for(graph_task, timeout=60)
    assert first["repair_admitted"] and second["repair_admitted"], (first, second)
    assert first["sub_question_ids"] == second["sub_question_ids"]

    snapshot = await harness.snapshot()
    assert snapshot.run.status == "completed", snapshot.run.error_code
    assert [plan.plan_version for plan in snapshot.plans] == [1, 2]
    repair_plan = snapshot.plans[1]
    repair_questions = [item for item in snapshot.questions if item.plan_id == repair_plan.id]
    assert len(repair_questions) == 1
    assert harness.dispatches.count(REPAIR_FORMAT) == 1
    assert sum(item[2] for item in harness.ingestion) == 1
    monkeypatch.setattr(
        api,
        "_caller",
        AsyncMock(return_value=SimpleNamespace(tenant_id=harness.tenant, user_id=harness.user)),
    )
    projection = await api.get_research_run(harness.run_id)
    assert projection["report"]["repairOutcome"] == {
        "status": "repaired",
        "newSourceCount": 1,
        "verifiedFindingCount": 1,
    }


async def test_cancellation_during_repair_preserves_collected_evidence_and_base_assessment(harness):
    entered, release = asyncio.Event(), asyncio.Event()
    harness.controls["repair_entered"] = entered
    harness.controls["repair_release"] = release

    graph_task = asyncio.create_task(harness.execute())
    await asyncio.wait_for(entered.wait(), timeout=30)
    async with tenant_session(str(harness.tenant)) as session:
        run = await lock_run(session, harness.tenant, harness.run_id)
        run.cancellation_requested_at = datetime.now(UTC)
        await EventOutbox(session, harness.tenant).append(
            run_id=harness.run_id,
            event_type="run.cancellation_requested",
            payload={"label": "Cancellation requested"},
        )
    release.set()
    await asyncio.wait_for(graph_task, timeout=60)

    snapshot = await harness.snapshot()
    assert snapshot.run.status == "cancelled"
    assert snapshot.run.cancellation_requested_at is not None
    assert snapshot.report is None
    assert len(snapshot.assessments) == 1
    assert snapshot.assessments[0].result is not None
    assert snapshot.assessments[0].result["assertions"]["claims"][0]["claim"] == CLAIM
    assert len(snapshot.sources) == 3
    assert harness.dispatches.count(REPAIR_FORMAT) == 0
    assert sum(item[2] for item in harness.ingestion) == 1


@pytest.mark.parametrize("node", ["node.planner_delta", "delta_review"])
async def test_crash_replays_repair_without_duplicate_plan_or_paid_dispatch(
    harness, monkeypatch, node
):
    crashed = False
    if node == "delta_review":
        original = builder.exact_reviews

        async def reviews(settings, claims, materials):
            nonlocal crashed
            if not crashed and any(claim.claim == REPAIR_CLAIM for claim in claims):
                crashed = True
                raise asyncio.CancelledError
            return await original(settings, claims, materials)

        monkeypatch.setattr(builder, "exact_reviews", reviews)
    else:
        original_event = builder.operation_event

        def event(name, **kwargs):
            nonlocal crashed
            if name == node and not crashed:
                crashed = True
                raise asyncio.CancelledError
            return original_event(name, **kwargs)

        monkeypatch.setattr(builder, "operation_event", event)
    with pytest.raises(asyncio.CancelledError):
        await harness.execute()
    await harness.execute()
    state = await harness.snapshot()
    assert crashed
    assert state.run.status == "completed", state.run.error_code
    assert [plan.plan_version for plan in state.plans] == [1, 2]
    assert len(state.assessments) == 2
    assert sum(item[2] for item in harness.ingestion) == 1
    assert harness.dispatches.count(REPAIR_FORMAT) == 1
    assert len(harness.dispatches) == len(state.calls)
    assert _finding_texts(state.report) == [CLAIM, REPAIR_CLAIM]


async def test_v9_jobs_keep_repair_disabled_and_reservations_unchanged(harness, monkeypatch):
    monkeypatch.setattr(builder, "MODE_GRAPH_VERSION", jobs.NARRATIVE_MODE_GRAPH_VERSION)
    # Graph-version capability sets are computed at import time; patch the
    # capability gate too, so this really exercises the legacy v9 contract.
    monkeypatch.setattr(builder, "REPAIR_GRAPH_VERSIONS", frozenset())
    await harness.execute()
    state = await harness.snapshot()
    assert state.run.status == "completed", state.run.error_code
    (assessment,) = state.assessments
    assert assessment.result["repair_status"] == builder.EXPLICIT_REPAIR_STATUS
    assert assessment.manifest["repair_status"] == builder.EXPLICIT_REPAIR_STATUS
    assert assessment.manifest["coverage_plan"]["repair_sources_reserved"] == 0
    assert assessment.result["repair_decision"]["proposals"] == []
    assert [plan.plan_version for plan in state.plans] == [1]
    assert REPAIR_FORMAT not in harness.dispatches
    assert "repair" not in assessment.result
