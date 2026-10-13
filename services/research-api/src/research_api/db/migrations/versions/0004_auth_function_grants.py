"""Remove Supabase default function grants from internal auth helpers.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ DECLARE role_name text; BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format(
                        'REVOKE ALL ON FUNCTION public.provision_research_account(uuid,jsonb), '
                        'public.handle_research_auth_user(), public.touch_research_profile() '
                        'FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    # Do not restore unsafe grants when rolling application code back.
    pass
