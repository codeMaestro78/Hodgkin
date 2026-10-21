"""Technical results cannot gain authority from a plausible formula or a linked claim alone."""

import json
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api import jobs
from research_api.config import Settings
from research_api.graph import builder
from research_api.graph.builder import _assessment_assertions, _restore_assessment_assertion_payload
from research_api.measurements import (
    MeasurementProposal,
    compatible_measurement_charts,
    measurement_comparisons,
    review_measurements,
)
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


def measurement(**changes):
    return MeasurementProposal.model_validate(
        {
            "subject": "Group A",
            "metric": "response rate",
            "value": "47.2",
            "unit": "%",
            "population": "adults",
            "period": "2024",
            "method": "randomized trial",
            "definition": "participants with response",
            "source_location": "Table 2",
            "claim_index": 0,
            "citation_index": 0,
        }
        | changes
    )


def measurement_audit(quote, claim=None):
    return [
        {
            "claim": claim or "Group A had a 47.2% response rate in adults in 2024.",
            "status": "supported",
            "claim_id": "claim-1",
            "citations": [
                {
                    "quote": quote,
                    "source_id": "source-1",
                    "source_hash": "a" * 64,
                    "citation_id": "citation-1",
                }
            ],
        }
    ]


def test_measurement_preserves_exact_source_value_and_admits_only_supported_literals():
    quote = (
        "Table 2: Treatment response for Group A: response rate was 47.2% in adults during 2024, "
        "measured in a randomized trial; response means participants with response."
    )
    rows = review_measurements([measurement()], measurement_audit(quote))
    assert rows[0]["status"] == "supported"
    assert rows[0]["result"]["value"] == "47.2"
    assert rows[0]["result"]["unit"] == "%"
    assert rows[0]["result"]["sourcePassage"] == quote
    assert rows[0]["result"]["plotValue"] == "47.2"

    rejected = review_measurements([measurement(value="48")], measurement_audit(quote))
    assert rejected[0]["status"] == "not_assessed"
    assert "value_not_in_exact_passage" in rejected[0]["reasons"]


def test_missing_scope_stays_unknown_and_ranges_are_not_plotted():
    quote = "Treatment response: Group A response rate was 47.2%."
    row = review_measurements(
        [
            measurement(
                population=None, period=None, method=None, definition=None, source_location=None
            )
        ],
        measurement_audit(quote),
    )[0]
    assert row["status"] == "supported"
    assert row["result"]["population"] is None
    assert row["result"]["plotValue"] == "47.2"
    range_quote = "Table 2 Treatment response: Group A response rate was 47.2–51.0%."
    range_row = review_measurements(
        [
            measurement(
                value="47.2–51.0",
                unit="%",
                population=None,
                period=None,
                method=None,
                definition=None,
            )
        ],
        measurement_audit(range_quote, "Group A response rate was 47.2–51.0%."),
    )[0]
    assert range_row["status"] == "supported"
    assert range_row["result"]["plotValue"] is None


def test_measurement_unit_must_be_adjacent_to_value_in_exact_passage():
    quote = "Group A response rate was 47.2; the report also lists percent elsewhere."
    row = review_measurements([measurement()], measurement_audit(quote))[0]
    assert row["status"] == "not_assessed"
    assert "value_unit_not_adjacent_in_exact_passage" in row["reasons"]

    larger_number = "Group A response rate was 147.2%."
    row = review_measurements([measurement()], measurement_audit(larger_number))[0]
    assert row["status"] == "not_assessed"
    assert "value_not_in_exact_passage" in row["reasons"]

    range_passage = "Group A response rate ranged from 47.2–51.0%."
    row = review_measurements([measurement()], measurement_audit(range_passage))[0]
    assert row["status"] == "not_assessed"
    assert "value_not_in_exact_passage" in row["reasons"]


def test_chart_requires_exactly_compatible_measurement_definitions_and_unique_subjects():
    base = {
        "metric": "response rate",
        "unit": "%",
        "population": "adults",
        "period": "2024",
        "method": "randomized trial",
        "definition": "participants with response",
        "plotValue": "47.2",
    }
    rows = [
        base | {"id": "m1", "subject": "Group A"},
        base | {"id": "m2", "subject": "Group B", "plotValue": "51.0"},
    ]
    charts = compatible_measurement_charts(rows)
    assert len(charts) == 1
    assert charts[0]["measurementIds"] == ["m1", "m2"]
    assert compatible_measurement_charts(rows[:1]) == []
    assert compatible_measurement_charts([rows[0], rows[1] | {"population": "children"}]) == []
    assert compatible_measurement_charts([rows[0], rows[1] | {"subject": "Group A"}]) == []


def test_measurement_comparisons_preserve_unknown_or_incompatible_scope():
    rows = [
        {
            "id": "m1",
            "metric": "response rate",
            "subject": "Group A",
            "unit": "%",
            "population": "adults",
            "period": "2024",
            "method": "trial",
            "definition": "response",
        },
        {
            "id": "m2",
            "metric": "response rate",
            "subject": "Group B",
            "unit": "%",
            "population": "children",
            "period": "2024",
            "method": "trial",
            "definition": "response",
        },
    ]
    compared = measurement_comparisons(rows)
    assert compared[0]["status"] == "not_established"
    assert compared[0]["basis"] == "missing_or_incompatible_scope_v1"
    assert compared[0]["measurementIds"] == ["m1", "m2"]
    rows[1]["population"] = "adults"
    assert measurement_comparisons(rows)[0]["status"] == "comparable"
    assert measurement_comparisons(rows[:1]) == []


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


def test_measurement_requests_have_a_new_opt_in_graph_and_structured_schema():
    settings = Settings(
        _env_file=None,
        TECHNICAL_RESULTS_ENABLED=True,
        SOURCE_MEASUREMENTS_ENABLED=True,
        BOUNDED_GAP_REPAIR_ENABLED=False,
    )
    assert (
        jobs.graph_version_for(settings, explicit_mode=True) == jobs.MEASUREMENT_MODE_GRAPH_VERSION
    )
    schema = _assessment_assertions("balanced", [], technical=True, measurements=True)
    assert schema.model_fields["measurements"].annotation
    replayed = schema.model_validate({"claims": [], "technical_results": [], "measurements": []})
    assert replayed.measurements == []
    with pytest.raises(ValueError, match="requires TECHNICAL_RESULTS_ENABLED"):
        jobs.graph_version_for(
            settings.model_copy(update={"TECHNICAL_RESULTS_ENABLED": False}), explicit_mode=True
        )
    with pytest.raises(ValueError, match="BOUNDED_GAP_REPAIR_ENABLED=false"):
        jobs.graph_version_for(
            settings.model_copy(update={"BOUNDED_GAP_REPAIR_ENABLED": True}), explicit_mode=True
        )


def test_v6_assessment_rebuilds_writer_assertions_from_review_receipts():
    result = {
        "report_version": 6,
        "assertions": {"claims": []},
        "technical_results": [{"proposal": proposal().model_dump(mode="json")}],
        "measurements": [{"proposal": measurement().model_dump(mode="json")}],
    }

    restored = _restore_assessment_assertion_payload(result)
    parsed = _assessment_assertions(
        "balanced", [], technical=True, measurements=True
    ).model_validate(restored)

    assert parsed.technical_results[0].title == "Theorem 2"
    assert parsed.measurements[0].value == "47.2"


def test_v4_assessment_does_not_require_typed_proposal_receipts():
    restored = _restore_assessment_assertion_payload(
        {"report_version": 4, "assertions": {"claims": []}}
    )
    assert "technical_results" not in restored
    assert "measurements" not in restored


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


def test_focused_budget_caps_writer_to_leave_time_for_collection_and_review():
    settings = Settings(
        _env_file=None,
        MODEL_WRITER_TIMEOUT_SECONDS=45,
        PROVIDER_TIMEOUT_SECONDS=30,
    )
    assert builder._criterion_review_reserve_seconds(settings) == 90
    assert builder._criterion_review_reserve_seconds(settings, protected=True) == 60
    assert builder._explicit_writer_timeout_seconds(settings, "focused") == 30
    assert builder._explicit_assessment_tail_seconds(settings, "focused") == 120
    assert builder._explicit_assessment_tail_seconds(settings, "balanced") == 165
    assert builder._post_writer_review_tail_seconds(settings, "focused") == 90
    assert builder._post_writer_review_tail_seconds(settings, "balanced") == 120


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
