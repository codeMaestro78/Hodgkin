"""Report-scoped checks, discovery paths and immutable follow-up links.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing tenant RLS and API-role revocations remain in force on these tables.
    op.execute("""
        ALTER TABLE sources ADD COLUMN IF NOT EXISTS discovery_paths jsonb NOT NULL DEFAULT '[]';
        ALTER TABLE sources ADD COLUMN IF NOT EXISTS content_signature jsonb NOT NULL DEFAULT '[]';
        ALTER TABLE gaps ADD COLUMN IF NOT EXISTS details jsonb NOT NULL DEFAULT '{}';
        ALTER TABLE evidence_claims ADD COLUMN IF NOT EXISTS report_id uuid;
        ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS parent_report_id uuid;
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_reports_tenant_id' AND conrelid = 'reports'::regclass) THEN
                ALTER TABLE reports ADD CONSTRAINT uq_reports_tenant_id UNIQUE (tenant_id, id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_claim_report' AND conrelid = 'evidence_claims'::regclass) THEN
                ALTER TABLE evidence_claims ADD CONSTRAINT fk_claim_report
                    FOREIGN KEY (tenant_id, report_id) REFERENCES reports(tenant_id, id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_run_parent_report'
                    AND conrelid = 'research_runs'::regclass) THEN
                ALTER TABLE research_runs ADD CONSTRAINT fk_run_parent_report
                    FOREIGN KEY (tenant_id, parent_report_id) REFERENCES reports(tenant_id, id);
            END IF;
        END $$;
        CREATE INDEX IF NOT EXISTS ix_claims_tenant_report ON evidence_claims(tenant_id, report_id);
        CREATE INDEX IF NOT EXISTS ix_runs_parent_report
            ON research_runs(tenant_id, parent_report_id);
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE research_runs DROP COLUMN parent_report_id;
        ALTER TABLE evidence_claims DROP COLUMN report_id;
        ALTER TABLE gaps DROP COLUMN details;
        ALTER TABLE sources DROP COLUMN discovery_paths;
        ALTER TABLE sources DROP COLUMN content_signature;
        ALTER TABLE reports DROP CONSTRAINT uq_reports_tenant_id;
    """)
