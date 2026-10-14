"""Fail closed if runtime credentials can bypass the database security boundary."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def validate_runtime_role(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text("""
            SELECT r.rolsuper, r.rolbypassrls, r.rolcreatedb, r.rolcreaterole,
                r.rolreplication,
                EXISTS (SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS memberships,
                EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE c.relowner=r.oid AND n.nspname IN ('public','research_checkpoints'))
                    AS owns_objects,
                EXISTS (SELECT 1 FROM pg_namespace n
                    WHERE n.nspname IN ('public','research_checkpoints')
                    AND has_schema_privilege(r.oid,n.oid,'CREATE')) AS can_create
            FROM pg_roles r WHERE r.rolname=current_user
        """)
                )
            )
            .mappings()
            .one()
        )
    if any(row.values()):
        raise RuntimeError("Unsafe runtime database role; use a non-owner, restricted account")
