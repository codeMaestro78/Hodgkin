# Historical Alembic 0009–0012 rollout notes and current recovery guidance

> **Current-checkout warning (2026-10-17):** this document was originally
> written for revisions `0009`–`0012`. The current checkout's Alembic head is
> `0019`; this guide is not a complete deployment checklist for the current
> API. Before deploying this code, inspect the target database's actual
> revision and review/apply every required migration through the current
> checkout head. Do not infer that Supabase is at `0019` from this document or
> from local Alembic state.

These instructions cover Alembic revisions `0009` (private projects/library),
`0010` (published-report immutability, report shares, and stored Markdown /
BibTeX exports), `0011` (persisted per-run model routing), and `0012`
(compatibility for legacy published-report inserts). This repository uses
Alembic as the migration authority; it does not use `supabase/migrations` or
`supabase db push` for these changes.

## Preconditions

1. Confirm the target project and database from the deployment secret source;
   never paste the connection URL into a ticket, terminal transcript, or chat.
2. Check `alembic current` against the target. Review every pending revision;
   do not use `stamp` or migration-repair commands to bypass schema history.
3. Confirm a recent database backup/PITR point is available and that the team
   knows how to restore it. Prefer a restore to a separate project for rehearsal.
4. Run the tested release against a disposable database from both a fresh
   migration chain and the immediately preceding revision. Verify runtime-role
   grants, forced RLS, report immutability, share expiry/revocation, and export
   download authorization before production.
5. Use the dedicated migration principal via the protected
   `services/research-api/.env.migrations` file. Do not use the runtime role for
   schema changes. Ensure only one operator runs the migration at a time.

## Apply

For the historical `0009`–`0012` release only, after the preconditions pass,
from `services/research-api` run:

```sh
uv run alembic upgrade head
uv run alembic current
```

The historical release ended at `0012`. The current checkout ends at `0019`;
running `alembic upgrade head` from this checkout applies every pending
revision through that head. Review those later migration files and rehearse
them on a disposable database before applying them to any shared target.
`0010` intentionally keeps old application writers
compatible: legacy published inserts receive `published_at` from the database,
may have a null stored `content_hash`, and are still immutable after insert.
The current writer stores a SHA-256 hash; readers compute one for legacy rows
that do not have it.

For the historical release, verify `0012` and the checks below. For the
current checkout, verify `alembic current` reports at least `0019` and that
the API `/health/ready` endpoint succeeds before deploying matching code.
Verify before deploying the UI that:

- the target revision matches the release being deployed (current checkout:
  `0019`; historical `0009`–`0012` release: `0012`);
- `research_runs.model_routing` exists and is readable/writable by the runtime
  role as required by the API;
- `projects`, `library_items`, `report_shares`, and `report_exports` exist;
- RLS and FORCE RLS are enabled on the new tenant-owned tables;
- `reports_immutable_after_publish` is enabled;
- the runtime role has only the intended table/column privileges;
- a canary report can be saved/exported, its share can be read, and revocation
  makes the next read return not-found.

Then deploy the matching API and web build, watch readiness, migration errors,
share/export outcomes, and research completion. Keep the prior app artifact
available until canary validation is complete.

## Application rollback

Rollback the application artifact, **not** the database schema. Revisions
`0009`–`0012` are additive, and `0010`/`0012` deliberately allow compatible
legacy report inserts while continuing to reject updates to already-published
reports. Keep the tables, trigger, migration history, shares, and export
artifacts in place.
Disable the new UI entry points if necessary; do not drop tables or manually
disable the immutability trigger as a routine rollback.

If the old app fails a write smoke test, stop research dispatch and keep the
service in maintenance mode. Roll forward with a compatible API fix. Do not
remove the trigger or issue an Alembic downgrade to get writes moving again.

## Database recovery / schema reversal

Revisions `0009` through `0012` refuse automatic downgrade because they contain
user data, persisted model-routing state, or compatibility behavior required by
rolling application versions. In particular, `0012` must not restore the prior
trigger while old writers may still be deployed. These refusals are intentional.
There is no safe generic `alembic downgrade` or ad-hoc `DROP TABLE` procedure.

If a database-level rollback is required:

1. Stop API workers and research dispatch; prevent new writes.
2. Preserve the current database snapshot and identify the required recovery
   point. Record the expected loss window and get the data owner/operator's
   approval before restoring data.
3. Restore the snapshot/PITR point into a separate recovery project first.
4. Validate schema revision, user/run/report counts, runtime-role permissions,
   and application smoke tests there.
5. Switch traffic only after the restored target is approved. Keep the failed
   database intact for forensic comparison until recovery is confirmed.

Restoring an older point may lose projects/library organization, share revokes,
or exports created after that point. A database restore is therefore a data
recovery event, not a routine code rollback. Do not edit migration history to
pretend a revision was undone.

Supabase recommends deploying versioned migrations and checking migration
history rather than making untracked remote schema edits; see its
[database migration guide](https://supabase.com/docs/guides/deployment/database-migrations)
and [backup/restore guidance](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore).
