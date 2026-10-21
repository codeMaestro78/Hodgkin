from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# Dispatch discovery exposes only tenant IDs and wake-up times, never research data.
# All job claims and execution are subsequently made under that tenant's RLS context.
class DispatchRegistry(Base):
    __tablename__ = "dispatch_registry"
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), primary_key=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ResearchBatch(Base):
    __tablename__ = "research_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "idempotency_key"),
        UniqueConstraint("tenant_id", "id", name="uq_batch_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_batch_owner"
        ),
        CheckConstraint(
            "(mode IS NULL AND mode_policy_version IS NULL) OR "
            "(mode IN ('focused','balanced','deep') AND mode_policy_version IS NOT NULL "
            "AND length(btrim(mode_policy_version)) > 0)",
            name="ck_research_batches_mode_snapshot",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mode_policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuntimeJob(Base):
    __tablename__ = "runtime_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_job_owner"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["research_batches.tenant_id", "research_batches.id"],
            name="fk_job_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        Index("ix_runtime_jobs_due", "tenant_id", "state", "lease_expires_at"),
        CheckConstraint("generation >= 0 AND attempts >= 0 AND active_ms >= 0"),
        CheckConstraint("state IN ('queued','running','waiting','completed','failed','cancelled')"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanApproval(Base):
    __tablename__ = "plan_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_approval_owner"
        ),
        UniqueConstraint("tenant_id", "run_id", "plan_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "plan_id"], ["research_plans.tenant_id", "research_plans.id"]
        ),
        CheckConstraint("decision IN ('approve','reject')"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchSchedule(Base):
    __tablename__ = "research_schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_schedule_owner"
        ),
        UniqueConstraint("tenant_id", "user_id", "idempotency_key"),
        CheckConstraint("interval_minutes >= 60 AND interval_minutes <= 43200"),
        CheckConstraint(
            "(mode IS NULL AND mode_policy_version IS NULL) OR "
            "(mode IN ('focused','balanced','deep') AND mode_policy_version IS NOT NULL "
            "AND length(btrim(mode_policy_version)) > 0)",
            name="ck_research_schedules_mode_snapshot",
        ),
        Index("ix_schedules_due", "tenant_id", "enabled", "next_run_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mode_policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_quota_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_quota_blocked_reason: Mapped[str | None] = mapped_column(String(64))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantScopedMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class User(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "external_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_subject: Mapped[str] = mapped_column(String(250), nullable=False)


class ResearchRun(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "research_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        UniqueConstraint("tenant_id", "user_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_report_id"],
            ["reports.tenant_id", "reports.id"],
            use_alter=True,
            name="fk_run_parent_report",
        ),
        CheckConstraint("next_event_sequence >= 0", name="ck_run_event_sequence_nonnegative"),
        Index("ix_research_runs_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_runs_parent_report", "tenant_id", "parent_report_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    original_question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mode_policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    report_requirements: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_routing: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active_plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    thread_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    next_event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    parent_report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BillingAccount(Base, TenantScopedMixin, TimestampMixin):
    """Personal billable subject, explicitly distinct from a workspace tenant."""

    __tablename__ = "billing_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_billing_accounts_tenant_id"),
        UniqueConstraint("tenant_id", "user_id", name="uq_billing_accounts_owner"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        CheckConstraint("account_type = 'personal'", name="ck_billing_account_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")


class BillingPeriod(Base, TenantScopedMixin):
    """Immutable grant/catalog snapshot for one personal account period."""

    __tablename__ = "billing_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_billing_periods_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "billing_account_id",
            "starts_at",
            "plan_key",
            name="uq_billing_period_plan_start",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "billing_account_id"],
            ["billing_accounts.tenant_id", "billing_accounts.id"],
            name="fk_billing_period_account",
        ),
        CheckConstraint(
            "plan_key IN ('free','scholar','investigator')", name="ck_billing_period_plan"
        ),
        CheckConstraint(
            "state IN ('pending','active','suspended','ended')", name="ck_billing_period_state"
        ),
        CheckConstraint("allowance_units >= 0", name="ck_billing_period_allowance"),
        CheckConstraint("starts_at < ends_at", name="ck_billing_period_bounds"),
        Index(
            "ix_billing_periods_owner_state_start",
            "tenant_id",
            "billing_account_id",
            "state",
            "starts_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    billing_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    plan_key: Mapped[str] = mapped_column(String(24), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    allowance_units: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingUnitEntry(Base, TenantScopedMixin):
    """Append-only deltas used by atomic quota admission and settlement."""

    __tablename__ = "billing_unit_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "billing_account_id"],
            ["billing_accounts.tenant_id", "billing_accounts.id"],
            name="fk_billing_unit_entry_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "billing_period_id"],
            ["billing_periods.tenant_id", "billing_periods.id"],
            name="fk_billing_unit_entry_period",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        CheckConstraint(
            "(entry_type = 'reservation' AND consumed_delta = 0 AND reserved_delta > 0) OR "
            "(entry_type = 'consumption' AND consumed_delta > 0 AND reserved_delta < 0) OR "
            "(entry_type = 'release' AND consumed_delta = 0 AND reserved_delta < 0) OR "
            "(entry_type = 'adjustment' AND consumed_delta <> 0 AND reserved_delta = 0)",
            name="ck_billing_unit_entry_shape",
        ),
        CheckConstraint(
            "(entry_type = 'adjustment' AND actor_id IS NOT NULL AND reason IS NOT NULL AND "
            "length(btrim(reason)) BETWEEN 1 AND 500) OR "
            "(entry_type <> 'adjustment' AND actor_id IS NULL AND reason IS NULL)",
            name="ck_billing_adjustment_audit",
        ),
        Index(
            "ix_billing_unit_entries_period_created",
            "tenant_id",
            "billing_account_id",
            "billing_period_id",
            "created_at",
        ),
        Index(
            "uq_billing_unit_owner_idempotency",
            "tenant_id",
            "billing_account_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "uq_billing_reservation_run",
            "tenant_id",
            "run_id",
            unique=True,
            postgresql_where=text("entry_type = 'reservation' AND run_id IS NOT NULL"),
        ),
        Index(
            "uq_billing_settlement_run",
            "tenant_id",
            "run_id",
            unique=True,
            postgresql_where=text(
                "entry_type IN ('consumption', 'release') AND run_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    billing_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    billing_period_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    consumed_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingCreditPurchase(Base, TenantScopedMixin):
    """Minimal one-time pack order projection; never stores raw Stripe payloads."""

    __tablename__ = "billing_credit_purchases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_billing_credit_purchase_tenant_id"),
        UniqueConstraint(
            "tenant_id", "billing_account_id", "id", name="uq_billing_credit_purchase_owner"
        ),
        UniqueConstraint(
            "tenant_id",
            "billing_account_id",
            "request_key_hash",
            name="uq_billing_credit_purchase_request_key",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "billing_account_id"],
            ["billing_accounts.tenant_id", "billing_accounts.id"],
            name="fk_billing_credit_purchase_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_billing_credit_purchase_user",
        ),
        CheckConstraint("length(btrim(package_key)) BETWEEN 1 AND 64"),
        CheckConstraint("length(btrim(stripe_price_id)) BETWEEN 1 AND 255"),
        CheckConstraint("amount_minor > 0 AND unit_grant > 0"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_billing_credit_purchase_currency"),
        CheckConstraint(
            "state IN ('pending','paid','failed','refunded','disputed','reconciliation_required')",
            name="ck_billing_credit_purchase_state",
        ),
        UniqueConstraint("stripe_checkout_session_id", name="uq_billing_credit_checkout_session"),
        UniqueConstraint("stripe_payment_intent_id", name="uq_billing_credit_payment_intent"),
        Index(
            "ix_billing_credit_purchase_account_created",
            "tenant_id",
            "billing_account_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    billing_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    package_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stripe_price_id: Mapped[str] = mapped_column(String(255), nullable=False)
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stripe_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    terms_version: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_grant: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BillingCreditEntry(Base, TenantScopedMixin):
    """Append-only purchased-credit lot ledger; independent of monthly allowances."""

    __tablename__ = "billing_credit_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "billing_account_id"],
            ["billing_accounts.tenant_id", "billing_accounts.id"],
            name="fk_billing_credit_entry_account",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "billing_account_id", "purchase_id"],
            [
                "billing_credit_purchases.tenant_id",
                "billing_credit_purchases.billing_account_id",
                "billing_credit_purchases.id",
            ],
            name="fk_billing_credit_entry_purchase_owner",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        CheckConstraint(
            "(entry_type = 'grant' AND available_delta > 0 "
            "AND reserved_delta = 0 AND run_id IS NULL) OR "
            "(entry_type = 'reservation' AND available_delta < 0 "
            "AND reserved_delta = -available_delta AND run_id IS NOT NULL) OR "
            "(entry_type = 'consumption' AND available_delta = 0 "
            "AND reserved_delta < 0 AND run_id IS NOT NULL) OR "
            "(entry_type = 'release' AND available_delta > 0 "
            "AND reserved_delta = -available_delta AND run_id IS NOT NULL) OR "
            "(entry_type = 'reversal' AND available_delta < 0 "
            "AND reserved_delta = 0 AND run_id IS NULL)",
            name="ck_billing_credit_entry_shape",
        ),
        Index(
            "uq_billing_credit_owner_idempotency",
            "tenant_id",
            "billing_account_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_billing_credit_purchase_created",
            "tenant_id",
            "billing_account_id",
            "purchase_id",
            "created_at",
        ),
        Index(
            "uq_billing_credit_run_purchase_type",
            "tenant_id",
            "run_id",
            "purchase_id",
            "entry_type",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    billing_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    purchase_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    available_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingShadowObservation(Base):
    """Immutable, non-enforcing unit-policy snapshot for one admitted run."""

    __tablename__ = "billing_shadow_observations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", name="uq_billing_shadow_tenant_run"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["research_runs.tenant_id", "research_runs.id"],
            name="fk_billing_shadow_run",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_billing_shadow_user",
        ),
        CheckConstraint(
            "(decision_status = 'provisional' "
            "AND policy_version = 'approved-mode-weights-1-2-4-v1' "
            "AND catalog_version IN ('research-units-v1-2026-10-19', "
            "'research-units-v2-2026-10-19') AND "
            "((mode = 'focused' AND proposed_units = 1) OR "
            "(mode = 'balanced' AND proposed_units = 2) OR "
            "(mode = 'deep' AND proposed_units = 4))) OR "
            "(decision_status = 'unpriced_legacy_mode' AND mode IS NULL "
            "AND proposed_units IS NULL AND policy_version IS NULL "
            "AND catalog_version IS NULL)",
            name="ck_billing_shadow_decision_shape",
        ),
        Index("ix_billing_shadow_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_status: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    catalog_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StripeWebhookEvent(Base):
    """Minimal deduplication inbox; intentionally excludes raw Stripe payloads."""

    __tablename__ = "stripe_webhook_events"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('received','ignored','processed','stale',"
            "'reconciliation_required')",
            name="ck_stripe_webhook_event_status",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    event_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    object_id: Mapped[str | None] = mapped_column(String(255))
    livemode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StripeCustomerLink(Base):
    """Server-owned mapping from a personal research account to Stripe Customer."""

    __tablename__ = "stripe_customer_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_stripe_customer_owner"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_stripe_customer_owner",
        ),
    )

    stripe_customer_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StripeSubscription(Base):
    """Minimal, replay-ordered subscription projection; never stores Stripe payloads."""

    __tablename__ = "stripe_subscriptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_stripe_subscription_owner",
        ),
        ForeignKeyConstraint(
            ["stripe_customer_id"],
            ["stripe_customer_links.stripe_customer_id"],
            name="fk_stripe_subscription_customer",
        ),
        CheckConstraint(
            "plan_key IS NULL OR plan_key IN ('scholar','investigator')",
            name="ck_stripe_subscription_plan",
        ),
        CheckConstraint(
            "current_period_start IS NULL OR current_period_end IS NULL OR "
            "current_period_start < current_period_end",
            name="ck_stripe_subscription_period",
        ),
        Index("ix_stripe_subscriptions_owner", "tenant_id", "user_id"),
    )

    stripe_subscription_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    plan_key: Mapped[str | None] = mapped_column(String(24))
    price_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_created: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StripeCheckoutAttempt(Base):
    """Owner-scoped idempotency and single-open-checkout guard."""

    __tablename__ = "stripe_checkout_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_stripe_checkout_owner",
        ),
        CheckConstraint(
            "plan_key IN ('scholar','investigator')",
            name="ck_stripe_checkout_plan",
        ),
        CheckConstraint(
            "state IN ('open','completed','expired','failed')",
            name="ck_stripe_checkout_state",
        ),
        UniqueConstraint(
            "tenant_id", "user_id", "request_key_hash", name="uq_stripe_checkout_request"
        ),
        Index(
            "uq_stripe_checkout_one_open_per_owner",
            "tenant_id",
            "user_id",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stripe_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    plan_key: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchPlan(Base, TenantScopedMixin):
    __tablename__ = "research_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "run_id", "plan_version"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_plan_version: Mapped[int | None] = mapped_column(Integer)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubQuestion(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "sub_questions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "plan_id"], ["research_plans.tenant_id", "research_plans.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_plans.id"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SubQuestionAttempt(Base, TenantScopedMixin):
    __tablename__ = "sub_question_attempts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sub_question_id", "attempt"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sub_question_id"], ["sub_questions.tenant_id", "sub_questions.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    sub_question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sub_questions.id"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Source(Base, TenantScopedMixin):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "run_id", "canonical_url", "content_hash"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sub_question_id"], ["sub_questions.tenant_id", "sub_questions.id"]
        ),
        Index("ix_sources_tenant_content_hash", "tenant_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    sub_question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sub_questions.id"), nullable=True
    )
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(250))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_class: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    discovery_paths: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    content_signature: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class EvidenceClaim(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "evidence_claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sub_question_id"], ["sub_questions.tenant_id", "sub_questions.id"]
        ),
        Index("ix_evidence_claims_tenant_subquestion", "tenant_id", "sub_question_id"),
        ForeignKeyConstraint(
            ["tenant_id", "report_id"], ["reports.tenant_id", "reports.id"], name="fk_claim_report"
        ),
        Index("ix_claims_tenant_report", "tenant_id", "report_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    sub_question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sub_questions.id"), nullable=False
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    support: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    caveats: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    provenance: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class Citation(Base, TenantScopedMixin):
    __tablename__ = "citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "evidence_claim_id"],
            ["evidence_claims.tenant_id", "evidence_claims.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "source_id"], ["sources.tenant_id", "sources.id"]),
        Index("ix_citations_tenant_claim", "tenant_id", "evidence_claim_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    evidence_claim_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("evidence_claims.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sources.id"), nullable=False)
    quote: Mapped[str] = mapped_column(String(600), nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verification: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Contradiction(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "contradictions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        Index("ix_contradictions_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    evidence_claim_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")


class ResearchGap(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "gaps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        Index("ix_gaps_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    materiality: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    target_query: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Budget(Base, TenantScopedMixin):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    max_wall_clock_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_search_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    max_provider_operations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_sources: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_browser_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_reflection_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)


class UsageLedger(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "usage_ledger"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    search_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_search_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    browser_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    reserved_estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )


class ProviderCallReservation(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "provider_call_reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "request_fingerprint", "attempt"),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "run_id", "id", name="uq_reservations_tenant_run_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        CheckConstraint("reserved_search_calls >= 0", name="ck_reservation_search_calls"),
        CheckConstraint("reserved_estimated_cost_usd >= 0", name="ck_reservation_cost"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reserved_search_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractionSlot(Base, TenantScopedMixin, TimestampMixin):
    """One admitted canonical URL per run; unknown dispatches retain quota."""

    __tablename__ = "extraction_slots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "url_fingerprint"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id", "reservation_id"],
            [
                "provider_call_reservations.tenant_id",
                "provider_call_reservations.run_id",
                "provider_call_reservations.id",
            ],
        ),
        CheckConstraint(
            "state IN ('reserved','consumed','released','uncertain')",
            name="ck_extraction_slot_state",
        ),
        Index("ix_extraction_slots_run_state", "tenant_id", "run_id", "state"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    url_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")


class ProviderCall(Base, TenantScopedMixin):
    __tablename__ = "provider_calls"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reservation_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["provider_call_reservations.tenant_id", "provider_call_reservations.id"],
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("provider_call_reservations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    request_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    response_schema_version: Mapped[str | None] = mapped_column(String(40))
    provider_request_id: Mapped[str | None] = mapped_column(String(250))
    provider_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    response_artifact_ref: Mapped[str | None] = mapped_column(String(1024))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NodeExecution(Base, TenantScopedMixin):
    __tablename__ = "node_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "node_id", "attempt", "output_hash"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base, TenantScopedMixin):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "event_sequence"),
        UniqueConstraint("tenant_id", "event_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        Index("ix_run_events_tenant_run_sequence", "tenant_id", "run_id", "event_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Report(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "version"),
        UniqueConstraint("tenant_id", "id", name="uq_reports_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_runs.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable for historical Markdown reports; never infer a retrospective assessment.
    document: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Captured before publication; NULL means this legacy report has no snapshot.
    retrieval_accounting: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(64))


class ReportShare(Base, TenantScopedMixin):
    __tablename__ = "report_shares"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        ForeignKeyConstraint(["tenant_id", "report_id"], ["reports.tenant_id", "reports.id"]),
        UniqueConstraint("token_hash"),
        CheckConstraint("expires_at > created_at", name="ck_report_share_expiry"),
        Index("ix_report_shares_owner", "tenant_id", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Only a SHA-256 digest of the high-entropy bearer secret is persisted.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReportExport(Base, TenantScopedMixin):
    __tablename__ = "report_exports"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        ForeignKeyConstraint(["tenant_id", "report_id"], ["reports.tenant_id", "reports.id"]),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "report_id",
            "format",
            "renderer_version",
            name="uq_report_exports_owner_report_format_renderer",
        ),
        CheckConstraint("format IN ('markdown','bibtex')", name="ck_report_export_format"),
        CheckConstraint(
            "size_bytes BETWEEN 0 AND 1048576 AND octet_length(content) = size_bytes",
            name="ck_report_export_size",
        ),
        Index("ix_report_exports_owner", "tenant_id", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evaluation(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["research_runs.tenant_id", "research_runs.id"]
        ),
        Index("ix_evaluations_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_runs.id"), nullable=True
    )
    benchmark_case_id: Mapped[str] = mapped_column(String(200), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Project(Base, TenantScopedMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "id", name="uq_project_owner_id"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 100 AND name = btrim(name)", name="ck_project_name"
        ),
        Index("ix_projects_owner", "tenant_id", "user_id", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LibraryItem(Base, TenantScopedMixin):
    __tablename__ = "library_items"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "user_id", "project_id"],
            ["projects.tenant_id", "projects.user_id", "projects.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "report_id"], ["reports.tenant_id", "reports.id"]),
        ForeignKeyConstraint(["tenant_id", "source_id"], ["sources.tenant_id", "sources.id"]),
        UniqueConstraint("tenant_id", "user_id", "report_id", name="uq_library_report"),
        UniqueConstraint("tenant_id", "user_id", "source_id", name="uq_library_source"),
        CheckConstraint("(report_id IS NULL) <> (source_id IS NULL)", name="ck_library_target"),
        CheckConstraint("length(notes) <= 2000", name="ck_library_notes"),
        CheckConstraint(
            "jsonb_typeof(tags) = 'array' AND jsonb_array_length(tags) <= 10 "
            "AND NOT jsonb_path_exists(tags, '$[*] ? (@.type() != \"string\")') "
            'AND NOT jsonb_path_exists(tags, \'$[*] ? (@ like_regex "^.{41,}$" flag "s")\')',
            name="ck_library_tags",
        ),
        Index("ix_library_owner_cursor", "tenant_id", "user_id", "id"),
        Index("ix_library_project", "tenant_id", "user_id", "project_id", "id"),
        Index("ix_library_report", "tenant_id", "report_id"),
        Index("ix_library_source", "tenant_id", "source_id"),
        Index("ix_library_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
