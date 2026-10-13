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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    report_requirements: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    active_plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    thread_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    next_event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    parent_report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


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
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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
