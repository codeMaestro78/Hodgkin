"""authoritative tenant-safe application core

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

from research_api.db.models import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "users",
    "research_runs",
    "research_plans",
    "sub_questions",
    "sub_question_attempts",
    "sources",
    "evidence_claims",
    "citations",
    "contradictions",
    "gaps",
    "budgets",
    "usage_ledger",
    "provider_call_reservations",
    "provider_calls",
    "node_executions",
    "run_events",
    "reports",
    "evaluations",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_scope ON tenants USING "
        "(id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{table}" USING '
            "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )

    # The Docker development environment creates research_app. Supabase uses its
    # dashboard-provided database role instead, so grants must not assume that a
    # local-only role exists.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') "
        "THEN GRANT USAGE ON SCHEMA public TO research_app; "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO research_app; "
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO research_app; "
        "END IF; END $$;"
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
