import pytest

from research_api.billing.lifecycle import settlement_outcome


@pytest.mark.parametrize(
    ("status", "unresolved", "dispatched", "expected"),
    [
        ("completed", False, False, "consume"),
        ("failed", False, True, "release"),
        ("cancelled", False, False, "release"),
        ("cancelled", False, True, "consume"),
        ("completed", True, True, None),
        ("cancelled", True, True, None),
        ("running", False, False, None),
    ],
)
def test_terminal_settlement_policy(status, unresolved, dispatched, expected):
    assert (
        settlement_outcome(
            status,
            unresolved_provider_call=unresolved,
            provider_dispatched=dispatched,
        )
        == expected
    )
