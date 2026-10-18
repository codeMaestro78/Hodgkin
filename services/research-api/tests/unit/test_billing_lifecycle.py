import pytest

from research_api.billing.lifecycle import settlement_outcome, stripe_signature_valid


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


def test_stripe_signature_verifies_exact_raw_body_and_enforces_timestamp_tolerance():
    body = b'{"id":"evt_123","type":"ping"}'
    signature = "t=1700000000,v1=70f66647c6b3343e86d7f0e43b94f48330fb636d0126974525111d3a7e4ea154"

    assert stripe_signature_valid(body, signature, "whsec_test_secret", now_seconds=1_700_000_000)
    assert not stripe_signature_valid(
        body + b" ", signature, "whsec_test_secret", now_seconds=1_700_000_000
    )
    assert not stripe_signature_valid(
        body, signature, "whsec_test_secret", now_seconds=1_700_000_301
    )
