# Durable research runtime: milestones 4–8

Implemented in the checkout, with local PostgreSQL and mocked provider validation.
Migration **0007** was applied to the configured Supabase project on 2026-10-14
after explicit user approval and a fresh 21-test local migration/recovery check.
The hosted revision, forced RLS on all eight runtime/checkpoint data tables,
denied browser-role privileges, size constraints and tenant foreign keys were
verified. A transaction-only tenant-isolation probe passed; its fixture rows and
temporary verification grants were rolled back. No application deployment or
paid live-provider test was performed.

**Restricted runtime account configured (2026-10-14):** following explicit user
approval, `research_app` was created with a generated SCRAM password, no elevated
role flags, no memberships, and specific application-table grants. The local
server `.env` now uses it. Owner credentials are in ignored `.env.migrations`;
both files are mode 0600. Alembic loads the latter, while the API does not.
Startup and readiness reject privileged/owner runtime accounts. Restart any
already-running API to replace its old pool; remote deployment secrets have not
been changed. See [runtime role runbook](./runtime-role.md) for evidence and limits.

## What changed

| Milestone | Implementation | Acceptance evidence |
| --- | --- | --- |
| 4: persistence/performance | Source metadata batches of at most eight, per-source savepoints, artifact I/O outside transactions, pipelined snapshot collections | `test_ingestion_persistence.py`, `test_snapshot_collections.py`; good sources survive isolated metadata/artifact failures, cancellation escapes |
| 5: synthesis | Draft-only writer → assertion extraction → deterministic exact quotes → one semantic audit → supported findings | `test_synthesis_pipeline.py`, durable and legacy report-audit tests; rejected assertions stay inspectable |
| 6: accounting/replay | Server-persisted OpenAI response reuse; Tavily artifact receipts; proof-backed reconciliation CLI | `test_model_replay_accounting.py`; no duplicate charge, unknown spend stays reserved |
| 7: recovery | Atomic run/job/outbox submission; PostgreSQL leases, generation fences, official LangGraph PostgreSQL saver | `test_durable_runtime.py`, `test_checkpointing_postgres.py`; fresh pool resumes checkpoints without replanning; stale owners cannot write |
| 8: approval/automation | Default-on plan approval (including coverage repairs), immutable approve/reject decision, bounded batches and interval schedules | Local approval resume/rejection tests, concurrent scheduler tests, BFF tests and browser fixture |

Source metadata batching reduced transactions from six to one in the six-source
fixture; the corresponding measured SQL executions were 41 versus a calculated
60 for the prior per-source pattern. Snapshot collection still executes eight
SELECTs but pipelines them on the existing authorized tenant connection. The
loopback sample (15.07 ms sequential vs 14.97 ms pipelined medians) **does not
demonstrate a meaningful latency gain**. Measure production request p50/p95,
pool wait, and dependency timings before claiming a speed improvement.

## Runtime and security

The [deadline and failure-feedback fix](./deadline-and-failure-feedback.md) updates
new mode time budgets, fresh-worker overlap handling, visible errors, and idle SSE
polling. Existing failed runs and their paid-call records remain unchanged.

The later [mode-specific reports](./mode-specific-research-reports.md) supersede
the synthesis and evidence-bundle ceilings recorded below. Current jobs use
`research-v4` after [Phase 1 quality foundations](./phase1-quality-foundations.md).
V3 jobs with empty report requirements retain their unchanged request contract;
v3 jobs with requirements and v2/unknown recovery fail closed. Completed reports
remain unchanged.

- Requests commit the job together with the run and first event. No request-local
  fire-and-forget graph invocation remains. API lifespan drains jobs; use a
  long-running server, not an ephemeral/serverless request process.
- Defaults: `DISPATCHER_ENABLED=true`, `WORKER_CONCURRENCY=2` per process,
  `WORKER_LEASE_SECONDS=60`, `MAX_PENDING_RUNS_PER_TENANT=32` including waiting
  approvals. One-second polling; at most five recovery claims. These are not
  fleet-wide provider rate limits.
- Registry discovery is a reviewed coordination exception: only tenant IDs and
  wake-up timestamps are visible to the trusted server dispatcher. Jobs, research
  data, approvals and checkpoints require tenant RLS. Browser roles have no access.
- Short application and checkpoint transactions verify the current owner,
  generation and live lease under a shared job-row lock. Claim, decision and
  cancellation operations use registry → job → run lock order. Network calls
  never hold these locks. Expired or superseded workers cannot persist results.
- Checkpoints use `tenantUUID:runUUID`, root namespace, compact string/ID state,
  synchronous node-boundary durability, no pickle fallback or arbitrary module
  allowlist, 1 MiB serialization/database bounds. Migration metadata is owner-only.
  Graph version must be compatible with `research-v4` (only empty-requirement v3
  jobs retain compatibility); incompatible recovery fails closed.
- Active milliseconds accumulate through heartbeat and final settlement. A crash
  conservatively adds one lease interval for its unobserved tail. Human approval
  waiting does not consume active runtime. Restart does not reset the budget.
- Wrapped node cancellation is distinguished from user intent and from the
  wall-clock deadline. Shutdown leaves a leased job recoverable rather than
  recording an accidental terminal research failure.
- Original per-question dispatch slots are stored before network I/O, preserving
  the search fingerprint after partial persistence. Persisted initial/repair plans
  and completed questions are reused. Uncertain provider results are not redispatched.
- Checkpoint deletion is an internal, explicit `TenantPostgresSaver.adelete_thread`
  operation restricted to terminal runs. No automatic retention janitor is added;
  coordinate cleanup with report/evidence retention and disable workers for rollback.

## Approval and automation interfaces

The composer sends `requireApproval` (default true). Planner calls can consume
budget before approval; source collection starts only after approval. A bounded
coverage-repair plan also returns through the approval gate before new searches.
The snapshot
exposes `approval: {planId, state, questions}`. POST
`/research/runs/{id}/approve` with `{planId, decision: "approve" | "reject"}`
requires the authenticated owner, active plan and waiting job. Identical decisions
are idempotent; conflicting/stale decisions return 409. Reject or cancel closes
the waiting job and releases queue capacity without invoking the graph.

`/research/automation` provides:

- POST/GET `/research/batches`: 1–20 questions, stable `idempotencyKey`, approval
  choice and optional per-run `budgetOverrides`. Capacity failure rolls the entire
  batch back. Each question has a separate run and budget.
- POST/GET `/research/schedules`: question, stable `idempotencyKey`, whole
  `intervalMinutes` in 60–43,200, approval choice and optional budget. At most ten
  enabled schedules per tenant. First run occurs after the chosen interval.
- POST `/research/schedules/{id}/disable`: owner-only disable. It prevents future
  occurrences; already created runs must be cancelled separately.
- Due schedules are serialized by the tenant registry, with one occurrence after
  downtime, not a catch-up storm. Occurrence keys include the scheduled timestamp.
- All Next.js BFF POST routes forward their bodies with a 256 KiB byte limit,
  same-origin guard, verified Supabase session and internal server credentials.
  Changing parameters creates a new submission identity; retries reuse it.

Contracts are version 1.3, accepting prior 1.1/1.2 envelopes. Generated Python
models honor schema defaults, including the default approval choice.

## Accounting operations

From `services/research-api`, with the trusted service database credentials:

```sh
uv run python -m research_api.accounting_ops list --tenant-id TENANT_UUID --run-id RUN_UUID
uv run python -m research_api.accounting_ops reconcile --tenant-id TENANT_UUID --run-id RUN_UUID --reservation-id RESERVATION_UUID
uv run python -m research_api.accounting_ops release --tenant-id TENANT_UUID --run-id RUN_UUID --reservation-id RESERVATION_UUID
```

List pages contain at most 100 entries; use `--after-id` to paginate. Reconcile
requires an existing successful server receipt. Release requires existing trusted
server evidence of nonexecution. Operators cannot supply replacement costs or
proof bodies. No age-based refunds or automatic external receipt retrieval.

## Remaining limitations

This is at-least-once **execution with guarded replay**, not an exactly-once billing
guarantee. A provider may execute before a process dies without recording a usable
receipt; that case remains blocked/charged conservatively and needs investigation.
An unavailable/corrupt artifact receipt can also prevent replay. Local tests
simulate cancellation, lease expiry and a new pool, not an external kill of a
signed-in production deployment.

Plan approve/reject is shipped; plan editing and browser-action approval
are not. No browser provider exists in this slice. Batches use one question per
line, not CSV import. Schedules are intervals, not cron/timezone calendars, and
do not generate report diffs or notifications. Rewind UI, automatic checkpoint
retention, fleet-wide rate limits, public API keys/webhooks, exports/share/library
and academic adapters are separate work. The current mode-specific synthesis
bundle admits up to 6/12/20 content-deduplicated sources and selects bounded literal
query-ranked passages; this is not source-independence proof or comprehensive
retrieval. Rich draft tables still are not published directly.

## Validation commands

Recorded on 2026-10-14: **332 backend tests**, **51 frontend tests**, **8 shared
contract tests**, and **24 isolated browser checks** passed. Ruff, Python mypy
(48 source files), workspace TypeScript checks, 37 generated-schema validation,
Next.js production build, and `git diff --check` passed. The migration chain
through 0007 was exercised in a fresh disposable database with Supabase-like
browser roles; the final bounds and tenant foreign keys were also applied locally.
Those suite results are local validation. Hosted migration verification is recorded
above separately; neither constitutes paid-provider or production recovery validation.

```sh
# Local loopback infrastructure only, never hosted Supabase.
cd services/research-api
RUN_AUTH_SCHEMA_TESTS=1 uv run pytest tests/unit tests/integration -o addopts='' -q
uv run ruff check .
uv run mypy src
```

From the repository root using Node 24: `corepack pnpm test`,
`corepack pnpm typecheck`, `corepack pnpm contracts:check`, and
`corepack pnpm --filter @research/web build`. The isolated automation browser
fixture intercepts all API calls; it does not submit paid research.

Official semantics checked against [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
and [persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
