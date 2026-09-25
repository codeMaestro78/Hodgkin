# Observability

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
