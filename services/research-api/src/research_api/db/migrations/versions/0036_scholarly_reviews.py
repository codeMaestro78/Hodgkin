"""Owner-scoped scholarly reviews and append-only workflow evidence.

Revision ID: 0036
Revises: 0035
"""

from typing import cast

from alembic import op
from sqlalchemy import Table

from research_api.db.models import (
    CollaborationAudit,
    CollaborationMember,
    LivingEvent,
    LivingWatch,
    ScholarlyAuditEvent,
    ScholarlyDuplicateMark,
    ScholarlyEvidenceRow,
    ScholarlyRetrievalReceipt,
    ScholarlyReview,
    ScholarlyScreeningDecision,
    ScholarlySearchExecution,
    ScholarlySearchRecord,
    ScholarlyStudyArtifact,
)

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

MODELS = (
    ScholarlyReview,
    ScholarlySearchExecution,
    ScholarlySearchRecord,
    ScholarlyScreeningDecision,
    ScholarlyRetrievalReceipt,
    ScholarlyDuplicateMark,
    ScholarlyStudyArtifact,
    ScholarlyEvidenceRow,
    ScholarlyAuditEvent,
)
LIVING_MODELS = (LivingWatch, CollaborationMember, LivingEvent, CollaborationAudit)


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public")
    op.execute("""
        CREATE FUNCTION public.scholarly_reject_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'scholarly review history is append-only';
        END $$
    """)
    review_owner = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid "
        "AND owner_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid"
    )
    for review_model in MODELS:
        cast(Table, review_model.__table__).create(op.get_bind(), checkfirst=True)
        table = review_model.__tablename__
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY owner_scope ON public.{table} "
            f"USING ({review_owner}) WITH CHECK ({review_owner})"
        )
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        op.execute(f"""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                REVOKE ALL ON public.{table} FROM research_app;
                GRANT SELECT, INSERT ON public.{table} TO research_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON public.{table} FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON public.{table} FROM authenticated;
            END IF;
        END $$;""")  # noqa: S608
        op.execute(
            f"CREATE TRIGGER scholarly_append_only BEFORE UPDATE OR DELETE ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.scholarly_reject_mutation()"
        )

    checks = {
        "scholarly_reviews": ["length(btrim(title)) > 0", "length(btrim(question)) > 0"],
        "scholarly_search_executions": [
            "length(btrim(search_id)) > 0",
            "length(btrim(query)) > 0",
            "length(btrim(database)) > 0",
            "reported_result_count IS NULL OR reported_result_count >= 0",
            "jsonb_typeof(filters) = 'array'",
            "jsonb_typeof(result_record_ids) = 'array'",
        ],
        "scholarly_search_records": [
            "length(btrim(record_id)) > 0",
            "length(btrim(title)) > 0",
            "length(btrim(provider)) > 0",
            "length(btrim(provider_record_id)) > 0",
        ],
        "scholarly_screening_decisions": [
            "stage IN ('title_abstract', 'full_text')",
            "outcome IN ('include', 'exclude', 'maybe')",
            "(outcome = 'exclude') = (exclusion_reason IS NOT NULL)",
            "(stage = 'full_text') = (source_id IS NOT NULL)",
        ],
        "scholarly_retrieval_receipts": [
            "status IN ('retrieved', 'not_retrieved')",
            "(status = 'retrieved') = (source_id IS NOT NULL)",
        ],
        "scholarly_duplicate_marks": ["record_id <> canonical_record_id"],
        "scholarly_study_artifacts": [
            "content_hash ~ '^[0-9a-f]{64}$'",
            "length(btrim(artifact_ref)) > 0",
            "jsonb_typeof(page_anchors) = 'array'",
        ],
        "scholarly_evidence_rows": [
            "length(btrim(source_id)) > 0",
            "length(btrim(claim)) > 0",
            "length(btrim(quote)) > 0",
        ],
    }
    for table, expressions in checks.items():
        for index, expression in enumerate(expressions):
            op.execute(
                f"ALTER TABLE public.{table} ADD CONSTRAINT ck_{table}_{index} CHECK ({expression})"
            )

    for living_model in LIVING_MODELS:
        cast(Table, living_model.__table__).create(op.get_bind(), checkfirst=True)
        table = living_model.__tablename__
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        op.execute(f"""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'research_app') THEN
                REVOKE ALL ON public.{table} FROM research_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO research_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON public.{table} FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON public.{table} FROM authenticated;
            END IF;
        END $$;""")  # noqa: S608

    actor = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    tenant = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    member = (  # noqa: S608 - static migration identifiers only
        "EXISTS (SELECT 1 FROM public.collaboration_members m "  # noqa: S608
        f"WHERE m.tenant_id = living_watches.tenant_id AND m.watch_id = living_watches.id "
        f"AND m.user_id = {actor})"
    )
    op.execute(f"""CREATE POLICY watch_select ON public.living_watches FOR SELECT
        USING (tenant_id = {tenant} AND (owner_user_id = {actor} OR {member}))""")
    op.execute(f"""CREATE POLICY watch_insert ON public.living_watches FOR INSERT
        WITH CHECK (tenant_id = {tenant} AND owner_user_id = {actor})""")
    op.execute(f"""CREATE POLICY watch_update ON public.living_watches FOR UPDATE
        USING (tenant_id = {tenant} AND owner_user_id = {actor})
        WITH CHECK (tenant_id = {tenant} AND owner_user_id = {actor})""")
    def watch_owner(table: str) -> str:
        return (  # noqa: S608 - table comes only from literals in this migration
            "EXISTS (SELECT 1 FROM public.living_watches w "  # noqa: S608
            f"WHERE w.tenant_id = {table}.tenant_id AND w.id = {table}.watch_id "
            f"AND w.owner_user_id = {actor})"
        )
    op.execute(f"""CREATE POLICY member_select ON public.collaboration_members FOR SELECT
        USING (tenant_id = {tenant} AND (user_id = {actor} OR invited_by = {actor}))""")
    op.execute(f"""CREATE POLICY member_insert ON public.collaboration_members FOR INSERT
        WITH CHECK (tenant_id = {tenant} AND invited_by = {actor}
        AND {watch_owner('collaboration_members')})""")
    op.execute(f"""CREATE POLICY member_update ON public.collaboration_members FOR UPDATE
        USING (tenant_id = {tenant} AND {watch_owner('collaboration_members')})
        WITH CHECK (tenant_id = {tenant} AND {watch_owner('collaboration_members')})""")
    op.execute(f"""CREATE POLICY member_delete ON public.collaboration_members FOR DELETE
        USING (tenant_id = {tenant} AND {watch_owner('collaboration_members')})""")
    for table in ("living_events", "collaboration_audit"):
        access = (  # noqa: S608 - static migration identifiers only
            "EXISTS (SELECT 1 FROM public.living_watches w "  # noqa: S608
            f"WHERE w.tenant_id = {table}.tenant_id AND w.id = {table}.watch_id)"
        )
        op.execute(
            f"CREATE POLICY {table}_select ON public.{table} FOR SELECT "
            f"USING (tenant_id = {tenant} AND {access})"
        )

    def editor(table: str) -> str:
        return (  # noqa: S608 - table comes only from literals in this migration
            f"({watch_owner(table)} OR EXISTS (SELECT 1 FROM public.collaboration_members m "  # noqa: S608
            f"WHERE m.tenant_id = {table}.tenant_id AND m.watch_id = {table}.watch_id "
            f"AND m.user_id = {actor} AND m.role = 'editor'))"
        )
    op.execute(f"""CREATE POLICY event_update ON public.living_events FOR UPDATE
        USING (tenant_id = {tenant} AND {editor('living_events')})
        WITH CHECK (tenant_id = {tenant} AND {editor('living_events')})""")
    op.execute(f"""CREATE POLICY event_insert ON public.living_events FOR INSERT
        WITH CHECK (tenant_id = {tenant} AND {watch_owner('living_events')})""")
    op.execute(f"""CREATE POLICY audit_insert ON public.collaboration_audit FOR INSERT
        WITH CHECK (tenant_id = {tenant} AND actor_user_id = {actor}
        AND {editor('collaboration_audit')})""")
    op.execute("""CREATE TRIGGER collaboration_audit_append_only BEFORE UPDATE OR DELETE
        ON public.collaboration_audit FOR EACH ROW
        EXECUTE FUNCTION public.scholarly_reject_mutation()""")
    for table, expr in {
        "collaboration_members": "role IN ('editor', 'viewer')",
        "living_watches": "status IN ('unknown', 'active', 'corrected', 'retracted')",
        "living_events": "decision IN ('open', 'relevant', 'dismissed', 'conflict', 'resolved')",
    }.items():
        op.execute(f"ALTER TABLE public.{table} ADD CONSTRAINT ck_{table}_state CHECK ({expr})")


def downgrade() -> None:
    raise RuntimeError("Preserve scholarly audit history; roll back application code only")
