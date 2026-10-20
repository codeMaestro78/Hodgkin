"""Offline benchmark integrity and aggregation, without application/provider startup."""

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

SERVICE = Path(__file__).resolve().parents[2]
SCRIPT = SERVICE / "scripts/evaluate_modes.py"
spec = importlib.util.spec_from_file_location("mode_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = evaluation
spec.loader.exec_module(evaluation)


@pytest.fixture
def cases():
    return evaluation.load_cases(evaluation.FIXTURES / "cases.jsonl")


@pytest.fixture
def raw(cases):
    return [row.model_dump() for row in evaluation.replay(cases)]


def test_frozen_baseline_and_schema_are_reproducible(cases):
    actual = evaluation.baseline()
    assert len(actual["observations"]) == 60
    assert evaluation.canonical(actual) == (evaluation.FIXTURES / "baseline.json").read_text()
    assert evaluation.load_json(evaluation.FIXTURES / "schema.json") == {
        "case": evaluation.Case.model_json_schema(),
        "observation": evaluation.Observation.model_json_schema(),
    }
    manifest = evaluation.load_json(evaluation.FIXTURES / "manifest.json")
    for name, digest in manifest.items():
        assert evaluation.sha256(evaluation.FIXTURES / name) == digest
    assert len({case.category for case in cases}) == 7
    assert all(case.label_status == "draft_awaiting_human_adjudication" for case in cases)


def test_synthetic_results_do_not_claim_live_quality_or_established_coverage(raw, cases):
    summary = evaluation.aggregate(evaluation.validate_observations(raw, cases), cases)
    assert summary["release_gate"]["status"] == "blocked"
    for mode in summary["modes"].values():
        assert mode["runs"] == 20
        assert mode["operations"] == 40
        assert mode["sources"] == 20
        assert mode["verified_findings"] == 17
        assert mode["metrics"]["claim_precision"]["value"] is None
        assert mode["metrics"]["core_dimension_coverage"]["value"] == 0
        assert mode["measurements"]["end_to_end_ms"]["p95"] is None
        assert mode["settled_cost_per_verified_finding"] is None
    assert {row["quality"] for row in raw} == {"partial", "insufficient_evidence"}
    assert all(row["requested_mode"] is None for row in raw)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(mode="answered"),
        lambda r: r.update(quality="answered"),
        lambda r: r.update(policy_origin="explicit"),
        lambda r: r.update(requested_mode="deep"),
        lambda r: r["usage"].update(sources=100),
        lambda r: r["usage"].update(operations={"search": 100}),
        lambda r: r["usage"].update(verified_findings=100),
        lambda r: r["usage"].update(sources=True),
        lambda r: r["metrics"].update(claim_precision={"numerator": 2, "denominator": 1}),
        lambda r: r["metrics"].pop("claim_precision"),
        lambda r: r["measurements"].pop("queue_wait_ms"),
        lambda r: r["measurements"].update(end_to_end_ms={"value": 10, "source": None}),
        lambda r: r["measurements"].update(end_to_end_ms={"value": float("nan"), "source": "x"}),
        lambda r: r["measurements"].update(end_to_end_ms={"value": 10, "source": "synthetic"}),
        lambda r: r.update(human_review_reference="invented review"),
        lambda r: r["human_scores"].update(directness=5),
        lambda r: r.update(unexpected="field"),
    ],
)
def test_rejects_invalid_or_misleading_observations(raw, mutate):
    row = copy.deepcopy(raw[0])
    mutate(row)
    with pytest.raises(ValidationError):
        evaluation.Observation.model_validate(row)


def test_deep_identity_survives_two_operation_limit(raw):
    row = raw[2]
    row.update(requested_mode="deep", policy_origin="explicit")
    row["limits"]["provider_operations"] = 2
    assert evaluation.Observation.model_validate(row).mode == "deep"


@pytest.mark.parametrize(
    "mutation", ["duplicate", "unknown_case", "dimensions", "snapshot", "kind"]
)
def test_rejects_incomparable_or_mismatched_inputs(raw, cases, mutation):
    if mutation == "duplicate":
        raw.append(copy.deepcopy(raw[0]))
    elif mutation == "unknown_case":
        raw[0]["case_id"] = "missing"
    elif mutation == "dimensions":
        raw[0]["dimension_states"] = {"not_a_dimension": "unknown"}
    elif mutation == "snapshot":
        raw[0]["snapshot"]["model"] = "different"
    else:
        raw[0]["evidence_kind"] = "live_observation"
    with pytest.raises(ValueError):
        evaluation.validate_observations(raw, cases)


def test_micro_ratios_latency_percentiles_and_cost_missingness(raw, cases):
    rows = [raw[0], raw[3], raw[6]]
    for index, row in enumerate(rows):
        row["evidence_kind"] = "live_observation"
        row["metrics"]["claim_precision"] = {"numerator": index + 1, "denominator": 4}
        row["measurements"]["end_to_end_ms"] = {"value": (index + 1) * 10, "source": "test"}
    rows[0]["measurements"]["settled_cost_usd"] = {"value": 0.5, "source": "test"}
    rows[0]["dimension_states"]["core"] = "established"
    summary = evaluation.aggregate(evaluation.validate_observations(rows, cases), cases)
    focused = summary["modes"]["focused"]
    assert focused["metrics"]["claim_precision"]["value"] == 0.5
    assert focused["measurements"]["end_to_end_ms"]["p50"] == 20
    assert focused["measurements"]["end_to_end_ms"]["p95"] == 30
    assert focused["settled_cost_per_verified_finding"] == 0.5
    assert focused["settled_cost_per_established_dimension"] == 0.5
    assert summary["modes"]["deep"]["measurements"]["end_to_end_ms"]["p50"] is None
    assert summary["release_gate"]["status"] == "blocked"


def test_zero_denominator_is_unknown(raw, cases):
    raw[0]["metrics"]["claim_precision"] = {"numerator": 0, "denominator": 0}
    result = evaluation.aggregate(evaluation.validate_observations(raw[:1], cases), cases)
    assert result["modes"]["focused"]["metrics"]["claim_precision"]["value"] is None


def test_cli_validates_and_release_gate_fails_closed(tmp_path):
    success = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert success.returncode == 0, success.stderr
    assert json.loads(success.stdout)["reproducible"] is True
    blocked = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "check", "--require-release"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 2
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"bad": 1, "bad": 2}')
    rejected = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "aggregate", "--input", str(invalid)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert "duplicate JSON key" in rejected.stderr


def test_cli_rejects_tampered_archived_legacy_policy(tmp_path):
    frozen = tmp_path / "modes-v1"
    shutil.copytree(evaluation.FIXTURES, frozen)
    policy_path = frozen / "legacy-policy.json"
    policy = json.loads(policy_path.read_text())
    policy["20"]["limits"]["output_tokens"] = 16_384
    policy_path.write_text(evaluation.canonical(policy))

    checked = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "check", "--fixtures", str(frozen)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert checked.returncode == 1
    assert "baseline differs" in checked.stderr
