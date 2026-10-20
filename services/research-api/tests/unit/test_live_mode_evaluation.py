import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "live_mode_evaluation", ROOT / "scripts/live_mode_evaluation.py"
)
live = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = live
spec.loader.exec_module(live)

from evaluate_modes import load_cases, validate_observations  # noqa: E402

from research_api.mode_policy import resolve_mode_budget  # noqa: E402

CASES = load_cases(ROOT / "evaluation/modes/v1/cases.jsonl")
SNAPSHOT = {
    "model": "gpt-4o-mini",
    "provider": "openai+tavily",
    "prompt": "source_tree_sha256:" + "0" * 64,
    "schema": "modes-observation-v1",
    "graph": "graph",
    "policy": "policy",
}
LIMITS = {
    "provider_operations": 6,
    "sources": 6,
    "candidate_findings": 12,
    "context_chars": 12000,
    "output_tokens": 4096,
    "plan_questions": 3,
}


def receipt(**overrides):
    return {
        "status": "completed",
        "operations": {"search": 2, "extract": 1},
        "sources": 3,
        "verified_findings": 2,
        "input_tokens": 1200,
        "output_tokens": 300,
        "ledger_cost_usd": "0.031000",
        "model_cost_usd": "0.007000",
        "first_source_ms": 4100,
        "end_to_end_ms": 52000,
    } | overrides


def test_worst_case_uses_run_token_ceilings_and_admission_is_inclusive():
    budget = resolve_mode_budget("deep")
    worst = live.worst_case_model_usd(budget, "gpt-4o-mini", "openai")
    assert budget.max_output_tokens == 40_000
    assert worst == Decimal("0.039000")
    assert live.admit(Decimal("2.961"), worst, Decimal("3.00"))
    assert not live.admit(Decimal("2.961001"), worst, Decimal("3.00"))
    archived = resolve_mode_budget("deep", policy_version="research-mode-policy-v1")
    assert live.worst_case_model_usd(archived, "gpt-4o-mini", "openai") == Decimal("0.027000")
    assert live.worst_case_model_usd(budget, "unpriced", "openai") == budget.max_estimated_cost_usd


def test_live_observation_validates_and_makes_no_quality_claims():
    row = live.observation(CASES[0], "focused", receipt(), SNAPSHOT, LIMITS)
    (validated,) = validate_observations([row], CASES)
    assert validated.evidence_kind == "live_observation"
    assert validated.policy_origin == "explicit" and validated.requested_mode == "focused"
    assert set(validated.dimension_states.values()) == {"unknown"}
    assert all(value is None for value in validated.metrics.values())
    assert all(value is None for value in validated.human_scores.values())
    assert validated.human_review_reference is None
    assert validated.measurements["settled_cost_usd"].value == 0.007
    assert not validated.failed and validated.quality == "partial"


def test_failed_run_without_evidence_is_recorded_honestly():
    row = live.observation(
        CASES[1],
        "deep",
        receipt(status="failed", verified_findings=0, first_source_ms=None),
        SNAPSHOT,
        LIMITS,
    )
    (validated,) = validate_observations([row], CASES)
    assert validated.failed and validated.quality == "insufficient_evidence"
    first = validated.measurements["first_useful_evidence_ms"]
    assert first.value is None and first.source is None


def test_receipt_digest_changes_with_receipt_content():
    first = live.observation(CASES[0], "focused", receipt(), SNAPSHOT, LIMITS)
    second = live.observation(CASES[0], "focused", receipt(sources=4), SNAPSHOT, LIMITS)
    assert first["receipt_sha256"] != second["receipt_sha256"]


def test_env_reader_requires_provider_keys(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY='a'\nDATABASE_URL=postgresql://remote/db\nLLM_MODEL_NAME=m\n")
    with pytest.raises(SystemExit):
        live.read_env_keys(path)
    path.write_text(path.read_text() + 'TAVILY_API_KEY="b"\n')
    assert live.read_env_keys(path) == {
        "OPENAI_API_KEY": "a",
        "TAVILY_API_KEY": "b",
        "LLM_MODEL_NAME": "m",
    }


def test_loopback_guard_rejects_remote_hosts():
    live.require_loopback("postgresql://u@127.0.0.1:55432/research", "DATABASE_URL")
    with pytest.raises(SystemExit):
        live.require_loopback("postgresql://u@db.example.com:5432/research", "DATABASE_URL")
