from pathlib import Path

from research_api.db.models import BillingCreditPurchase


def test_razorpay_migration_is_forward_only_and_preserves_stripe_history():
    migration = (
        Path(__file__).parents[2]
        / "src/research_api/db/migrations/versions/0033_razorpay_credit_orders.py"
    ).read_text()

    assert 'revision = "0033"' in migration
    assert 'down_revision = "0032"' in migration
    assert "DROP NOT NULL" in migration
    assert "provider_order_id" in migration
    assert "provider_payment_id" in migration
    assert "DROP TABLE" not in migration
    assert "Preserve Razorpay payment references" in migration


def test_purchase_model_has_provider_neutral_receipt_fields():
    columns = BillingCreditPurchase.__table__.columns
    assert columns["payment_provider"].nullable is False
    assert columns["provider_order_id"].nullable is True
    assert columns["provider_payment_id"].nullable is True
    assert columns["stripe_price_id"].nullable is True
