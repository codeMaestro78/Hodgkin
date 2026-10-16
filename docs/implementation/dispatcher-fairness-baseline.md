# Dispatcher fairness baseline

2026-10-16: real local PostgreSQL characterization and bounded claim fix.

## Executed evidence

The baseline reproduction used `APP_ENV=test`, fixture principals
`research_app` / `research_owner`, loopback port 55432, and database
`research_quality_validation_20261016`. No provider, object-storage or Redis
network calls were used. The current test validates loopback URLs and that the
application/admin URLs target the same database; it does not pin the port, name,
or role names.

Unchanged characterization, before adding the gate:

```text
.                                                                        [100%]
1 passed in 1.51s
```

Both tests on baseline (`pytest -p no:cacheprovider --tb=short`):

```text
.F                                                                       [100%]
E   Failed: tenant B did not execute while tenant A registry remained held; PostgreSQL observed claim blocked by holder: True
FAILED tests/integration/test_dispatcher_fairness_characterization.py::test_busy_registry_does_not_block_later_tenant_execution
1 failed, 1 passed in 4.83s
```

The gate is intentionally failing, not skipped or marked xfail. It requires B's
execution event before releasing A's registry transaction. On baseline, an
autocommit observer establishes an actual `pg_blocking_pids()` wait, followed by
a bounded event wait. The old characterization additionally checks B's untouched
queued ownership/generation and verifies execution after release. Only discovery
ordering and execution are mocked; claiming, enqueueing, registry locks and the
dispatcher loop are real. Completion here means the execution stub returned,
not that a research graph or report completed. UUID-scoped fixture rows are
cleaned up, including on failure.

## Implemented claim-only change

- Select the existing tenant registry row with `FOR UPDATE SKIP LOCKED` inside
  the claim transaction. Return `None` immediately when busy or absent, before
  scheduling, job selection or registry refresh. Keep the row lock until commit
  across all subsequent claim logic.
- Do not change `lock_registry()`: enqueue and API callers rely on creating a
  missing row and serializing queue/schedule mutations. Discovery returns
  committed registry rows, but a stale/missing ID should still fail closed.
- Current `schedule_due()` uses the same session, calls `create_once()`, inserts
  jobs directly, and appends outbox events. It calls neither `lock_registry()`
  nor `enqueue()`, so there is no current nested registry acquisition to adjust.
  Retaining the outer lock preserves its queue-limit and schedule serialization.
  Any later nested registry operation must use the same session/transaction;
  a separate transaction would contend with the outer lock.
- A busy return must not clear or postpone `next_due_at`; normal later polling
  retries. A missing return does not repair a registry row.
- This gate proves progress past one busy tenant with free worker capacity. It
  does not prove global fairness, absence of waits later in claim, or progress
  past more than the discovery limit of 100 busy tenants.

The implementation changed registry selection to `FOR UPDATE SKIP LOCKED` and
returns without mutating queue or schedule state when the row is busy. The
forward-progress regression passed against local PostgreSQL after the change; the
full non-live backend suite also passed against a fresh database migrated through
`0011`.

Future work is measurement-led: quantify skip frequency and queue wait by tenant
before considering broader fairness policy or changing pool sizes. Keep the
baseline failure separate from the current green regression; do not make the old
broken-behavior assertion pass on fixed code.
