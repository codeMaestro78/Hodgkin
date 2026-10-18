"""Writer policy changes must not redispatch an existing paid/ambiguous request."""

import json
from types import SimpleNamespace

import pytest

from research_api.config import Settings
from research_api.graph import builder
from research_api.model_budget import model_run
from research_api.repositories.budgets import ReservationReplayError
from tests.integration.test_model_replay_accounting import client, seed

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_literal_writer_policy_preserves_legacy_receipt_and_uncertain_dispatch(ambiguous):
    identity = await seed()
    sdk = client(text='{"claims":[]}', error=ValueError("ambiguous") if ambiguous else None)
    settings = Settings(_env_file=None, OPENAI_API_KEY="fixture")
    model_token = builder.model_client.set(sdk)
    run_token = model_run.set(identity)
    args = dict(question="Kafka", source_context="Original bundle", max_search_calls=12)
    material = builder.SourceMaterial(
        source=SimpleNamespace(title="Kafka", canonical_url="https://k.test"),
        content="Kafka stores durable events.",
    )
    try:
        if ambiguous:
            with pytest.raises(ValueError, match="ambiguous"):
                await builder._synthesize_with_openai(settings, **args)
        else:
            await builder._synthesize_with_openai(settings, **args)
        sdk.responses.create.side_effect = AssertionError("must not dispatch a second request")
        if ambiguous:
            with pytest.raises(ReservationReplayError):
                await builder._synthesize_with_openai(settings, materials=[material], **args)
        else:
            result = await builder._synthesize_with_openai(settings, materials=[material], **args)
            assert result.assertions.claims == []
        assert sdk.responses.create.await_count == 1
    finally:
        model_run.reset(run_token)
        builder.model_client.reset(model_token)


async def test_passage_id_receipt_replays_without_dispatch_and_restores_original_quote():
    identity = await seed()
    quote = 'Kafka calls this "durable" event storage.'
    sdk = client(
        text=json.dumps(
            {
                "claims": [
                    {
                        "claim": "Kafka provides durable event storage.",
                        "section": "mechanisms",
                        "figures": [],
                        "caveats": [],
                        "citations": [{"source_number": 1, "passage_id": "s1_p1"}],
                    }
                ]
            }
        )
    )
    settings = Settings(_env_file=None, OPENAI_API_KEY="fixture")
    model_token = builder.model_client.set(sdk)
    run_token = model_run.set(identity)
    args = dict(
        question="Kafka",
        source_context="Original bundle",
        max_search_calls=6,
        materials=[
            builder.SourceMaterial(
                source=SimpleNamespace(title="Kafka", canonical_url="https://k.test"),
                content=quote,
            )
        ],
    )
    try:
        first = await builder._synthesize_with_openai(settings, **args)
        sdk.responses.create.side_effect = AssertionError("must reuse the paid receipt")
        second = await builder._synthesize_with_openai(settings, **args)
        assert first == second
        assert second.assertions.claims[0].citations[0].quote == quote
        assert sdk.responses.create.await_count == 1
    finally:
        model_run.reset(run_token)
        builder.model_client.reset(model_token)
