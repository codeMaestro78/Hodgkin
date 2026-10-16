# Pre-dispatch extraction admission and accounting operations

Implemented 2026-10-14. This closes the extraction-slot and operator-tool gaps
from the [core reliability slice](./core-reliability-slice.md). It does not add
durable graph recovery, checkpoints, worker leases or an accounting dashboard.

## Admission semantics

`ExtractionAdmissionRepository` takes a run-local **FOR NO KEY UPDATE** lock,
admits canonical URLs within the persisted ceiling, and commits slots together
with the provider-call reservation before extraction I/O. This lock serializes
admission without conflicting with the KEY SHARE locks taken by reservation
foreign keys. Source-persistence and ordered-outbox locks remain unchanged.

- Focused/Balanced/Deep retain 6/12/20 ceilings, derived from the existing budget.
  Quick explainers retain two; the persisted question also enforces quick mode.
- Only admitted URLs enter the extraction payload or become accepted evidence.
  Partial remaining capacity trims the payload before dispatch.
- Slots are tenant/run-scoped and canonical-URL deduplicated. Reserved, consumed
  and uncertain slots consume capacity. Known non-dispatched/rejected requests
  release slots; successful HTTP responses consume slots even if extraction or
  artifact storage later fails. No refund is based on elapsed time.
- A stored source can be reused with merged discovery paths and unchanged
  retrieval time, without another extraction call. This is not a fresh re-fetch.
- Pending/uncertain URLs with no stored evidence are not dispatched by another
  worker and are not waited on or represented as that worker's successful coverage.
  Dependency-aware waits/resume are part of durable execution, not this slice.
- Legacy source URLs are conservatively imported into the ledger inside the
  tenant-scoped admission transaction. No global privileged data scan is needed.

The limit is on distinct admitted canonical URLs in a run, not the number of
search-result snippets a search engine returns, full browser requests, or hidden
provider-internal redirects/subrequests. Failed/ambiguous attempted URLs may leave
fewer published sources than the ceiling. It is a maximum, not a completeness promise.

## Migration and safe rollout

Alembic `0006_extraction_admission` adds `extraction_slots` and a tenant/run/id
reservation uniqueness constraint for its composite foreign key. It enables and
forces tenant RLS, revokes PUBLIC/anon/authenticated access, and grants the local
server role only. The repository follows the existing Alembic schema workflow;
there is no second Supabase CLI migration history.

The migration was initially applied to local PostgreSQL. After explicit user
approval on 2026-10-14, the configured Supabase project was checked and was already
at revision `0006`. Read-only verification confirmed the expected columns,
uniqueness/composite foreign keys, enabled/forced RLS and tenant policy, and denied
SELECT/INSERT/UPDATE/DELETE for anon and authenticated roles. No hosted migration
was rerun and no database writes were made during this verification. Seven runs
were still marked nonterminal and were left untouched; their worker versions and
actual liveness were not certified.

For other environments, drain old API workers and in-flight research before
applying it: old workers do
not write admission slots and cannot be safely mixed with new admission code.
The uniqueness constraint requires an ordinary database DDL lock; zero-downtime
or production contention has not been measured. Restart with the new code only
after the migration succeeds. Do not drop the ledger while workers are active.

## Operator commands

Run these only from a trusted server environment with the application database
principal. This is **not user-facing authentication or an organization-admin API**.
Do not expose the command through a browser, tool server or untrusted shell input.
Tenant/run IDs choose the scope of an already privileged operator.

From `services/research-api`:

```sh
uv run python -m research_api.accounting_ops list --tenant-id TENANT_UUID --run-id RUN_UUID
uv run python -m research_api.accounting_ops list --tenant-id TENANT_UUID --run-id RUN_UUID --after-id LAST_RESERVATION_UUID
uv run python -m research_api.accounting_ops reconcile --tenant-id TENANT_UUID --run-id RUN_UUID --reservation-id RESERVATION_UUID
```

`list` returns at most 100 reserved/uncertain entries, including estimated reserved
cost, operation and receipt availability. It omits prompts, URLs, raw provider
bodies and credentials. Pagination is a live list, not a consistent snapshot;
repeat from the start when investigating concurrent changes.

`reconcile` validates tenant/run membership and uses the existing successful
receipt. It accepts no cost, token count, receipt upload or arbitrary state. It
does not retrieve receipts from providers or release unresolved uncertainty. A
trusted success receipt consumes an uncertain extraction slot without freeing
quota. Errors with missing proof leave accounting unchanged. Repeated successful
settlement is idempotent.

Scoped reconciliation takes the reservation lock before reading its lifecycle,
and repository lock reads refresh ORM identity-map state. Concurrent operators
and deliberately stale sessions are regression-tested so one receipt cannot
consume a reservation twice or make reserved totals negative.

## Validation

- Local Alembic upgrade from 0005 to 0006 passed; the disposable fresh-schema
  test covers all six migrations, profile auth, RLS and browser-role denial.
- 182 backend tests passed with `RUN_AUTH_SCHEMA_TESTS=1`. New tests count actual
  extraction payload URLs across concurrent workers, partial capacity, pending
  duplicates, cancellation, released slots, ambiguous timeouts, cached evidence,
  budget rollback and operator tenant/run isolation.
- Strict mypy passed on 40 source files; Ruff and changed-file formatting passed.
- Shared contracts remain unchanged. No paid provider calls or hosted writes.
- 34 generated contract schemas validated; 36 frontend and five contract tests
  passed; workspace TypeScript checks passed. No frontend behavior changed here.

RLS/grants were checked against [Supabase's RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).
