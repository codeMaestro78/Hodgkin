from research_api.api import _public_repair_outcome


def test_repaired_outcome_exposes_only_supported_public_counts():
    assert _public_repair_outcome(
        {
            "status": "repaired",
            "reason": None,
            "new_source_count": 2,
            "delta_claim_count": 3,
            "failure": "private provider detail",
            "dimension_ids": ["private"],
        }
    ) == {
        "status": "repaired",
        "newSourceCount": 2,
        "verifiedFindingCount": 3,
    }


def test_stopped_outcome_omits_unrecognized_reasons_and_internal_failure():
    assert _public_repair_outcome(
        {
            "status": "stopped",
            "reason": "upstream-secret-error",
            "failure": "provider returned a credential-bearing response",
            "new_source_count": -1,
            "delta_claim_count": True,
        }
    ) == {"status": "stopped"}


def test_repair_projection_omits_unknown_statuses():
    assert _public_repair_outcome({"status": "running"}) is None
    assert _public_repair_outcome(None) is None
