# Atomic lifecycle and submission foundation

## Scope and status

Implemented on 2026-10-14: roadmap milestones 1–3 and the bounded SSE read-path
portion of milestone 4. No new runtime framework, queue service, schema migration,
hosted database write, or deployment was introduced.

The system-design approach here is to put concurrent invariants at their existing
PostgreSQL ownership boundary and prove them with real local transactions.

## CI and safety gates

Test configuration respects explicitly supplied CI ports, instead of replacing
5432/4566 with development ports. All fixture databases and storage endpoints
must use loopback hosts; URI query overrides are rejected. Shared admin targets
are used by all integration fixtures, including the disposable auth-schema DB.
CI enables auth-schema tests, migrates with the owner principal, tests with the
non-owner application principal, and excludes paid live-provider tests.

Run locally from `services/research-api`:

```sh
RUN_AUTH_SCHEMA_TESTS=1 uv run pytest tests/unit tests/integration
uv run ruff check src tests
uv run mypy src
```

The GitHub-hosted CI job itself must still run after publication; local passing
tests are not evidence that a remote CI job has executed.

## Lifecycle invariant

Run writes use a tenant-scoped `FOR NO KEY UPDATE` lock with refreshed ORM state.
`ensure_active` checks terminal state and cancellation intent under that same lock.
Transition, plan persistence, plan expansion and report publication cannot advance
a stopped run. Node completion locks the run before the node row and does not
replace cancellation intent or a terminal failure with completion. Graph failure
handling also locks and rechecks before changing status.

Cancellation remains cooperative: an already dispatched network request may
finish and incur usage. This work prevents later lifecycle writes and dispatch
at existing cancellation boundaries; it does not promise instantaneous aborts.

## Submission invariant

`INSERT ... ON CONFLICT DO NOTHING RETURNING` arbitrates the existing
tenant/user/key uniqueness constraint. Only the insertion winner creates budget,
usage and creation events and schedules execution. A replay returns the original
run, while changed question, requirements, effective budget or parent report
conflicts with the stored request. There is no age-based key reuse.

The composer retains the key for retries of the same serialized draft and changes
it when the draft/scope changes. A synchronous ref prevents duplicate submissions
before React's busy state renders. It also displays string API `detail` errors.
The key is component-local, not a shared server cache or persistent browser history.

Follow-ups retain parent-report version scoping and lock the parent/gap. An existing
gap investigation link is not overwritten by a different submission. Same-key
replays return their existing run. A second key receives 409 and must open the
existing investigation; failed runs may use the existing retry endpoint, but this
slice does not automatically relink gaps to retry descendants.

## SSE invariant

The BFF forwards `Last-Event-ID`; Python validates it and resumes after the greater
of the header/query cursors. One joined query reads run status and up to 128 events
per poll. Full replay pages drain immediately, including terminal runs; the stream
does not stop before the remaining committed events have been delivered.
Idle live streams still poll every second. PostgreSQL remains replay truth;
notifications, cross-client fan-out, bounded connection lifetimes and delta
projections remain subsequent work.

Events now pass a dictionary to `ServerSentEvent.data`, not a pre-encoded JSON
string. The pinned FastAPI implementation JSON-encodes data itself. A real ASGI
wire-format test catches double encoding and checks that one browser-style JSON
parse yields each event object and its numeric sequence.

## Remaining roadmap

Historical boundary: the subsequent [durable runtime](./durable-runtime.md)
implements the bounded versions of steps 4–8 below. Read that runbook for current
guarantees; the non-durable caveat below describes this earlier slice only.

4. Measure broader snapshot/ingestion overhead and isolate persistence failures.
5. Simplify synthesis while preserving exact-span and semantic verification.
6. Add proof-backed accounting reconciliation and stored-result replay.
7. Add bounded durable dispatch/checkpoints, graph-version compatibility, tenant
   authorization, checkpoint retention and crash/restart recovery.
8. Add approval-aware lifecycle states, then batch/schedules.

API-process tasks are still non-durable. A crash after the create transaction
commits but before scheduling can strand the queued run; idempotency does not
solve this recovery window. No automatic uncertain-spend refunds were added.
