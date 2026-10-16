# Observability

## Request and failure diagnostics (2026-10-14)

Default logging is now signal-first. `RESEARCH_LOG_LEVEL=INFO` retains lifecycle,
provider outcomes, failures, and synthesis finding counts. Successful tenant
transactions, auth verification, snapshot collections and header timings are
DEBUG records. `DATABASE_SLOW_STATEMENT_MS=1000` controls slow-statement warnings;
failures remain visible regardless of duration. Set `RESEARCH_LOG_LEVEL=DEBUG`
for the API and Next.js process when investigating fine-grained timing.
The proxy emits one normal JSON completion record rather than three phase logs;
aborted browser requests are disconnects (499), not upstream failures (503).
SSE connection lifetime is not generation latency. Provider errors are not hidden.

The Next.js research proxy generates an `x-request-id`, forwards it to Python,
and returns it with successful upstream responses. JSON `research.proxy` logs
separate Auth verification, upstream response headers, and response completion.
Python `operation.outcome` logs cover request headers/completion, Auth, tenant
transactions (including connection/RLS setup time), configurable slow SQL statements,
SQL failures, graph nodes, collection failures and top-level graph failures.
SQL text, parameters, URLs, cookies, prompts and exception messages are excluded.
Exception groups expose at most eight leaf types, safe SQLSTATEs and code locations.

For SSE, `http.headers` / `firstByteMs` measure response-start latency; the total
`http.request` duration includes the entire connection lifetime. It is not report
generation latency. Transaction totals include work performed inside the context;
they are not exclusively SQL execution time. `db.statement.slow` isolates actual
driver round trips; exported tracing and dashboards are still not configured.

Parallel attempt insertion exposed a reproducible FK lock-upgrade deadlock in
the outbox. Sequence allocation now uses `FOR NO KEY UPDATE` with refreshed ORM
state: sequence writers remain serialized, while concurrent FK `KEY SHARE`
holders remain compatible. The local concurrency regression checks ordered,
unique sequences across three simultaneous tasks. No event ordering lock was removed.

History now uses one projection query instead of two. Snapshot run/budget/usage/
source-count reads share one query instead of four. Auth HTTP connections are
reused for the service lifespan, but identities are verified on every request:
there is no authorization cache or authentication bypass.

Development: use `--reload --reload-dir src/research_api` to exclude test edits.
Source edits still restart execution. Durable jobs/checkpoints now support bounded
restart recovery; ambiguous provider outcomes still require receipts, not blind
redispatch. For uninterrupted manual research, run without `--reload`. These
logging changes do not reset existing failed runs.

## Current instrumentation (2026-10-13)

The model ledger now records every explicit model attempt alongside provider
operations in `provider_calls` / `provider_call_reservations`. Start/completion
timestamps, outcomes, request IDs when supplied, pricing version, admission token
heuristic and received token counts allow tenant-scoped investigation. Unknown
usage stays explicitly estimated; uncertain spend stays reserved without proof.
Provider-supplied Tavily usage cannot override internal token/cost accounting.

At service lifespan startup, `research_api.dependencies` emits structured outcome
logs at INFO through the existing Uvicorn handlers (or a stream fallback). Records
include provider, operation, outcome, attempt, duration, a run UUID when in a graph
context, and a safe reason code. They exclude prompts, source URLs, raw responses,
API keys and exception messages. Context propagates to child graph tasks and is
reset at run exit. Do not enable SDK/HTTP debug body logging in production.

Provider durations and persisted node/call timestamps are measurement inputs,
not a measured production P95 or a configured dashboard. Queue age/first-evidence
latency and citation precision can be derived from run/task/source/check records;
exported metrics, OTel spans and aggregation/alerts remain later work. No new SSE
publication path is introduced; the PostgreSQL event log stays replay truth.

The sections below retain the broader target architecture. In particular,
checkpoint records, global retry orchestration and telemetry dashboards are not
implemented guarantees of this slice.

How a single research run stays traceable end to end. See
[events-and-sse.md](./events-and-sse.md) for the event log this is built
on and [reliability.md](./reliability.md) for the failure modes this
detects.

## What is tracked per run

| Signal | Source |
|---|---|
| Node events (`node.started`, `node.progress`) | Append-only event log |
| Provider telemetry (latency, status, provider used) | Provider adapter instrumentation, tied to `node_executions` |
| Token usage (input/output) | Accumulated into `ResearchState.usage` |
| Estimated cost | Accumulated into `ResearchState.usage.estimatedCostUsd`, checked against `budget.maxEstimatedCostUsd` |
| Search calls | `usage.searchCalls`, checked against `budget.maxSearchCalls` |
| Browser sessions | `usage.browserSessions`, checked against `budget.maxBrowserSessions` |
| Retries | `sub_question_attempts`, `node_executions.attempt` |
| Failures | `run.failed` events, `errorCode` on the run row |
| Checkpoints | LangGraph checkpointer records (see [database.md](./database.md#checkpointer-storage)) |
| SSE events | `run_events` table, replayable |

## End-to-end traceability

A single research run should be traceable purely from durable records —
no ad-hoc log-grepping required for the common case:

1. `GET /api/research/runs/:runId` gives current status, budget, and
   usage.
2. `GET /api/research/runs/:runId/events` (with no `Last-Event-ID`) gives
   the **complete ordered history** of everything the run did.
3. `node_executions` gives per-node attempt/retry detail if deeper
   inspection is needed.
4. `GET /api/research/sources/:sourceId` gives the verified excerpt behind
   any specific citation in the final report.

This is the intended first stop for the debugging workflow in
[agent.md](./agent.md#17-debugging-guide) — reproduce against the durable
projection and event log before adding new instrumentation.

## Latency

- P50/P95 latency is tracked per run and per node, and specifically per
  provider call (feeds the circuit breaker in
  [reliability.md](./reliability.md#circuit-breakers)).
- The evaluation benchmark (see [evaluation.md](./evaluation.md)) tracks
  mean and P95 end-to-end latency as a first-class metric.

## Cost

- `usage.estimatedCostUsd` is updated incrementally as the run progresses,
  not only at completion, so a run can be stopped before it silently blows
  past a tenant's cost expectations.
- Cost is broken down by provider and by LLM call in the underlying usage
  ledger (see [database.md](./database.md)) for post-hoc analysis.

## Dashboards (proposed)

`PROPOSED` — no dashboard tooling confirmed against a real repository.
Reasonable candidates once infrastructure is chosen: a metrics/tracing
stack fed by `node_executions`/provider telemetry, plus a simple
per-tenant usage view backed directly by the `usage_ledger` table.

## What NOT to rely on for observability

- Raw LLM token streaming (`report.delta`) is a UX affordance, not an
  observability signal — it does not tell you whether a node succeeded,
  retried, or failed.
- In-memory-only counters that don't survive a process restart — anything
  worth alerting on should be backed by the durable tables above.
