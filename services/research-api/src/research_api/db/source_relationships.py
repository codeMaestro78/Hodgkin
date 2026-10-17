"""Isolated Phase 2 model; main must register it with migration metadata after GO."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from research_api.db.models import Base, Source

source_table: Table = Base.metadata.tables[Source.__tablename__]
if not any(c.name == "uq_sources_tenant_run_id" for c in source_table.constraints):
    source_table.append_constraint(
        UniqueConstraint("tenant_id", "run_id", "id", name="uq_sources_tenant_run_id")
    )


class SourceIdentityRecord(Base):
    __tablename__ = "source_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id", "source_id"],
            ["sources.tenant_id", "sources.run_id", "sources.id"],
            name="fk_source_identity_source",
            ondelete="CASCADE",
        ),
        CheckConstraint("jsonb_typeof(metadata_basis) = 'object'", name="ck_source_identity_basis"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    work_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(250), nullable=True)
    metadata_basis: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRelationship(Base):
    __tablename__ = "source_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id", "from_source_id"],
            ["sources.tenant_id", "sources.run_id", "sources.id"],
            name="fk_source_relationship_from",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id", "to_source_id"],
            ["sources.tenant_id", "sources.run_id", "sources.id"],
            name="fk_source_relationship_to",
            ondelete="CASCADE",
        ),
        CheckConstraint("from_source_id < to_source_id", name="ck_source_relationship_order"),
        CheckConstraint(
            "kind IN ('same_content','same_work','same_publisher')",
            name="ck_source_relationship_kind",
        ),
        CheckConstraint(
            "jsonb_typeof(basis) = 'object' AND basis <> '{}'::jsonb",
            name="ck_source_relationship_basis",
        ),
        CheckConstraint("confidence = 'observed'", name="ck_source_relationship_confidence"),
        Index("ix_source_relationship_to", "tenant_id", "run_id", "to_source_id"),
    )

    # The composite PK is also the replay conflict key and the from-endpoint index.
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    from_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    to_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    basis: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="observed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
