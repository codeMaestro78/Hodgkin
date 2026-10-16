import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.config import Settings
from research_api.graph import builder
from research_api.grounding import grounded_writer_request, literal_passages, restore_passage_quotes


def test_passages_are_literal_bounded_relevant_and_deterministic():
    text = (
        "Menu\n"
        + "Unrelated navigation. " * 40
        + "\nKafka stores events durably. Consumers replay stored events."
    )
    choices = literal_passages(text, "Kafka replay", 500)
    assert choices == literal_passages(text, "Kafka replay", 500)
    assert all(quote in text and 8 <= len(quote) <= 600 for quote in choices)
    assert sum(map(len, choices)) <= 500
    assert any("Kafka stores events" in quote for quote in choices)


def test_writer_schema_binds_exact_quotes_to_their_source_without_mutating_legacy_request():
    old = {
        "input": "Question\n\nEvidence bundle:\nlegacy context",
        "instructions": "Legacy policy",
        "text": {
            "format": {
                "name": "balanced_claim_draft",
                "strict": True,
                "schema": builder.BalancedAssertions.model_json_schema(),
            }
        },
    }
    original = json.dumps(old, sort_keys=True)
    materials = [
        ("Kafka", "https://k.test", "Kafka stores durable events."),
        ("Temporal", "https://t.test", "Temporal records workflow history."),
    ]
    request, registry = grounded_writer_request(
        old, materials, "Kafka Temporal", 18000, "legacy context"
    )
    assert json.dumps(old, sort_keys=True) == original
    citation = request["text"]["format"]["schema"]["$defs"]["CitationDraft"]
    for number, branch in enumerate(citation["anyOf"], 1):
        assert branch["properties"]["source_number"]["enum"] == [number]
        assert branch["required"] == ["source_number", "passage_id"]
        assert branch["additionalProperties"] is False
        assert all(
            registry[(number, passage)] in materials[number - 1][2]
            for passage in branch["properties"]["passage_id"]["enum"]
        )
    assert "legacy context" not in request["input"]
    assert "one factual proposition" in request["instructions"]
    assert (request, registry) == grounded_writer_request(
        old, materials, "Kafka Temporal", 18000, "legacy context"
    )


def test_no_passages_does_not_create_an_invalid_empty_enum():
    request = {"text": {"format": {"schema": {}}}, "input": "", "instructions": ""}
    assert grounded_writer_request(request, [("", "", "   ")], "q", 1000, "") == (request, {})


@pytest.mark.parametrize("saved", [False, True])
async def test_real_writer_uses_literal_policy_unless_replaying_existing_request(
    monkeypatch, saved
):
    response = AsyncMock(return_value=SimpleNamespace(output_text='{"claims":[]}'))
    monkeypatch.setattr(builder, "_model_response", response)
    monkeypatch.setattr(builder, "_has_legacy_writer_request", AsyncMock(return_value=saved))
    material = builder.SourceMaterial(
        source=SimpleNamespace(title="Kafka", canonical_url="https://k.test"),
        content="Kafka stores durable events.",
    )
    await builder._synthesize_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"),
        question="Kafka",
        source_context="Old bundle",
        materials=[material],
        max_search_calls=12,
    )
    dispatched = response.call_args.kwargs
    fmt = dispatched["text"]["format"]
    assert fmt["name"].endswith("_passages_v2") is (not saved)
    if not saved:
        options = fmt["schema"]["$defs"]["CitationDraft"]["anyOf"]
        assert options[0]["properties"]["passage_id"]["enum"] == ["s1_p1"]
        assert "Old bundle" not in dispatched["input"]
    else:
        assert "Old bundle" in dispatched["input"]


def test_source_quotes_with_json_special_characters_never_enter_schema_enums():
    quote = 'Kafka calls this "exactly once".\nUse \\ transactions.'
    old = {
        "input": "",
        "instructions": "",
        "text": {
            "format": {"name": "claims", "schema": builder.FocusedAssertions.model_json_schema()}
        },
    }
    request, registry = grounded_writer_request(old, [("Kafka", "", quote)], "Kafka", 12000, "")
    assert '"exactly once"' not in json.dumps(request["text"]["format"]["schema"])
    passage = next(iter(registry))
    payload = {"claims": [{"citations": [{"source_number": passage[0], "passage_id": passage[1]}]}]}
    restored = restore_passage_quotes(payload, registry)
    assert restored["claims"][0]["citations"][0]["quote"] in quote
    assert "passage_id" not in restored["claims"][0]["citations"][0]


def test_unknown_or_cross_source_passage_rejects_whole_claim():
    registry = {(1, "s1_p1"): "Kafka stores events."}
    payload = {
        "claims": [
            {
                "citations": [
                    {"source_number": 1, "passage_id": "s1_p1"},
                    {"source_number": 2, "passage_id": "s1_p1"},
                ]
            }
        ]
    }
    assert restore_passage_quotes(payload, registry)["claims"][0]["citations"] == []
