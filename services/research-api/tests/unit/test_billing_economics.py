import sys
from decimal import Decimal
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from analyze_billing_economics import analyze_receipts, load_receipts


def test_reports_mode_cost_and_provisional_cost_per_unit_including_failures():
    result = analyze_receipts(
        [
            {
                "case_id": "case-a",
                "mode": "focused",
                "status": "completed",
                "ledger_cost_usd": "0.10",
                "model_cost_usd": "0.08",
            },
            {
                "case_id": "case-b",
                "mode": "focused",
                "status": "failed",
                "ledger_cost_usd": "0.20",
                "model_cost_usd": "0.15",
            },
            {
                "case_id": "case-a",
                "mode": "balanced",
                "status": "completed",
                "ledger_cost_usd": "0.30",
                "model_cost_usd": "0.25",
            },
            {
                "case_id": "case-a",
                "mode": "deep",
                "status": "completed",
                "ledger_cost_usd": "0.80",
                "model_cost_usd": "0.70",
            },
        ]
    )

    assert result["input"]["accepted"] == 4
    assert result["modes"]["focused"]["runs"] == 2
    assert result["modes"]["focused"]["outcomes"] == {"completed": 1, "failed": 1}
    assert result["modes"]["focused"]["ledger_estimated_cost_usd"]["total"] == "0.300000"
    assert result["modes"]["focused"]["provisional_units"]["cost_per_unit_total"] == "0.150000"
    assert result["modes"]["balanced"]["provisional_units"]["cost_per_unit_total"] == "0.150000"
    assert result["modes"]["deep"]["provisional_units"]["cost_per_unit_total"] == "0.200000"


def test_uses_latest_receipt_for_duplicate_case_and_mode():
    result = analyze_receipts(
        [
            {
                "case_id": "case-a",
                "mode": "focused",
                "status": "failed",
                "ledger_cost_usd": "0.40",
            },
            {
                "case_id": "case-a",
                "mode": "focused",
                "status": "completed",
                "ledger_cost_usd": "0.12",
            },
        ]
    )

    assert result["input"]["duplicate_receipts"] == 1
    assert result["modes"]["focused"]["runs"] == 1
    assert result["modes"]["focused"]["outcomes"] == {"completed": 1}
    assert result["modes"]["focused"]["ledger_estimated_cost_usd"]["total"] == "0.120000"


def test_rejects_bad_costs_and_does_not_claim_missing_cost_is_zero():
    result = analyze_receipts(
        [
            {
                "mode": "focused",
                "status": "completed",
                "ledger_cost_usd": "NaN",
            },
            {
                "mode": "focused",
                "status": "completed",
                "ledger_cost_usd": "1e999999",
            },
            {
                "mode": "deep",
                "status": "completed",
                "ledger_cost_usd": "0.50",
                "model_cost_usd": "0.30",
            },
            {"mode": "unknown", "status": "completed", "ledger_cost_usd": "0.1"},
            "not-an-object",
        ]
    )

    assert result["input"] == {
        "rows": 5,
        "accepted": 3,
        "malformed": 1,
        "unknown_mode": 1,
        "duplicate_receipts": 0,
    }
    assert result["modes"]["focused"]["ledger_estimated_cost_usd"]["count"] == 0
    assert result["modes"]["deep"]["ledger_estimated_cost_usd"]["total"] == "0.500000"
    assert result["modes"]["deep"]["model_estimated_cost_usd"]["total"] == "0.300000"
    assert Decimal(result["modes"]["deep"]["provisional_units"]["cost_per_unit_total"]) == Decimal(
        "0.125000"
    )


def test_bounds_receipt_input_and_counts_unparseable_json():
    assert load_receipts(StringIO('{"mode":"focused"}\nnot-json\n')) == [
        {"mode": "focused"},
        None,
    ]
    try:
        load_receipts(StringIO('{"mode":"focused"}\n'), max_records=0)
    except ValueError as error:
        assert "input limit" in str(error)
    else:
        raise AssertionError("receipt record limit must be enforced")


def test_rejects_incomplete_or_nonpositive_weight_policy():
    try:
        analyze_receipts([], unit_weights={"focused": Decimal(1)})
    except ValueError as error:
        assert "unit weights" in str(error)
    else:
        raise AssertionError("an incomplete policy must not be analyzed")
