import hashlib
import hmac
import json

from pydantic import SecretStr

from research_api.billing.credit_packs import (
    configured_razorpay_credit_packs,
    razorpay_credit_topups_available,
)
from research_api.billing.razorpay import payment_signature_valid
from research_api.config import Settings


def test_payment_signature_uses_order_id_pipe_payment_id_hmac_sha256():
    secret = "fixture-secret"  # noqa: S105
    payload = "order_test_123|pay_test_456"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    assert payment_signature_valid(
        order_id="order_test_123",
        payment_id="pay_test_456",
        signature=signature,
        secret=SecretStr(secret),
    )


def test_payment_signature_rejects_mismatch_and_missing_values():
    secret = SecretStr("test-secret")

    assert not payment_signature_valid(
        order_id="order_test_123",
        payment_id="pay_test_456",
        signature="0" * 64,
        secret=secret,
    )
    assert not payment_signature_valid(
        order_id="",
        payment_id="pay_test_456",
        signature="0" * 64,
        secret=secret,
    )


def test_razorpay_pack_catalog_requires_inr_and_minimum_amount():
    valid = Settings(
        APP_ENV="test",
        RAZORPAY_CREDIT_PACKS_JSON=json.dumps(
            [
                {
                    "key": "starter",
                    "amountMinor": 100,
                    "currency": "INR",
                    "units": 5,
                    "expiryDays": None,
                }
            ]
        ),
    )
    assert configured_razorpay_credit_packs(valid)["starter"].amount_minor == 100
    assert (
        configured_razorpay_credit_packs(
            Settings(
                APP_ENV="test",
                RAZORPAY_CREDIT_PACKS_JSON=json.dumps(
                    [
                        {
                            "key": "starter",
                            "amountMinor": 99,
                            "currency": "INR",
                            "units": 5,
                            "expiryDays": None,
                        }
                    ]
                ),
            )
        )
        == {}
    )
    assert (
        configured_razorpay_credit_packs(
            Settings(
                APP_ENV="test",
                RAZORPAY_CREDIT_PACKS_JSON=json.dumps(
                    [
                        {
                            "key": "starter",
                            "amountMinor": 100,
                            "currency": "USD",
                            "units": 5,
                            "expiryDays": None,
                        }
                    ]
                ),
            )
        )
        == {}
    )


def test_razorpay_topups_are_disabled_by_default():
    assert not razorpay_credit_topups_available(Settings(APP_ENV="test"))
