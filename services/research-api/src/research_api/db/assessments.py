"""Isolated explicit-mode assessment mapping; importing registers it with Base."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from research_api.db.models import Base, ResearchPlan, TenantScopedMixin

MANIFEST_MAX_BYTES = 256 * 1024
RESULT_MAX_BYTES = 512 * 1024
PLAN_SCOPE_CONSTRAINT = "uq_research_plans_tenant_run_id"

# 0001 creates current metadata on fresh installs. Register the FK target here
# without editing the shared models module; 0015 adds it conditionally on upgrades.
_plans_table = Base.metadata.tables[ResearchPlan.__tablename__]
assert isinstance(_plans_table, Table)
if not any(c.name == PLAN_SCOPE_CONSTRAINT for c in _plans_table.constraints):
    _plans_table.append_constraint(
        UniqueConstraint("tenant_id", "run_id", "id", name=PLAN_SCOPE_CONSTRAINT)
    )


class ResearchAssessment(Base, TenantScopedMixin):
    __tablename__ = "research_assessments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "plan_id", name="uq_assessment_plan"),
        UniqueConstraint(
            "tenant_id", "run_id", "plan_id", "evidence_key", name="uq_assessment_evidence"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id", "plan_id"],
            ["research_plans.tenant_id", "research_plans.run_id", "research_plans.id"],
            name="fk_assessment_plan_scope",
        ),
        CheckConstraint("length(evidence_key) BETWEEN 1 AND 64", name="ck_assessment_key"),
        CheckConstraint(
            "jsonb_typeof(manifest) = 'object' AND octet_length(manifest::text) <= 262144",
            name="ck_assessment_manifest",
        ),
        CheckConstraint(
            "result IS NULL OR (jsonb_typeof(result) = 'object' "
            "AND octet_length(result::text) <= 524288)",
            name="ck_assessment_result",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
