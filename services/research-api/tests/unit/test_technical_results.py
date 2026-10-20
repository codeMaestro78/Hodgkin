"""Technical results cannot gain authority from a plausible formula or a linked claim alone."""

import json
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api import jobs
from research_api.config import Settings
from research_api.graph import builder
from research_api.graph.builder import _assessment_assertions
from research_api.technical_results import TechnicalResultProposal, review_technical_results


def proposal(**changes):
    data = {
        "kind": "theorem",
        "title": "Theorem 2",
        "claim_index": 0,
        "citation_index": 0,
        "assumptions": ["reversible continuous-time chains"],
        "notation": ["lambda is the spectral gap"],
        "source_expression": "t_mix <= log(1/pi_min)/lambda",
        "representation": "plain_text",
        "source_location": "Theorem 2",
    }
    return TechnicalResultProposal.model_validate(data | changes)


QUOTE = (
    "Theorem 2. For reversible continuous-time chains, lambda is the spectral gap "
    "and t_mix <= log(1/pi_min)/lambda."
)


def test_admits_only_exact_fields_with_a_supported_parent_claim():
    audited = [
        {
            "claim": "For reversible continuous-time chains, t_mix obeys the stated bound.",
            "status": "supported",
            "citations": [
                {
                    "quote": QUOTE,
                    "source_id": "source-1",
                    "source_hash": "a" * 64,
                    "citation_id": "citation-1",
                }
            ],
            "claim_id": "claim-1",
        }
    ]
    checked = review_technical_results([proposal()], audited)
    assert checked[0]["status"] == "supported"
    assert checked[0]["result"]["expression"]["sourceText"] == proposal().source_expression
    assert checked[0]["result"]["claimId"] == "claim-1"
    assert checked[0]["result"]["citationIds"] == ["citation-1"]


def test_rejects_missing_scope_or_changed_formula():
    audited = [
        {
            "claim": "For continuous-time chains, t_mix obeys the stated bound.",
            "status": "supported",
            "citations": [
                {
                    "quote": QUOTE,
                    "source_id": "source-1",
                    "source_hash": "a" * 64,
                    "citation_id": "citation-1",
                }
            ],
            "claim_id": "claim-1",
        }
    ]
    assert review_technical_results([proposal()], audited)[0]["status"] == "not_assessed"
    audited[0]["claim"] = "For reversible continuous-time chains, t_mix obeys the bound."
    checked = review_technical_results(
        [proposal(source_expression="t_mix >= log(1/pi_min)/lambda")], audited
    )
    assert checked[0]["status"] == "not_assessed"
    assert "expression_not_in_quote" in checked[0]["reasons"]


def test_rejects_unreviewed_claim_or_missing_location():
    audited = [
        {
            "claim": "For reversible continuous-time chains, t_mix obeys the bound.",
            "status": "partially_supported",
            "citations": [
                {
                    "quote": QUOTE,
                    "source_id": "source-1",
                    "source_hash": "a" * 64,
                    "citation_id": "citation-1",
                }
            ],
            "claim_id": "claim-1",
        }
    ]
    assert review_technical_results([proposal()], audited)[0]["status"] == "not_assessed"
    audited[0]["status"] = "supported"
    assert (
        "location_not_in_quote"
        in review_technical_results([proposal(source_location="Page 99")], audited)[0]["reasons"]
    )


def test_technical_request_is_pinned_to_a_new_graph_and_schema():
    settings = Settings(
        _env_file=None,
        TECHNICAL_RESULTS_ENABLED=True,
        BOUNDED_GAP_REPAIR_ENABLED=False,
    )
    assert jobs.graph_version_for(settings, explicit_mode=True) == jobs.TECHNICAL_MODE_GRAPH_VERSION
    assert jobs.TECHNICAL_MODE_GRAPH_VERSION.startswith("research-v17-")
    assert (
        "technical_results" in _assessment_assertions("balanced", [], technical=True).model_fields
    )
    assert (
        "technical_results"
        not in _assessment_assertions("balanced", [], technical=False).model_fields
    )
    assert (
        jobs.graph_version_for(
            settings.model_copy(update={"BOUNDED_GAP_REPAIR_ENABLED": True}), explicit_mode=True
        )
        == jobs.PROTECTED_REPAIR_MODE_GRAPH_VERSION
    )
    assert jobs.graph_version_for(Settings(_env_file=None), explicit_mode=True) == (
        jobs.PROTECTED_MODE_GRAPH_VERSION
    )


@pytest.mark.parametrize("mode,limit", [("focused", 2), ("balanced", 4), ("deep", 6)])
def test_technical_proposals_are_bounded_by_mode(mode, limit):
    schema = _assessment_assertions(mode, [], technical=True).model_json_schema()
    assert schema["properties"]["technical_results"]["maxItems"] == limit


@pytest.mark.asyncio
async def test_technical_writer_request_requires_bounded_proposals(monkeypatch):
    response = AsyncMock(
        return_value=SimpleNamespace(output_text='{"claims":[],"technical_results":[]}')
    )
    monkeypatch.setattr(builder, "_model_response", response)
    draft = await builder._synthesize_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"),
        question="State the theorem and its assumptions",
        source_context="SOURCE [1] fixture",
        max_search_calls=6,
        mode="focused",
        technical_results_enabled=True,
    )
    assert draft.technical_results == []
    schema = response.call_args.kwargs["text"]["format"]["schema"]
    assert "technical_results" in schema["properties"]


@pytest.mark.asyncio
async def test_empty_grounded_draft_gets_one_bounded_redraft(monkeypatch):
    quote = (
        "Theorem 2: For a finite irreducible reversible chain, the spectral gap lambda gives "
        "the total-variation bound max_x ||P_t(x,.) - pi||_TV <= "
        "(1/(2 sqrt(pi_min))) exp(-lambda t)."
    )
    claim = (
        "For a finite irreducible reversible chain, the source states this "
        "total-variation upper bound."
    )
    response = AsyncMock(
        side_effect=[
            SimpleNamespace(output_text='{"claims":[],"technical_results":[]}'),
            SimpleNamespace(
                output_text=(
                    '{"claims":[{"claim":'
                    + json.dumps(claim)
                    + ',"section":"mechanisms","figures":[],"caveats":[],"citations":'
                    '[{"source_number":1,"passage_id":"s1_p1"}]}],'
                    '"technical_results":[{"kind":"theorem","title":"Theorem 2",'
                    '"claim_index":0,"citation_index":0,'
                    '"assumptions":["finite irreducible reversible chain"],"notation":[],'
                    '"source_expression":"max_x ||P_t(x,.) - pi||_TV <= '
                    '(1/(2 sqrt(pi_min))) exp(-lambda t)","representation":"plain_text",'
                    '"source_location":"Theorem 2"}]}'
                )
            ),
        ]
    )
    monkeypatch.setattr(builder, "_model_response", response)
    pin_request = AsyncMock()
    material = builder.SourceMaterial(
        source=SimpleNamespace(
            title="Primary Markov-chain source", canonical_url="https://example.test/theorem"
        ),
        content=quote,
    )

    draft = await builder._synthesize_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"),
        question="State the exact continuous-time spectral-gap bound and assumptions.",
        source_context=f"SOURCE [1]\nTitle: Markov chains\n{quote}",
        max_search_calls=6,
        materials=[material],
        mode="focused",
        technical_results_enabled=True,
        pin_request=pin_request,
    )

    assert response.await_count == 2
    assert len(draft.assertions.claims) == 1
    assert draft.assertions.claims[0].citations[0].quote == quote
    assert len(draft.technical_results) == 1
    assert (
        "prior structured draft contained zero claims"
        in response.await_args_list[1].kwargs["instructions"]
    )
    assert response.await_args_list[1].kwargs["max_output_tokens"] <= 3072
    assert pin_request.await_count == 1
    pinned_initial, pinned_registry, pinned_retry = pin_request.await_args.args
    assert pinned_initial["text"]["format"]["name"].startswith("focused_claim_draft")
    assert pinned_registry
    assert pinned_retry["text"]["format"]["name"].endswith("_empty_draft_retry_v2")


@pytest.mark.asyncio
async def test_invalid_empty_draft_retry_keeps_original_valid_empty_result(monkeypatch):
    response = AsyncMock(
        side_effect=[
            SimpleNamespace(output_text='{"claims":[]}'),
            SimpleNamespace(output_text="not-json"),
        ]
    )
    monkeypatch.setattr(builder, "_model_response", response)
    material = builder.SourceMaterial(
        source=SimpleNamespace(title="Source", canonical_url="https://example.test"),
        content=(
            "A source passage with enough literal text to be selected for the requested question."
        ),
    )

    draft = await builder._synthesize_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"),
        question="What does this source establish?",
        source_context="SOURCE [1] fixture",
        max_search_calls=6,
        materials=[material],
        mode="focused",
    )

    assert response.await_count == 2
    assert draft.assertions.claims == []


def test_explicit_assessment_reserves_reviewer_and_publication_but_not_another_writer():
    settings = Settings(
        _env_file=None,
        MODEL_WRITER_TIMEOUT_SECONDS=45,
        PROVIDER_TIMEOUT_SECONDS=30,
    )
    assert builder._criterion_review_reserve_seconds(settings) == 90
    assert builder._criterion_review_reserve_seconds(settings, protected=True) == 50
    assert builder._explicit_assessment_tail_seconds(settings, "focused") == 115
    assert builder._explicit_assessment_tail_seconds(settings, "balanced") == 135
    assert builder._post_writer_review_tail_seconds(settings, "focused") == 70
    assert builder._post_writer_review_tail_seconds(settings, "balanced") == 90


@pytest.mark.asyncio
async def test_explicit_claim_review_caps_model_batches_to_protect_criterion_review(monkeypatch):
    response = AsyncMock(return_value=SimpleNamespace(output_text='{"reviews":[]}'))
    monkeypatch.setattr(builder, "_model_response", response)
    claims = [
        builder.ReportAssertion(
            claim=f"Claim {index}",
            citations=[
                builder.CitationDraft(source_number=1, quote=f"Evidence quote {index} item {part}")
                for part in range(3)
            ],
            caveats=[],
        )
        for index in range(33)
    ]

    reviews = await builder._semantic_reviews_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"), claims=claims, max_batches=2
    )

    assert reviews == []
    assert response.await_count == 2


@pytest.mark.asyncio
async def test_bounded_claim_review_timeout_returns_no_unverified_reviews(monkeypatch):
    async def slow_review(*_args, **_kwargs):
        import asyncio

        await asyncio.sleep(0.05)

    monkeypatch.setattr(builder, "_model_response", slow_review)
    claim = builder.ReportAssertion(
        claim="A narrow source-backed claim.",
        citations=[builder.CitationDraft(source_number=1, quote="An exact evidence passage.")],
        caveats=[],
    )

    reviews = await builder._semantic_reviews_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"),
        claims=[claim],
        max_batches=1,
        timeout_seconds=0.001,
    )

    assert reviews == []


@pytest.mark.asyncio
async def test_empty_draft_without_selected_literal_passages_is_not_retried(monkeypatch):
    response = AsyncMock(return_value=SimpleNamespace(output_text='{"claims":[]}'))
    monkeypatch.setattr(builder, "_model_response", response)
    material = builder.SourceMaterial(
        source=SimpleNamespace(title="Source", canonical_url="https://example.test"),
        content="short",
    )

    draft = await builder._synthesize_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"),
        question="What evidence is here?",
        source_context="SOURCE [1] fixture",
        max_search_calls=6,
        materials=[material],
        mode="focused",
    )

    assert response.await_count == 1
    assert draft.assertions.claims == []


@pytest.mark.asyncio
async def test_empty_draft_retry_respects_report_publication_time_reserve(monkeypatch):
    response = AsyncMock(return_value=SimpleNamespace(output_text='{"claims":[]}'))
    monkeypatch.setattr(builder, "_model_response", response)
    material = builder.SourceMaterial(
        source=SimpleNamespace(title="Source", canonical_url="https://example.test"),
        content=(
            "A source passage with enough literal text to be selected for the requested question."
        ),
    )
    deadline_token = builder.assessment_deadline.set(monotonic() + 10)
    try:
        draft = await builder._synthesize_with_openai(
            Settings(_env_file=None, OPENAI_API_KEY="fixture"),
            question="What does this source establish?",
            source_context="SOURCE [1] fixture",
            max_search_calls=6,
            materials=[material],
            mode="focused",
        )
    finally:
        builder.assessment_deadline.reset(deadline_token)

    assert response.await_count == 1
    assert draft.assertions.claims == []
