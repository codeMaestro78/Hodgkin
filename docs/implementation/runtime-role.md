# Restricted runtime database role

Configured on the approved Supabase project on 2026-10-14. Migration stays at
0007; this is account provisioning and permissions, not a data migration.

- `research_app` is a server-side database login, not a Supabase end-user role.
  Its password is randomly generated and stored as a SCRAM verifier in PostgreSQL.
- No SUPERUSER, BYPASSRLS, CREATEDB, CREATEROLE, REPLICATION or inherited roles.
  It owns no application objects and cannot create objects in application schemas.
- Explicit SELECT/INSERT/UPDATE grants cover the current runtime tables. Users
  are read-only; checkpoint data additionally permits DELETE for terminal cleanup.
  No blanket/default grants, migration metadata, auth identities or bootstrap
  function permissions. The reviewed registry discovery exception still applies.
- `.env` contains the restricted runtime URL. `.env.migrations` contains the
  original migration-owner URL; only Alembic loads that separate file. Explicit
  `DATABASE_ADMIN_URL` environment overrides remain supported for CI.
- Both secret files are ignored by Git and chmod 0600. No secret was printed or
  committed. Do not load `.env.migrations` into an API container. File separation
  on one development account is not OS/process isolation: production should give
  migration secrets only to a separate deployment job, not the runtime host.
- Startup/readiness fail closed on elevated flags, memberships, application
  ownership or schema CREATE privileges. This prevents accidentally switching
  the API back to `postgres`; it is not a full security certification.

`infra/postgres/runtime-role.sql` documents the exact initial grants for hosted
provisioning. It intentionally refuses to overwrite an existing role and creates
a NOLOGIN role until a password is separately set. Never put passwords in this SQL
file. Future runtime tables need explicit reviewed grants in their migration.

## Verification

The actual restricted hosted login passed: owned run/budget/ledger writes,
outbox writes, durable enqueue, pipelined reads, and checkpoint DML. Reads in one
tenant context hid other tenants. Cross-tenant checkpoint insertion, persistent
schema creation, SET ROLE postgres, auth.users, Alembic metadata and checkpoint
migration metadata were denied with SQLSTATE 42501. These were transaction-only
checks, rolled back without submitting any paid work or retaining test research.
Alembic still connected using the separate owner file and reported 0007 (head).

Local regression tests include acceptance of restricted flags and rejection of
each unsafe flag. The full backend suite passed 341 tests after this change.

## Activation and scope

Restart the research API so its connection pool reads the new `.env`. No service
was restarted here, avoiding unrequested execution of queued paid research.
Other deployed instances need their own runtime DATABASE_URL updated securely;
changing this checkout does not update remote deployment secrets.

RLS enforces the tenant context selected by the trusted server, not a separate
database account per customer. The backend still must authenticate callers and
set the correct tenant transaction context. Possession of server database
credentials or arbitrary SQL execution is not an end-user authorization mechanism.
Google/email sign-in and the browser's publishable key are unchanged.
