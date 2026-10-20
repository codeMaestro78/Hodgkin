from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.config import Settings
from research_api.graph import builder
from research_api.mode_reports import policy_for_mode
from research_api.report_document import build_report_document
from research_api.reports import report_policy


@pytest.mark.parametrize("mode", ["focused", "balanced", "deep"])
def test_small_budget_preserves_explicit_report_mode(mode):
    policy = policy_for_mode(2, mode=mode, max_sources=1)
    assert policy.mode == mode
    assert policy.source_count == 1
    assert (
        policy.output_tokens
        == report_policy({"focused": 6, "balanced": 12, "deep": 20}[mode]).output_tokens
    )


@pytest.mark.parametrize("calls", [2, 6, 12, 20])
def test_legacy_report_policy_is_identical(calls):
    assert policy_for_mode(calls) == report_policy(calls)


def test_unknown_explicit_mode_fails_closed():
    with pytest.raises(ValueError, match="unknown"):
        policy_for_mode(6, mode="unbounded")


async def test_small_explicit_deep_budget_keeps_deep_writer_schema(monkeypatch):
    response = AsyncMock(return_value=SimpleNamespace(output_text='{"claims":[]}'))
    monkeypatch.setattr(builder, "_model_response", response)
    await builder._synthesize_with_openai(
        Settings(_env_file=None, OPENAI_API_KEY="fixture"),
        question="What is durable execution?",
        source_context="SOURCE [1] bounded local fixture",
        max_search_calls=2,
        mode="deep",
    )
    request = response.call_args.kwargs
    assert request["text"]["format"]["name"] == "deep_claim_draft"
    assert request["max_output_tokens"] == 16384


def test_small_explicit_deep_budget_keeps_document_mode_and_honest_quality():
    doc = build_report_document(
        question="What is durable execution?",
        max_search_calls=2,
        mode="deep",
        requirements=[],
        findings=[],
        questions=[],
        excluded=0,
    )
    assert doc["mode"] == "deep"
    assert doc["quality"]["status"] == "insufficient_evidence"
